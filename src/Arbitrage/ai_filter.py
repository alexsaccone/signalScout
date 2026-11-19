import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode

if __package__:
    from .api import ScanError, normalize_markets, utc_timestamp
    from .pricing import OUTPUT_FIELDS, price_pairs
    from .searcher import filter_kalshi_events, filter_polymarket_events, refresh_reviewed_pairs, review_candidates, verified_pairs
else:
    from api import ScanError, normalize_markets, utc_timestamp
    from pricing import OUTPUT_FIELDS, price_pairs
    from searcher import filter_kalshi_events, filter_polymarket_events, refresh_reviewed_pairs, review_candidates, verified_pairs


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
        if args.review_candidates:
            window = timedelta(hours=args.hours)
            kalshi, poly = filter_kalshi_events(now, window), filter_polymarket_events(now, window)
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

    if args.review_candidates:
        candidates = review_candidates(kalshi, poly)
        atomic_write(args.review_candidates, lambda output: json.dump(candidates, output, indent=2))
        print(f"Wrote {len(candidates)} review candidates to {args.review_candidates}")
    if publish:
        write_snapshot(args.output, result)
        source = "fixture" if args.fixture else "live"
        print(f"Wrote {len(result)} opportunities to {args.output} ({source} data)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan reviewed Kalshi and Polymarket pairs.")
    parser.add_argument("--fixture", type=Path, help="Replay local market responses and reviews.")
    parser.add_argument("--reviewed-pairs", type=Path, help="JSON array of reviewed contract pairs.")
    parser.add_argument("--review-candidates", type=Path, help="Write similarly titled pairs for review.")
    parser.add_argument("--hours", type=int, default=24, help="Hours ahead to search for candidates (default: 24).")
    parser.add_argument("--output", type=Path,
                        help="CSV destination (default: opportunities.csv or opportunities.example.csv with --fixture).")
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = Path("opportunities.example.csv" if args.fixture else "opportunities.csv")

    if not (args.fixture or args.reviewed_pairs or args.review_candidates):
        parser.error("provide --reviewed-pairs, --review-candidates, or --fixture")
    if not 1 <= args.hours <= 720:
        parser.error("--hours must be between 1 and 720")
    inputs = {path.resolve() for path in (args.fixture, args.reviewed_pairs) if path}
    outputs = [path.resolve() for path in (args.output, args.review_candidates) if path]
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
