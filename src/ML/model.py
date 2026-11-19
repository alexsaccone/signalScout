import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
import json
from math import log, log1p
from pathlib import Path
from statistics import fmean
import sys

DATASET = Path(__file__).resolve().parents[2] / "data" / "setka_june_2022.csv"
INITIAL_RATING = 1500
UPDATE_WEIGHT = 24


@dataclass(frozen=True)
class Match:
    day: date
    player_one: str
    player_two: str
    winner: int


def load_matches(path):
    matches = {}
    input_count = 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row_number, row in enumerate(csv.DictReader(source), start=2):
            input_count += 1
            try:
                day = datetime.strptime(row["Date"], "%m/%d/%Y").date()
                starts = datetime.strptime(row["Time"].strip(), "%H:%M:%S").time()
                first, second = row["Player1"].strip(), row["Player2"].strip()
                winner = int(row["HomeWinner"])
                if not first or not second or winner not in (0, 1):
                    raise ValueError("invalid players or winner")
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid match record at CSV line {row_number}") from error
            if first == second:
                continue
            key = day, starts, *sorted((first, second))
            winner_name = first if winner else second
            if key in matches and matches[key][1] != winner_name:
                raise ValueError(f"Conflicting match result at CSV line {row_number}")
            matches.setdefault(key, (Match(day, first, second, winner), winner_name))
    return [match for match, _ in matches.values()], input_count - len(matches)


def evaluate(matches, test_start=None):
    dates = sorted({match.day for match in matches})
    if len(dates) < 2:
        raise ValueError("At least two match dates are required")
    if test_start is None:
        test_start = dates[int(0.8 * len(dates))]
    if not dates[0] < test_start <= dates[-1]:
        raise ValueError("Test start must leave at least one earlier day and one test day")

    ratings = defaultdict(lambda: INITIAL_RATING)
    holdout = []
    train_games = 0
    for day, day_matches in groupby(sorted(matches, key=lambda match: match.day), key=lambda match: match.day):
        changes = defaultdict(float)
        for match in day_matches:
            difference = ratings[match.player_two] - ratings[match.player_one]
            probability = 1 / (1 + 10 ** (difference / 400))
            if day >= test_start:
                holdout.append((probability, match.winner))
            else:
                train_games += 1
            change = UPDATE_WEIGHT * (match.winner - probability)
            changes[match.player_one] += change
            changes[match.player_two] -= change
        # The CSV has start times but no completion times. Same-day results cannot affect predictions.
        for player, change in changes.items():
            ratings[player] += change

    return {
        "first_date": dates[0].isoformat(), "test_start": test_start.isoformat(),
        "last_date": dates[-1].isoformat(), "train_games": train_games, "test_games": len(holdout),
        "brier_score": fmean((probability - outcome) ** 2 for probability, outcome in holdout),
        "log_loss": fmean(loss(probability, outcome) for probability, outcome in holdout),
        "accuracy": fmean((probability > 0.5) == bool(outcome) if probability != 0.5 else 0.5
                          for probability, outcome in holdout),
        "constant_50_percent": {"brier_score": 0.25, "log_loss": log(2), "accuracy": 0.5},
        "calibration": calibration(holdout),
    }


def loss(probability, outcome):
    clipped = min(1 - 1e-15, max(1e-15, probability))
    return -log(clipped) if outcome else -log1p(-clipped)


def calibration(predictions):
    bins = [[] for _ in range(5)]
    for probability, outcome in predictions:
        bins[min(int(probability * 5), 4)].append((probability, outcome))
    return [
        {
            "range": [index / 5, (index + 1) / 5], "matches": len(entries),
            "mean_predicted": fmean(probability for probability, _ in entries),
            "observed_win_rate": fmean(outcome for _, outcome in entries),
        }
        for index, entries in enumerate(bins) if entries
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate a pregame Setka player-rating baseline.")
    parser.add_argument("--data", type=Path, default=DATASET)
    parser.add_argument("--test-start", type=date.fromisoformat, help="First test date (YYYY-MM-DD).")
    args = parser.parse_args(argv)
    try:
        matches, excluded = load_matches(args.data)
        report = evaluate(matches, args.test_start)
        report["excluded_records"] = excluded
    except (ValueError, OSError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
