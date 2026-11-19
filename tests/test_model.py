from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.ML.model import evaluate, load_matches, Match


DAY_ONE = date(2022, 6, 10)
DAY_TWO = date(2022, 6, 11)
DAY_THREE = date(2022, 6, 12)


class PregameRatingTest(unittest.TestCase):
    def test_reads_players_and_results_without_postgame_feature_columns(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "games.csv"
            source.write_text(
                "Date,Time,Player1,Player2,HomeWinner\n"
                "6/10/2022,1:05:00,One,Two,1\n"
                "6/10/2022,01:05:00,Two,One,0\n"
                "6/10/2022,1:20:00,One,One,1\n",
                encoding="utf-8",
            )
            self.assertEqual(load_matches(source), ([Match(DAY_ONE, "One", "Two", 1)], 2))

    def test_holdout_updates_use_previous_days_and_ignore_row_order(self):
        matches = [
            Match(DAY_THREE, "One", "Two", 1),
            Match(DAY_TWO, "One", "Two", 1),
            Match(DAY_ONE, "One", "Two", 1),
        ]
        summary = evaluate(matches, DAY_TWO)
        self.assertEqual(summary, evaluate(list(reversed(matches)), DAY_TWO))
        self.assertEqual(summary["test_games"], 2)
        self.assertEqual(summary["train_games"], 1)
        self.assertLess(summary["brier_score"], summary["constant_50_percent"]["brier_score"])

    def test_same_day_predictions_do_not_use_other_games_that_day(self):
        first = Match(DAY_ONE, "One", "Two", 1)
        stable = Match(DAY_TWO, "One", "Two", 1)
        results = [evaluate([first, Match(DAY_TWO, "One", "Two", winner), stable], DAY_TWO)
                   for winner in (0, 1)]
        self.assertEqual(results[0]["calibration"][0]["mean_predicted"],
                         results[1]["calibration"][0]["mean_predicted"])
        self.assertNotEqual(results[0]["calibration"][0]["observed_win_rate"],
                            results[1]["calibration"][0]["observed_win_rate"])
