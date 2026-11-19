import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from src.Arbitrage.dashboard import main, upcoming_odds

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
GAME = {
    "sportsMarketType": "moneyline", "closed": False, "active": True, "acceptingOrders": True,
    "question": "Falcons vs. Foxes", "gameStartTime": "2026-11-20 02:00:00+00",
    "slug": "hockey-fal-fox", "outcomes": '["Falcons", "Foxes"]', "outcomePrices": '["0.60", "0.40"]',
}


class DashboardTest(unittest.TestCase):
    def test_odds_are_for_upcoming_moneyline_games_with_named_outcomes(self):
        games = upcoming_odds([
            dict(GAME, closed=True),
            dict(GAME, gameStartTime="2026-11-18T23:00:00Z"),
            dict(GAME, outcomes='["Yes", "No"]'),
            dict(GAME, outcomePrices='["NaN", "0.1"]'),
            GAME, GAME,
        ], NOW)
        game, = games
        self.assertEqual(game["outcomes"][0], {"name": "Falcons", "probability": 0.6})
        self.assertEqual(game["starts_at"], "2026-11-20T02:00:00+00:00")

    def test_fixture_snapshot_contains_odds_and_a_reviewed_estimate(self):
        fixture = Path(__file__).parent / "fixtures" / "scan.json"
        with TemporaryDirectory() as directory, mock.patch(
            "requests.sessions.Session.request", side_effect=AssertionError("Unexpected HTTP")
        ):
            output = Path(directory) / "snapshot.json"
            self.assertEqual(main(["--fixture", str(fixture), "--output", str(output)]), 0)
            snapshot = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["source"], "fixture")
        self.assertEqual(len(snapshot["odds"]), 3)
        opportunity, = snapshot["opportunities"]
        self.assertEqual(opportunity["estimated_net_profit"], "0.73000")
