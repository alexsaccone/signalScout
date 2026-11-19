from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from itertools import batched
import json
import logging
from time import sleep

import requests

KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2"
GAMMA_URL = "https://gamma-api.polymarket.com"
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
        "limit": 200, "mve_filter": "exclude",
        "min_close_ts": int(now.timestamp()),
        "max_close_ts": int((now + window).timestamp()),
    }
    rows = market_rows(f"{KALSHI_URL}/markets", params, "cursor", "cursor", pages)
    return normalize_markets(rows, "kalshi", now, window)


def more_poly(pages, now, window=SCAN_WINDOW):
    params = {
        "limit": 100, "closed": "false",
        "end_date_min": now.isoformat(),
        "end_date_max": (now + window).isoformat(),
    }
    rows = market_rows(f"{GAMMA_URL}/markets/keyset", params, "next_cursor", "after_cursor", pages)
    return normalize_markets(rows, "polymarket", now, window)


def lookup_markets(ids, venue, now):
    selected = []
    for batch in batched(sorted(ids), 100):
        if venue == "kalshi":
            rows = market_rows(f"{KALSHI_URL}/markets", {"tickers": ",".join(batch)}, "cursor", "cursor", 2)
        else:
            params = {"condition_ids": list(batch), "closed": "false", "limit": 100}
            rows = market_rows(f"{GAMMA_URL}/markets/keyset", params, "next_cursor", "after_cursor", 2)
        selected.extend(market for market in normalize_markets(rows, venue, now) if market["id"] in ids)
    return selected
