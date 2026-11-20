import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

from .ai_filter import atomic_write, fixture_quotes
from .api import binary_values, GAMMA_URL, market_rows, normalize_markets, ScanError, utc_timestamp
from .pricing import price_pairs
from .searcher import refresh_reviewed_pairs, verified_pairs
from .settlement_verification import current_assessment_rows

ODDS_WINDOW = timedelta(days=3)


def upcoming_odds(rows, now):
    games = {}
    for row in rows:
        try:
            if (row["sportsMarketType"] != "moneyline" or row["closed"] is not False
                    or row["active"] is not True or row["acceptingOrders"] is not True):
                continue
            starts = utc_timestamp(row["gameStartTime"])
            if not now < starts <= now + ODDS_WINDOW:
                continue
            labels = binary_values(row["outcomes"])
            if (len(set(labels)) != 2 or any(not isinstance(label, str) or not label.strip() for label in labels)
                    or {label.casefold() for label in labels} == {"yes", "no"}):
                continue
            prices = [Decimal(str(price)) for price in binary_values(row["outcomePrices"])]
            if any(not price.is_finite() or not 0 < price < 1 for price in prices):
                continue
            event = (row.get("events") or [{}])[0]
            slug = event.get("slug") or row["slug"]
            if not re.fullmatch(r"[a-zA-Z0-9-]+", slug):
                continue
            title = row["question"].strip()
            if not title:
                continue
            games.setdefault(slug, {
                "id": slug, "title": title, "sport": slug.split("-")[0].upper(),
                "starts_at": starts.isoformat(), "url": f"https://polymarket.com/event/{slug}",
                "outcomes": [{"name": label, "probability": float(price)} for label, price in zip(labels, prices)],
            })
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return sorted(games.values(), key=lambda item: (item["starts_at"], item["title"]))


def live_games(now):
    params = {
        "limit": 100, "closed": "false", "sports_market_types": ["moneyline"],
        "end_date_min": now.isoformat(),
        "end_date_max": (now + ODDS_WINDOW).isoformat(),
    }
    rows = market_rows(f"{GAMMA_URL}/markets/keyset", params, "next_cursor", "after_cursor", 100)
    return upcoming_odds(rows, now)


def live_pairs(reviews, report, now):
    verified = list(current_assessment_rows(report.get("verified", [])))
    differences = {
        (row["pair"]["kalshi"]["id"], row["pair"]["polymarket"]["id"]): row
        for row in current_assessment_rows(report.get("cancellation_only", []))
    }
    rejected = [row for row in report.get("different_rules", []) if row["pair"] in reviews]
    blocked = [row["pair"] for row in current_assessment_rows(rejected)]
    reviews = [review for review in reviews if review not in blocked]
    checked = refresh_reviewed_pairs(reviews + [row["pair"] for row in verified] +
                                     [row["pair"] for row in differences.values()], now)
    priceable, cancellation = [], []
    for left, right in checked:
        difference = differences.get((left["id"], right["id"]))
        if difference:
            cancellation.append({
                "kalshi_id": left["id"], "polymarket_id": right["id"],
                "title": left["title"], "polymarket_title": right["title"],
                "polymarket_venue": right.get("venue", "polymarket"),
                "kalshi_cancellation": difference["kalshi_cancellation"],
                "polymarket_cancellation": difference["polymarket_cancellation"],
                "closes_at": min(left["close_time"], right["close_time"]).isoformat(),
                "rulebook": difference["evidence"]["kalshi_rulebook"],
            })
        else:
            priceable.append((left, right))
    return priceable, cancellation


def matched_pair_rows(pairs):
    rows = [{
        "kalshi_id": left["id"], "polymarket_id": right["id"],
        "kalshi_title": left["title"], "polymarket_title": right["title"],
        "polymarket_venue": right.get("venue", "polymarket"), "polymarket_url": right.get("url"),
        "closes_at": min(left["close_time"], right["close_time"]).isoformat(),
        "capital_until": max(left["close_time"], right["close_time"]).isoformat(),
    } for left, right in pairs]
    return sorted(rows, key=lambda row: (row["closes_at"], row["kalshi_title"], row["polymarket_id"]))


def shared_event_rows(report):
    results = []
    for row in report.get("different_rules", []):
        if not row.get("shared_event"):
            continue
        left, right = row["pair"]["kalshi"], row["pair"]["polymarket"]
        earliest, latest = sorted((left["close_time"], right["close_time"]))
        results.append({
            "kalshi_id": left["id"], "polymarket_id": right["id"],
            "kalshi_title": left["title"], "polymarket_title": right["title"],
            "polymarket_venue": right.get("venue", "polymarket"), "polymarket_url": right.get("url"),
            "kalshi_close": left["close_time"], "polymarket_close": right["close_time"],
            "closes_at": earliest, "capital_until": latest, "difference": row["difference"],
            "kalshi_rulebook": row["evidence"].get("kalshi_rulebook"),
            "polymarket_rulebook": row["evidence"].get("polymarket_rulebook"),
        })
    return sorted(results, key=lambda row: (row["capital_until"], row["kalshi_title"]))


def build_snapshot(reviews_path, fixture_path=None, assessment_path=None):
    if fixture_path:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        kalshi = normalize_markets(fixture["kalshi"], "kalshi", now)
        polymarket = normalize_markets(fixture["polymarket"], "polymarket", now)
        pairs = list(verified_pairs(kalshi, polymarket, fixture["reviewed_pairs"]))
        opportunities = price_pairs(pairs, lambda: now, fixture_quotes(fixture["quotes"]))
        return {"source": "fixture", "generated_at": now.isoformat(), "odds": upcoming_odds(fixture["odds"], now),
                "opportunities": opportunities, "matched_pairs": matched_pair_rows(pairs),
                "cancellation_only": [], "shared_events": []}

    now = datetime.now(timezone.utc)
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    if not isinstance(reviews, list):
        raise ScanError("Reviewed pairs must be a JSON array")
    games = live_games(now)
    report = json.loads(assessment_path.read_text(encoding="utf-8")) if assessment_path else {}
    pairs, cancellation = live_pairs(reviews, report, now)
    opportunities = price_pairs(pairs, lambda: datetime.now(timezone.utc))
    return {"source": "live", "generated_at": datetime.now(timezone.utc).isoformat(),
            "odds": games, "opportunities": opportunities, "matched_pairs": matched_pair_rows(pairs),
            "cancellation_only": cancellation, "shared_events": shared_event_rows(report)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the SignalScout dashboard snapshot.")
    parser.add_argument("--reviewed-pairs", type=Path, default=Path("data/reviewed_pairs.json"))
    parser.add_argument("--settlement-assessment", type=Path, help="Full settlement assessment from the current run.")
    parser.add_argument("--fixture", type=Path, help="Build a labeled offline demo snapshot.")
    parser.add_argument("--output", type=Path, default=Path("src/website/public/snapshot.json"))
    args = parser.parse_args(argv)
    try:
        snapshot = build_snapshot(args.reviewed_pairs, args.fixture, args.settlement_assessment)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output, lambda output: json.dump(snapshot, output, default=str))
    except (ScanError, AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Dashboard refresh failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(snapshot['odds'])} games and {len(snapshot['opportunities'])} opportunities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
