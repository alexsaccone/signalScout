from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import logging

import requests

KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2"
GAMMA_URL = "https://gamma-api.polymarket.com"
SCAN_WINDOW = timedelta(days=30)


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def binary_values(value):
    values = json.loads(value) if isinstance(value, str) else value
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Expected exactly two values")
    return values


def normalize_market(market, venue, now):
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
                "yes_ask": Decimal(market["yes_ask_dollars"]),
                "no_ask": Decimal(market["no_ask_dollars"]),
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
            prices = dict(zip(outcomes, map(Decimal, binary_values(market["outcomePrices"]))))
            normalized = {
                "id": market["conditionId"],
                "title": market["question"],
                "subtitle": "",
                "rules": market.get("description") or "",
                "secondary_rules": "",
                "resolution": market.get("resolutionSource") or "",
                "tokens": tokens,
                "yes_ask": prices["yes"],
                "no_ask": prices["no"],
                "close_time": close,
            }
        if not all(isinstance(normalized[key], str) and normalized[key].strip() for key in ("id", "title")):
            raise ValueError("Missing market ID or title")
        if not all(isinstance(normalized[key], str) for key in ("rules", "secondary_rules", "subtitle")):
            raise ValueError("Invalid market text")
        if not now < close <= now + SCAN_WINDOW:
            return None
        return normalized
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as error:
        logging.warning("Skipping malformed %s market (%s)", venue, type(error).__name__)
        return None


def more_kalshi(pages, now):
    markets = []
    params = {"limit": 200, "status": "open", "mve_filter": "exclude"}
    for _ in range(pages):
        response = requests.get(f"{KALSHI_URL}/markets", params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        markets.extend(payload["markets"])
        cursor = payload.get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return [market for payload in markets if (market := normalize_market(payload, "kalshi", now)) is not None]


def more_poly(pages, now):
    markets = []
    params = {
        "limit": 200, "closed": "false",
        "end_date_min": now.isoformat(),
        "end_date_max": (now + SCAN_WINDOW).isoformat(),
    }
    for _ in range(pages):
        response = requests.get(f"{GAMMA_URL}/markets/keyset", params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        markets.extend(payload["markets"])
        cursor = payload.get("next_cursor")
        if not cursor:
            break
        params["after_cursor"] = cursor
    return [market for payload in markets if (market := normalize_market(payload, "polymarket", now)) is not None]
