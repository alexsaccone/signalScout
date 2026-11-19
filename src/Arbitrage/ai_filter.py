import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

if __package__:
    from .api import normalize_market, utc_timestamp
    from .searcher import OUTPUT_FIELDS, arbitrage_analysis, filter_kalshi_events, filter_polymarket_events, review_candidates, verified_pairs
else:
    from api import normalize_market, utc_timestamp
    from searcher import OUTPUT_FIELDS, arbitrage_analysis, filter_kalshi_events, filter_polymarket_events, review_candidates, verified_pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan reviewed Kalshi and Polymarket pairs.")
    parser.add_argument("--fixture", type=Path, help="Replay local market responses and reviews.")
    parser.add_argument("--reviewed-pairs", type=Path, help="JSON array of reviewed contract pairs.")
    parser.add_argument("--review-candidates", type=Path, help="Write similarly titled pairs for review.")
    parser.add_argument("--output", type=Path, default=Path("opportunities.csv"))
    args = parser.parse_args(argv)

    if args.fixture:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        kalshi, poly = (
            [market for row in fixture[venue] if (market := normalize_market(row, venue, now)) is not None]
            for venue in ("kalshi", "polymarket")
        )
        reviews = fixture["reviewed_pairs"]
    else:
        now = datetime.now(timezone.utc)
        kalshi, poly = filter_kalshi_events(now), filter_polymarket_events(now)
        reviews = []

    if args.reviewed_pairs:
        reviews = json.loads(args.reviewed_pairs.read_text(encoding="utf-8"))
    if args.review_candidates:
        if args.review_candidates.resolve() == args.output.resolve():
            parser.error("--review-candidates and --output must be different paths")
        candidates = review_candidates(kalshi, poly)
        args.review_candidates.write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")

    result = arbitrage_analysis(verified_pairs(kalshi, poly, reviews), now)
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(result)


if __name__ == "__main__":
    main()
