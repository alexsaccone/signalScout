import argparse
import json
from pathlib import Path

import pandas as pd

if __package__:
    from .searcher import arbitrage_analysis, filter_kalshi_events, filter_polymarket_events, sentiment_analysis
else:
    from searcher import arbitrage_analysis, filter_kalshi_events, filter_polymarket_events, sentiment_analysis


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan Kalshi and Polymarket for candidate opportunities.")
    parser.add_argument("--fixture", type=Path, help="Replay pre-scored candidates from a local JSON file.")
    parser.add_argument("--output", type=Path, default=Path("opportunities.csv"))
    args = parser.parse_args(argv)

    if args.fixture:
        with args.fixture.open(encoding="utf-8") as fixture:
            candidates = pd.DataFrame(json.load(fixture))
    else:
        candidates = sentiment_analysis(filter_kalshi_events(), filter_polymarket_events())

    result = arbitrage_analysis(candidates)
    result.to_csv(args.output, index=False)


if __name__ == "__main__":
    main()
