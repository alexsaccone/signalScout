from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
from email.utils import parsedate_to_datetime
from itertools import product
from urllib.parse import quote

if __package__:
    from .api import KALSHI_URL, POLY_US, POLY_US_URL, fetch_json, utc_timestamp
else:
    from api import KALSHI_URL, POLY_US, POLY_US_URL, fetch_json, utc_timestamp

CLOB_URL = "https://clob.polymarket.com"
US_STANDARD_TAKER_RATE = Decimal("0.095")
MAX_QUOTE_AGE = timedelta(seconds=60)
CLOCK_SKEW = timedelta(seconds=5)
SIDES = (("yes", "no"), ("no", "yes"))

OUTPUT_FIELDS = (
    "kalshi_id", "polymarket_id", "kalshi_name", "polymarket_name",
    "kalshi_side", "polymarket_side", "polymarket_token",
    "kalshi_ask", "polymarket_ask", "max_contracts", "quote_at", "valid_until",
    "estimated_fees", "estimated_cost", "estimated_net_profit", "net_return_pct",
    "polymarket_venue", "closes_at", "capital_until", "daily_roi_pct",
    "minimum_payout", "rule_difference",
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


def polymarket_us_quotes(market, fetch):
    slug = quote(market["id"], safe="")
    data = fetch(f"{POLY_US_URL}/v1/markets/{slug}/book")[0]["marketData"]
    if data["marketSlug"] != market["id"] or data["state"] != "MARKET_STATE_OPEN":
        return {}
    observed_at = utc_timestamp(data["transactTime"])
    if market["minimum_trade_qty"] is None:
        return {}
    minimum = venue_number(market["minimum_trade_qty"])
    if not minimum.is_finite() or minimum <= 0:
        return {}
    quotes = {}
    offers = [(venue_number(row["px"]["value"]), venue_number(row["qty"]))
              for row in data["offers"] if row["px"]["currency"] == "USD"]
    bids = [(venue_number(row["px"]["value"]), venue_number(row["qty"]))
            for row in data["bids"] if row["px"]["currency"] == "USD"]
    if offers:
        price, size = min(offers)
        quotes["yes"] = Quote(price, size, observed_at, minimum)
    if bids:
        price, size = max(bids)
        quotes["no"] = Quote(1 - price, size, observed_at, minimum)
    return quotes


def opportunity(left, right, kalshi, poly, k_side, p_side, k_rate, p_rate, now,
                minimum_per_pair=Decimal(1), rule_difference=None):
    if not (left and right and left.usable(now) and right.usable(now)):
        return None
    size = min(left.size, right.size).to_integral_value(rounding=ROUND_FLOOR)
    if size < max(left.minimum, right.minimum):
        return None

    kalshi_base = left.price * size
    model_fee = (k_rate * kalshi_base * (1 - left.price)).quantize(Decimal(".000001"), rounding=ROUND_CEILING)
    kalshi_cost = (kalshi_base + model_fee).quantize(Decimal(".01"), rounding=ROUND_CEILING)
    poly_base = right.price * size
    poly_fee = p_rate * poly_base * (1 - right.price)
    if poly.get("venue") == POLY_US:
        poly_fee = poly_fee.quantize(Decimal(".01"), rounding=ROUND_HALF_EVEN)
    else:
        poly_fee = poly_fee.quantize(Decimal(".00001"), rounding=ROUND_CEILING)
    cost = kalshi_cost + poly_base + poly_fee
    minimum_payout = minimum_per_pair * size
    profit = minimum_payout - cost
    if profit <= 0:
        return None

    quoted_at = min(left.observed_at, right.observed_at)
    closes_at = min(kalshi["close_time"], poly["close_time"])
    capital_until = max(kalshi["close_time"], poly["close_time"])
    days = Decimal(str((capital_until - quoted_at).total_seconds())) / Decimal(86400)
    if days <= 0:
        return None
    net_return = 100 * profit / cost
    return {
        "kalshi_id": kalshi["id"], "polymarket_id": poly["id"],
        "kalshi_name": kalshi["title"], "polymarket_name": poly["title"],
        "kalshi_side": k_side, "polymarket_side": p_side, "polymarket_token": poly["tokens"][p_side],
        "kalshi_ask": left.price, "polymarket_ask": right.price, "max_contracts": size,
        "quote_at": quoted_at.isoformat(),
        "valid_until": min(quoted_at + MAX_QUOTE_AGE, kalshi["close_time"], poly["close_time"]).isoformat(),
        "estimated_fees": kalshi_cost - kalshi_base + poly_fee,
        "estimated_cost": cost, "estimated_net_profit": profit, "net_return_pct": net_return,
        "polymarket_venue": poly.get("venue", "polymarket"), "closes_at": closes_at.isoformat(),
        "capital_until": capital_until.isoformat(), "daily_roi_pct": net_return / days,
        "minimum_payout": minimum_payout, "rule_difference": rule_difference,
    }


def minimum_payouts(scenarios):
    """Compute the worst-case payout of each two-leg position from a complete proof."""
    values = {"no": Decimal(0), "50-50": Decimal("0.5"), "yes": Decimal(1)}
    if not scenarios or any(not isinstance(case, (list, tuple)) or len(case) != 2
                            or any(not isinstance(side, str) or side not in values for side in case)
                            for case in scenarios):
        return {}
    pairs = [(values[left], values[right]) for left, right in scenarios]
    return {
        (k_side, p_side): min((left if k_side == "yes" else 1 - left) +
                              (right if p_side == "yes" else 1 - right) for left, right in pairs)
        for k_side, p_side in product(("yes", "no"), repeat=2)
    }


def price_pairs(pairs, clock, fetch=fetch_json, shared_rules=None):
    opportunities = []
    for kalshi, poly in pairs:
        proof = shared_rules.get((kalshi["id"], poly["id"])) if shared_rules else None
        minimums = minimum_payouts(proof["payout_scenarios"]) if proof else dict.fromkeys(SIDES, Decimal(1))
        if not any(minimums.values()):
            continue
        try:
            k_rate = kalshi_fee_rate(kalshi, fetch)
            is_us = poly.get("venue") == POLY_US
            if is_us:
                coefficient = poly.get("fee_coefficient")
                published_rate = US_STANDARD_TAKER_RATE if coefficient is None else venue_number(coefficient)
                p_rate = max(US_STANDARD_TAKER_RATE, published_rate) if published_rate.is_finite() and published_rate >= 0 else None
            else:
                p_rate = polymarket_fee_rate(poly, fetch)
            if k_rate is None or p_rate is None or not k_rate.is_finite() or k_rate < 0:
                continue
            quotes = kalshi_quotes(kalshi, fetch)
            poly_quotes = polymarket_us_quotes(poly, fetch) if is_us else {}
            for (k_side, p_side), minimum in minimums.items():
                if not minimum or k_side not in quotes:
                    continue
                if not is_us and p_side not in poly_quotes:
                    poly_quotes[p_side] = polymarket_quote(poly["tokens"][p_side], fetch)
                now = clock()
                if now >= min(kalshi["close_time"], poly["close_time"]):
                    continue
                result = opportunity(quotes[k_side], poly_quotes.get(p_side), kalshi, poly, k_side, p_side,
                                     k_rate, p_rate, now, minimum, proof["rule_difference"] if proof else None)
                if result is not None:
                    opportunities.append(result)
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
            raise ValueError("Invalid order-book or fee response") from error
    publish_time = clock()
    return sorted(
        (row for row in opportunities if publish_time < datetime.fromisoformat(row["valid_until"])),
        key=lambda row: row["daily_roi_pct"], reverse=True,
    )
