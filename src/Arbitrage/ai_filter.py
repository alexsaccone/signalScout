import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode

if __package__:
    from .api import MAX_DISCOVERY_DAYS, ScanError, normalize_markets, utc_timestamp
    from .pricing import OUTPUT_FIELDS, price_pairs
    from .settlement_verification import assessment_report
    from .searcher import filter_kalshi_events, filter_polymarket_events, filter_polymarket_us_events, refresh_reviewed_pairs, review_candidates, review_leads, verified_pairs
else:
    from api import MAX_DISCOVERY_DAYS, ScanError, normalize_markets, utc_timestamp
    from pricing import OUTPUT_FIELDS, price_pairs
    from settlement_verification import assessment_report
    from searcher import filter_kalshi_events, filter_polymarket_events, filter_polymarket_us_events, refresh_reviewed_pairs, review_candidates, review_leads, verified_pairs


def fixture_quotes(responses):
    def fetch(url, params=None):
        key = f"{url}?{urlencode(params)}" if params else url
        response = responses[key]
        return response["body"], response.get("headers", {})
    return fetch


def atomic_write(path, write):
    pending = None
    try:
        with NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as output:
            pending = Path(output.name)
            write(output)
            output.flush()
            os.fsync(output.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def write_snapshot(path, opportunities):
    def write(output):
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(opportunities)
    atomic_write(path, write)


def scan(args):
    if args.fixture:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        kalshi_rows, poly_rows = fixture["kalshi"], fixture["polymarket"]
        if not isinstance(kalshi_rows, list) or not isinstance(poly_rows, list):
            raise ScanError("Fixture market responses must be arrays")
        kalshi = normalize_markets(kalshi_rows, "kalshi", now)
        poly = normalize_markets(poly_rows, "polymarket", now)
        reviews = fixture["reviewed_pairs"]
    else:
        now = datetime.now(timezone.utc)
        if args.review_candidates or args.review_leads or args.settlement_assessment:
            window = timedelta(hours=args.hours)
            feeds = (filter_kalshi_events, filter_polymarket_events, filter_polymarket_us_events)
            with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
                pending = [pool.submit(fetch, now, window) for fetch in feeds]
                kalshi, poly, us = [scan.result() for scan in pending]
            print(f"Discovered {len(kalshi)} Kalshi, {len(poly)} Polymarket International, "
                  f"and {len(us)} Polymarket US markets")
            poly += us
        reviews = []

    if args.reviewed_pairs:
        reviews = json.loads(args.reviewed_pairs.read_text(encoding="utf-8"))
    if not isinstance(reviews, list):
        raise ScanError("Reviewed pairs must be a JSON array")

    publish = args.fixture or args.reviewed_pairs
    if publish:
        if args.fixture:
            pairs = verified_pairs(kalshi, poly, reviews)
            result = price_pairs(pairs, lambda: now, fixture_quotes(fixture["quotes"]))
        else:
            pairs = refresh_reviewed_pairs(reviews, now)
            result = price_pairs(pairs, lambda: datetime.now(timezone.utc))

    candidates = review_candidates(kalshi, poly) if args.review_candidates or args.settlement_assessment else []
    lead_counts = {}
    leads = review_leads(kalshi, poly, lead_counts) if args.review_leads or args.settlement_assessment else []
    if args.review_candidates:
        atomic_write(args.review_candidates, lambda output: json.dump(candidates, output, indent=2))
        print(f"Wrote {len(candidates)} review candidates to {args.review_candidates}")
    if args.review_leads:
        report = {"status": "unverified", "generated_at": now.isoformat(), "leads": leads}
        atomic_write(args.review_leads, lambda output: json.dump(report, output, indent=2))
        print(f"Wrote {len(leads)} unverified review leads to {args.review_leads}")
    if args.settlement_assessment:
        assessment = assessment_report(kalshi, poly, candidates, leads)
        assessment["rule_text_discovery"] = lead_counts
        print(f"Rule-text search indexed {lead_counts['kalshi_indexed']} Kalshi and "
              f"{lead_counts['polymarket_indexed']} Polymarket markets with a usable dated condition. "
              f"It kept {lead_counts['exact_condition_leads']} exact-condition or statistic leads and "
              f"{lead_counts['fuzzy_leads']} additional fuzzy leads.")
        print(f"Assessed {assessment['candidate_pairs_assessed']} distinct candidates, including "
              f"{assessment['structured_event_candidates']} from weather and Fed event identities")
        atomic_write(args.settlement_assessment, lambda output: json.dump(assessment, output, indent=2))
        print(f"Settlement assessment: {len(assessment['verified'])} verified, "
              f"{len(assessment['cancellation_only'])} cancellation-only, "
              f"{len(assessment['different_rules'])} have different rules, "
              f"{len(assessment['manual_review'])} need manual review")
    if publish:
        write_snapshot(args.output, result)
        source = "fixture" if args.fixture else "live"
        print(f"Wrote {len(result)} opportunities to {args.output} ({source} data)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan reviewed Kalshi and Polymarket pairs.")
    parser.add_argument("--fixture", type=Path, help="Replay local market responses and reviews.")
    parser.add_argument("--reviewed-pairs", type=Path, help="JSON array of reviewed contract pairs.")
    parser.add_argument("--review-candidates", type=Path, help="Write pairs with matching published settlement terms for review.")
    parser.add_argument("--review-leads", type=Path, help="Write unverified same-event leads for manual settlement review.")
    parser.add_argument("--settlement-assessment", type=Path, help="Check full rulebooks and write an assessment.")
    parser.add_argument("--hours", type=int, default=24, help="Hours ahead to search for candidates (default: 24).")
    parser.add_argument("--output", type=Path,
                        help="CSV destination (default: opportunities.csv or opportunities.example.csv with --fixture).")
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = Path("opportunities.example.csv" if args.fixture else "opportunities.csv")

    if not (args.fixture or args.reviewed_pairs or args.review_candidates or args.review_leads or args.settlement_assessment):
        parser.error("provide --reviewed-pairs, --review-candidates, --review-leads, --settlement-assessment, or --fixture")
    if not 1 <= args.hours <= MAX_DISCOVERY_DAYS * 24:
        parser.error(f"--hours must be between 1 and {MAX_DISCOVERY_DAYS * 24}")
    if args.fixture and args.settlement_assessment:
        parser.error("--settlement-assessment requires live market rules")
    inputs = {path.resolve() for path in (args.fixture, args.reviewed_pairs) if path}
    outputs = [path.resolve() for path in (args.output, args.review_candidates, args.review_leads, args.settlement_assessment) if path]
    if inputs.intersection(outputs) or len(outputs) != len(set(outputs)):
        parser.error("input and output paths must be distinct")

    try:
        scan(args)
    except (ScanError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Scan failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
