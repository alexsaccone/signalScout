import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

from .ai_filter import atomic_write, fixture_quotes
from .api import binary_values, fetch_json, GAMMA_URL, market_rows, normalize_markets, POLY_US, POLY_US_URL, PUBLIC_SLUG, ScanError, utc_timestamp
from .pricing import price_pairs
from .searcher import refresh_reviewed_pairs, verified_pairs
from .settlement_ai_review import VERDICTS
from .settlement_documents import OFFICIAL_RULEBOOK
from .settlement_verification import current_assessment_rows

ODDS_WINDOW = timedelta(days=3)


def kalshi_event_url(ticker):
    if isinstance(ticker, str) and re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9.]+)+", ticker):
        ticker = ticker.lower()
        return f"https://kalshi.com/markets/{ticker.split('-', 1)[0]}/{ticker}"


def polymarket_us_event_urls(markets, fetch=fetch_json):
    by_question = defaultdict(set)
    for symbol, question in markets.items():
        if isinstance(question, str) and question.strip():
            by_question[question.strip()].add(symbol)

    def links(events, symbols):
        urls = {}
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            slug = event.get("slug")
            markets = event.get("markets")
            if isinstance(slug, str) and PUBLIC_SLUG.fullmatch(slug) and isinstance(markets, list):
                for market in markets:
                    symbol = market.get("slug") if isinstance(market, dict) else None
                    if isinstance(symbol, str) and symbol in symbols:
                        urls[symbol] = f"https://polymarket.us/event/{slug}"
        return urls

    def search(item):
        question, symbols = item
        try:
            payload, _ = fetch(f"{POLY_US_URL}/v1/search", {"query": question, "limit": 10})
        except ScanError:
            return {}
        return links(payload.get("events"), symbols) if isinstance(payload, dict) else {}

    def lookup(item):
        slug, symbols = item
        try:
            payload, _ = fetch(f"{POLY_US_URL}/v1/events/slug/{slug}")
        except ScanError:
            return {}
        return links([payload.get("event")], symbols) if isinstance(payload, dict) else {}

    urls = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(search, by_question.items()):
            urls.update(result)
        by_hint = defaultdict(set)
        for symbol in markets.keys() - urls.keys():
            slug = symbol.partition("-")[2].rpartition("-")[0]
            if PUBLIC_SLUG.fullmatch(slug):
                by_hint[slug].add(symbol)
        for result in pool.map(lookup, by_hint.items()):
            urls.update(result)
    return urls


def add_event_links(rows, markets):
    unresolved = {}
    for row in rows:
        kalshi, polymarket = markets[(row["kalshi_id"], row["polymarket_id"])]
        row["kalshi_url"] = kalshi_event_url(kalshi.get("event_id"))
        row["polymarket_url"] = polymarket.get("url")
        if not row["polymarket_url"] and polymarket.get("venue") == POLY_US:
            unresolved[polymarket["id"]] = polymarket.get("event_title")
    if unresolved:
        urls = polymarket_us_event_urls(unresolved)
        for row in rows:
            if not row["polymarket_url"]:
                row["polymarket_url"] = urls.get(row["polymarket_id"])


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
    verified = list(current_assessment_rows(report.get("verified", []), now))
    differences = {
        (row["pair"]["kalshi"]["id"], row["pair"]["polymarket"]["id"]): row
        for row in current_assessment_rows(report.get("cancellation_only", []), now)
    }
    conflicts = report.get("different_rules", [])
    blocked = [row["pair"] for row in conflicts + report.get("cancellation_only", []) if row["pair"] in reviews]
    reviews = [review for review in reviews if review not in blocked]
    shared_rules = {ids: row for ids, row in differences.items() if "payout_scenarios" in row}
    shared_rules.update({
        (row["pair"]["kalshi"]["id"], row["pair"]["polymarket"]["id"]): row
        for row in current_assessment_rows([row for row in conflicts if "payout_scenarios" in row], now)
    })
    checked = refresh_reviewed_pairs(reviews + [row["pair"] for row in verified] +
                                     [row["pair"] for row in differences.values()] +
                                     [row["pair"] for row in shared_rules.values()], now)
    priceable, cancellation, shared = [], [], []
    for left, right in checked:
        ids = left["id"], right["id"]
        difference = differences.get(ids)
        if ids in shared_rules:
            shared.append((left, right, shared_rules[ids]))
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
        elif ids not in shared_rules:
            priceable.append((left, right))
    return priceable, cancellation, shared


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
            "event_id": row.get("event_id", left["id"]),
            "event_title": row.get("event_title", left["title"]),
            "kalshi_title": left["title"], "polymarket_title": right["title"],
            "polymarket_venue": right.get("venue", "polymarket"), "polymarket_url": right.get("url"),
            "kalshi_close": left["close_time"], "polymarket_close": right["close_time"],
            "closes_at": earliest, "capital_until": latest, "difference": row["difference"],
            "kalshi_rulebook": row["evidence"].get("kalshi_rulebook"),
            "polymarket_rulebook": row["evidence"].get("polymarket_rulebook"),
        })
    return sorted(results, key=lambda row: (row["capital_until"], row["kalshi_title"]))


def ai_review_rows(assessment, ai_report):
    if not isinstance(ai_report, dict) or not assessment.get("generated_at") or ai_report.get("assessment_at") != assessment["generated_at"]:
        return []
    suggestions = {
        (row["kalshi_id"], row["polymarket_id"]): row["review"]
        for row in ai_report.get("reviews", [])
        if row["status"] in {"reviewed", "cached"}
    }
    rows = []
    for row in assessment.get("manual_review", []):
        left, right = row["pair"]["kalshi"], row["pair"]["polymarket"]
        review = suggestions.get((left["id"], right["id"]))
        if not review or review.get("verdict") not in VERDICTS:
            continue
        earliest, latest = sorted((left["close_time"], right["close_time"]), key=utc_timestamp)
        result = {
            "kalshi_id": left["id"], "polymarket_id": right["id"],
            "kalshi_title": left["title"], "polymarket_title": right["title"],
            "polymarket_venue": right.get("venue", "polymarket"),
            "closes_at": earliest, "capital_until": latest,
            "verdict": review["verdict"], "summary": review["summary"], "quotes": review["quotes"],
        }
        for venue in ("kalshi", "polymarket"):
            key = f"{venue}_rulebook"
            url = row["evidence"].get(key)
            if isinstance(url, str) and OFFICIAL_RULEBOOK.fullmatch(url):
                result[key] = url
        rows.append(result)
    return sorted(rows, key=lambda row: utc_timestamp(row["closes_at"]))


def build_snapshot(reviews_path, fixture_path=None, assessment_path=None, ai_review_path=None):
    if fixture_path:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        kalshi = normalize_markets(fixture["kalshi"], "kalshi", now)
        polymarket = normalize_markets(fixture["polymarket"], "polymarket", now)
        pairs = list(verified_pairs(kalshi, polymarket, fixture["reviewed_pairs"]))
        opportunities = price_pairs(pairs, lambda: now, fixture_quotes(fixture["quotes"]))
        matches = matched_pair_rows(pairs)
        add_event_links(opportunities + matches, {(left["id"], right["id"]): (left, right) for left, right in pairs})
        return {"source": "fixture", "generated_at": now.isoformat(), "odds": upcoming_odds(fixture["odds"], now),
                "opportunities": opportunities, "matched_pairs": matches,
                "cancellation_only": [], "shared_events": [], "ai_reviews": []}

    now = datetime.now(timezone.utc)
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    if not isinstance(reviews, list):
        raise ScanError("Reviewed pairs must be a JSON array")
    games = live_games(now)
    report = json.loads(assessment_path.read_text(encoding="utf-8")) if assessment_path else {}
    ai_rows = []
    if ai_review_path:
        try:
            ai_rows = ai_review_rows(report, json.loads(ai_review_path.read_text(encoding="utf-8")))
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            print("The AI-review report could not be published.", file=sys.stderr)
    pairs, cancellation, shared = live_pairs(reviews, report, now)
    shared_rules = {(left["id"], right["id"]): row for left, right, row in shared}
    opportunities = price_pairs(
        pairs + [(left, right) for left, right, _ in shared],
        lambda: datetime.now(timezone.utc), shared_rules=shared_rules,
    )
    matches = matched_pair_rows(pairs)
    matched_ids = {(row["kalshi_id"], row["polymarket_id"]) for row in matches}
    ai_rows = [row for row in ai_rows if (row["kalshi_id"], row["polymarket_id"]) not in matched_ids]
    shared_rows = shared_event_rows(report)
    markets = {}
    for row in report.get("different_rules", []) + report.get("cancellation_only", []) + report.get("manual_review", []):
        left, right = row["pair"]["kalshi"], row["pair"]["polymarket"]
        markets[left["id"], right["id"]] = (
            {"event_id": row.get("kalshi_event_id")},
            dict(right, url=row.get("polymarket_event_url") or right.get("url"),
                 event_title=row.get("polymarket_event_query") or row.get("event_title")),
        )
    markets.update({(left["id"], right["id"]): (left, right) for left, right in pairs})
    add_event_links(opportunities + matches + cancellation + shared_rows + ai_rows, markets)
    return {"source": "live", "generated_at": datetime.now(timezone.utc).isoformat(),
            "odds": games, "opportunities": opportunities, "matched_pairs": matches,
            "cancellation_only": cancellation, "shared_events": shared_rows,
            "ai_reviews": ai_rows,
            "shared_pairs_price_checked": len(shared)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the SignalScout dashboard snapshot.")
    parser.add_argument("--reviewed-pairs", type=Path, default=Path("data/reviewed_pairs.json"))
    parser.add_argument("--settlement-assessment", type=Path, help="Full settlement assessment from the current run.")
    parser.add_argument("--ai-review", type=Path, help="Advisory review report from the same assessment.")
    parser.add_argument("--fixture", type=Path, help="Build a labeled offline demo snapshot.")
    parser.add_argument("--output", type=Path, default=Path("src/website/public/snapshot.json"))
    args = parser.parse_args(argv)
    try:
        snapshot = build_snapshot(args.reviewed_pairs, args.fixture, args.settlement_assessment, args.ai_review)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output, lambda output: json.dump(snapshot, output, default=str))
    except (ScanError, AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Dashboard refresh failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(snapshot['odds'])} games and {len(snapshot['opportunities'])} opportunities.")
    print(f"Pricing checked {len(snapshot['matched_pairs'])} verified pairs and "
          f"{snapshot.get('shared_pairs_price_checked', 0)} shared pairs with an established payout floor. "
          f"Published {len(snapshot['shared_events'])} shared pairs and {len(snapshot['ai_reviews'])} AI-reviewed pairs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
