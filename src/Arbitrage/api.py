from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from itertools import batched
import re
import json
import logging
from time import sleep

import requests

KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2"
GAMMA_URL = "https://gamma-api.polymarket.com"
POLY_US_URL = "https://gateway.polymarket.us"
POLY_US = "polymarket_us"
MAX_DISCOVERY_DAYS = 1095
MAX_DISCOVERY_WINDOW = timedelta(days=MAX_DISCOVERY_DAYS)
PUBLIC_SLUG = re.compile(r"[a-z0-9-]+")
SCAN_WINDOW = timedelta(days=30)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ScanError(RuntimeError):
    pass


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def binary_values(value):
    values = json.loads(value) if isinstance(value, str) else value
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Expected exactly two values")
    return values


def fetch_json(url, params=None, get=None):
    get = get or requests.get
    for attempt in range(3):
        try:
            response = get(url, params=params, timeout=(5, 15))
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == 2:
                raise ScanError(f"{url}: connection failed after three attempts") from error
            sleep(2 ** attempt)
            continue
        except requests.RequestException as error:
            raise ScanError(f"{url}: request failed") from error

        if response.status_code in RETRY_STATUSES and attempt < 2:
            retry_after = response.headers.get("Retry-After")
            delay = 2 ** attempt
            if retry_after:
                try:
                    if retry_after.isdecimal():
                        delay = int(retry_after)
                    else:
                        delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
            sleep(min(10, max(0, delay)))
            continue

        try:
            response.raise_for_status()
            return response.json(), response.headers
        except (requests.RequestException, ValueError) as error:
            raise ScanError(f"{url}: HTTP {response.status_code} or invalid JSON") from error


def normalize_market(market, venue, now, window=SCAN_WINDOW):
    try:
        if venue == "kalshi":
            if (market["status"] not in {"active", "open"} or market["market_type"] != "binary"
                    or market.get("mve_collection_ticker") or market.get("mve_selected_legs")):
                return None
            close = utc_timestamp(market["close_time"])
            if market.get("expected_expiration_time") and utc_timestamp(market["expected_expiration_time"]) <= now:
                return None
            normalized = {
                "id": market["ticker"],
                "event_id": market["event_ticker"],
                "title": market["title"],
                "subtitle": market.get("yes_sub_title") or market.get("subtitle") or "",
                "rules": market.get("rules_primary") or "",
                "secondary_rules": market.get("rules_secondary") or "",
                "resolution": {key: market[key] for key in (
                    "strike_type", "floor_strike", "cap_strike", "functional_strike",
                    "occurrence_datetime", "early_close_condition",
                ) if market.get(key) is not None} or "",
                "close_time": close,
            }
        elif venue == POLY_US:
            if (market["active"] is not True or market["closed"] is not False or market.get("archived")
                    or market.get("hidden") or market.get("status") != "MARKET_STATUS_OPEN"):
                return None
            close = utc_timestamp(market["endDate"])
            sides = binary_values(market["marketSides"])
            if ({side.get("long") for side in sides} != {False, True}
                    or any(side.get("tradable") is not True for side in sides)):
                return None
            slug = market["slug"]
            if not isinstance(slug, str) or not PUBLIC_SLUG.fullmatch(slug):
                raise ValueError("Invalid Polymarket US symbol")
            tokens = {"yes" if side["long"] else "no": side["id"] for side in sides}
            if (len(set(tokens.values())) != 2 or any(not isinstance(token, str) or not token.isascii()
                                                     or not token.isdigit() for token in tokens.values())
                    or any(side.get("identifier") != slug for side in sides)):
                raise ValueError("Invalid Polymarket US side identifiers")
            title = market.get("title") or market["question"]
            normalized = {
                "id": slug, "venue": POLY_US, "title": title, "subtitle": "",
                "rules": market.get("description") or "", "secondary_rules": "",
                "resolution": "", "tokens": tokens, "close_time": close,
                "minimum_trade_qty": market.get("minimumTradeQty"),
                "fee_coefficient": market.get("feeCoefficient"),
            }
            event = next(iter(market.get("events") or []), {})
            event_slug = event.get("slug")
            if not event_slug and slug.startswith("nphc-"):
                event_slug = slug.removeprefix("nphc-").rsplit("-", 1)[0]
            if isinstance(event_slug, str) and PUBLIC_SLUG.fullmatch(event_slug):
                normalized["url"] = f"https://polymarket.us/event/{event_slug}"
        else:
            if market["closed"] is not False or market["active"] is not True or market["acceptingOrders"] is not True:
                return None
            close = utc_timestamp(market.get("endDate") or market["endDateIso"])
            outcomes = [side.casefold() for side in binary_values(market["outcomes"])]
            if set(outcomes) != {"yes", "no"}:
                return None
            tokens = dict(zip(outcomes, binary_values(market["clobTokenIds"])))
            if (not all(isinstance(token, str) and token.isascii() and token.isdigit() for token in tokens.values())
                    or tokens["yes"] == tokens["no"]):
                raise ValueError("Invalid outcome tokens")
            normalized = {
                "id": market["conditionId"],
                "title": market["question"],
                "subtitle": "",
                "rules": market.get("description") or "",
                "secondary_rules": "",
                "resolution": market.get("resolutionSource") or "",
                "tokens": tokens,
                "fees_enabled": market.get("feesEnabled"),
                "close_time": close,
            }
        keys = ("id", "title", "event_id") if venue == "kalshi" else ("id", "title")
        if not all(isinstance(normalized[key], str) and normalized[key].strip() for key in keys):
            raise ValueError("Missing market ID or title")
        if not all(isinstance(normalized[key], str) for key in ("rules", "secondary_rules", "subtitle")):
            raise ValueError("Invalid market text")
        if not now < close <= now + window:
            return None
        return normalized
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Malformed {venue} market ({type(error).__name__})") from error


def normalize_markets(rows, venue, now, window=SCAN_WINDOW):
    result = []
    valid = malformed = 0
    for row in rows:
        try:
            market = normalize_market(row, venue, now, window)
        except ValueError:
            malformed += 1
            continue
        valid += 1
        if market is not None:
            result.append(market)
    if malformed:
        logging.warning("Skipped %d malformed %s market records", malformed, venue)
        if not valid:
            raise ScanError(f"{venue} returned no readable market records")
    return result


def market_rows(url, params, response_cursor, request_cursor, pages):
    seen = set()
    with requests.Session() as session:
        for _ in range(pages):
            payload, _ = fetch_json(url, params, get=session.get)
            if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
                raise ScanError(f"{url}: invalid market page")
            if response_cursor == "cursor" and response_cursor not in payload:
                raise ScanError(f"{url}: missing pagination cursor")
            rows = payload["markets"]
            cursor = payload.get(response_cursor, "")
            if not isinstance(cursor, str) or cursor in seen or (cursor and not rows):
                raise ScanError(f"{url}: invalid or repeated pagination cursor")
            yield from rows
            if not cursor:
                return
            seen.add(cursor)
            params = {**params, request_cursor: cursor}
    raise ScanError(f"{url}: page limit reached before the end of the feed")


def more_kalshi(pages, now, window=SCAN_WINDOW):
    params = {
        "limit": 1000 if window > SCAN_WINDOW else 200, "mve_filter": "exclude",
        "min_close_ts": int(now.timestamp()),
        "max_close_ts": int((now + window).timestamp()),
    }
    rows = market_rows(f"{KALSHI_URL}/markets", params, "cursor", "cursor", pages)
    return normalize_markets(rows, "kalshi", now, window)


def more_poly(pages, now, window=SCAN_WINDOW):
    params = {
        "limit": 500 if window > SCAN_WINDOW else 100, "closed": "false",
        "end_date_min": now.isoformat(),
        "end_date_max": (now + window).isoformat(),
    }
    rows = market_rows(f"{GAMMA_URL}/markets/keyset", params, "next_cursor", "after_cursor", pages)
    return normalize_markets(rows, "polymarket", now, window)


def poly_us_market_rows(params, pages):
    limit = 500
    seen = set()
    with requests.Session() as session:
        offset = 0
        for _ in range(pages):
            payload, _ = fetch_json(f"{POLY_US_URL}/v1/markets", {**params, "limit": limit, "offset": offset},
                                    get=session.get)
            rows = payload.get("markets") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ScanError("Polymarket US returned an invalid market page")
            if not rows:
                return
            slugs = [row.get("slug") if isinstance(row, dict) else None for row in rows]
            ids = {slug for slug in slugs if isinstance(slug, str)}
            if ids and not ids - seen:
                raise ScanError("Polymarket US repeated a market page")
            for row, slug in zip(rows, slugs):
                if not isinstance(slug, str):
                    yield row
                elif slug not in seen:
                    seen.add(slug)
                    yield row
            offset += len(rows)
            if len(rows) < limit:
                return
    raise ScanError("Polymarket US page limit reached before the end of the feed")


def more_poly_us(pages, now, window=SCAN_WINDOW):
    params = {
        "active": "true", "closed": "false", "archived": "false",
        "endDateMin": now.isoformat(), "endDateMax": (now + window).isoformat(),
    }
    return normalize_markets(poly_us_market_rows(params, pages), POLY_US, now, window)


def lookup_markets(ids, venue, now):
    selected = []
    for batch in batched(sorted(ids), 100):
        if venue == "kalshi":
            rows = market_rows(f"{KALSHI_URL}/markets", {"tickers": ",".join(batch)}, "cursor", "cursor", 2)
        elif venue == POLY_US:
            rows = poly_us_market_rows({"slug": list(batch), "active": "true", "closed": "false"}, 2)
        else:
            params = {"condition_ids": list(batch), "closed": "false", "limit": 100}
            rows = market_rows(f"{GAMMA_URL}/markets/keyset", params, "next_cursor", "after_cursor", 2)
        selected.extend(market for market in normalize_markets(rows, venue, now, MAX_DISCOVERY_WINDOW) if market["id"] in ids)
    return selected
