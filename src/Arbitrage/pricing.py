from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from email.utils import parsedate_to_datetime
from urllib.parse import quote

if __package__:
    from .api import KALSHI_URL, fetch_json
else:
    from api import KALSHI_URL, fetch_json

CLOB_URL = "https://clob.polymarket.com"
MAX_QUOTE_AGE = timedelta(seconds=60)
CLOCK_SKEW = timedelta(seconds=5)
SIDES = (("yes", "no"), ("no", "yes"))

OUTPUT_FIELDS = (
    "kalshi_id", "polymarket_id", "kalshi_name", "polymarket_name",
    "kalshi_side", "polymarket_side", "polymarket_token",
    "kalshi_ask", "polymarket_ask", "max_contracts", "quote_at", "valid_until",
    "estimated_fees", "estimated_cost", "estimated_net_profit", "net_return_pct",
)


@dataclass(frozen=True)
class Quote:
    price: Decimal
    size: Decimal
    observed_at: datetime
    minimum: Decimal = Decimal(1)

    def usable(self, now):
        return (
            self.price.is_finite() and 0 < self.price < 1
            and self.size.is_finite() and self.size > 0
            and self.minimum.is_finite() and self.minimum > 0
            and -CLOCK_SKEW <= now - self.observed_at <= MAX_QUOTE_AGE
        )


def venue_number(value):
    return Decimal(str(value))


def kalshi_fee_rate(market, fetch):
    event_id = quote(market["event_id"], safe="")
    event = fetch(f"{KALSHI_URL}/events/{event_id}")[0]["event"]
    fee_type, multiplier = event.get("fee_type_override"), event.get("fee_multiplier_override")
    if fee_type is None or multiplier is None:
        series_id = quote(event["series_ticker"], safe="")
        series = fetch(f"{KALSHI_URL}/series/{series_id}")[0]["series"]
        fee_type = series["fee_type"] if fee_type is None else fee_type
        multiplier = series["fee_multiplier"] if multiplier is None else multiplier
    if fee_type not in {"quadratic", "quadratic_with_maker_fees"}:
        return None
    return Decimal("0.07") * venue_number(multiplier)


def kalshi_quotes(market, fetch):
    ticker = quote(market["id"], safe="")
    payload, headers = fetch(f"{KALSHI_URL}/markets/{ticker}/orderbook", {"depth": 1})
    book = payload["orderbook_fp"]
    observed_at = parsedate_to_datetime(headers["Date"]).astimezone(timezone.utc)
    quotes = {}
    for side, opposite in SIDES:
        bids = book[f"{opposite}_dollars"] or []
        if bids:
            bid, size = max((venue_number(price), venue_number(size)) for price, size in bids)
            quotes[side] = Quote(1 - bid, size, observed_at)
    return quotes


def polymarket_fee_rate(market, fetch):
    condition_id = quote(market["id"], safe="")
    metadata = fetch(f"{CLOB_URL}/clob-markets/{condition_id}")[0]
    if metadata["c"] != market["id"] or {token["o"].casefold(): token["t"] for token in metadata["t"]} != market["tokens"]:
        return None
    fee = metadata.get("fd")
    if fee is None:
        return Decimal(0) if market["fees_enabled"] is False else None
    rate = venue_number(fee["r"])
    if not rate.is_finite() or rate < 0:
        return None
    return rate if rate == 0 or fee.get("e") == 1 else None


def polymarket_quote(token, fetch):
    book = fetch(f"{CLOB_URL}/book", {"token_id": token})[0]
    if book["asset_id"] != token or not book["asks"]:
        return None
    observed_at = datetime.fromtimestamp(int(book["timestamp"]) / 1000, tz=timezone.utc)
    price, size = min((venue_number(row["price"]), venue_number(row["size"])) for row in book["asks"])
    return Quote(price, size, observed_at, venue_number(book["min_order_size"]))


def opportunity(left, right, kalshi, poly, k_side, p_side, k_rate, p_rate, now):
    if not (left and right and left.usable(now) and right.usable(now)):
        return None
    size = min(left.size, right.size).to_integral_value(rounding=ROUND_FLOOR)
    if size < max(left.minimum, right.minimum):
        return None

    kalshi_base = left.price * size
    model_fee = (k_rate * kalshi_base * (1 - left.price)).quantize(Decimal(".000001"), rounding=ROUND_CEILING)
    kalshi_cost = (kalshi_base + model_fee).quantize(Decimal(".01"), rounding=ROUND_CEILING)
    poly_base = right.price * size
    poly_fee = (p_rate * poly_base * (1 - right.price)).quantize(Decimal(".00001"), rounding=ROUND_CEILING)
    cost = kalshi_cost + poly_base + poly_fee
    profit = size - cost
    if profit <= 0:
        return None

    quoted_at = min(left.observed_at, right.observed_at)
    return {
        "kalshi_id": kalshi["id"], "polymarket_id": poly["id"],
        "kalshi_name": kalshi["title"], "polymarket_name": poly["title"],
        "kalshi_side": k_side, "polymarket_side": p_side, "polymarket_token": poly["tokens"][p_side],
        "kalshi_ask": left.price, "polymarket_ask": right.price, "max_contracts": size,
        "quote_at": quoted_at.isoformat(),
        "valid_until": min(quoted_at + MAX_QUOTE_AGE, kalshi["close_time"], poly["close_time"]).isoformat(),
        "estimated_fees": kalshi_cost - kalshi_base + poly_fee,
        "estimated_cost": cost, "estimated_net_profit": profit, "net_return_pct": 100 * profit / cost,
    }


def price_pairs(pairs, clock, fetch=fetch_json):
    opportunities = []
    for kalshi, poly in pairs:
        try:
            k_rate = kalshi_fee_rate(kalshi, fetch)
            p_rate = polymarket_fee_rate(poly, fetch)
            if k_rate is None or p_rate is None or not k_rate.is_finite() or k_rate < 0:
                continue
            quotes = kalshi_quotes(kalshi, fetch)
            for k_side, p_side in SIDES:
                if k_side not in quotes:
                    continue
                right = polymarket_quote(poly["tokens"][p_side], fetch)
                now = clock()
                if now >= min(kalshi["close_time"], poly["close_time"]):
                    continue
                result = opportunity(quotes[k_side], right, kalshi, poly, k_side, p_side, k_rate, p_rate, now)
                if result is not None:
                    opportunities.append(result)
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
            raise ValueError("Invalid order-book or fee response") from error
    publish_time = clock()
    return sorted(
        (row for row in opportunities if publish_time < datetime.fromisoformat(row["valid_until"])),
        key=lambda row: row["net_return_pct"], reverse=True,
    )
