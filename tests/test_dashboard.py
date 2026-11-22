import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from src.Arbitrage.dashboard import ai_review_rows, build_snapshot, main, polymarket_us_event_urls, upcoming_odds

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
GAME = {
    "sportsMarketType": "moneyline", "closed": False, "active": True, "acceptingOrders": True,
    "question": "Falcons vs. Foxes", "gameStartTime": "2026-11-20 02:00:00+00",
    "slug": "hockey-fal-fox", "outcomes": '["Falcons", "Foxes"]', "outcomePrices": '["0.60", "0.40"]',
}


class DashboardTest(unittest.TestCase):
    def test_publishes_current_advisory_reviews_without_sending_them_to_pricing(self):
        stamp = NOW.isoformat()
        left = {"id": "KXTEST-EVENT-A", "title": "Kalshi contract", "close_time": "2026-12-01T20:00:00-05:00"}
        right = {"id": "test-event-a", "title": "Polymarket contract", "close_time": "2026-12-02T00:00:00Z",
                 "venue": "polymarket_us"}
        candidate = {"pair": {"kalshi": left, "polymarket": right}, "evidence": {},
                     "kalshi_event_id": "KXTEST-EVENT", "polymarket_event_url": "https://polymarket.us/event/test-event"}
        assessment = {"generated_at": stamp, "manual_review": [candidate]}
        suggestion = {"kalshi_id": left["id"], "polymarket_id": right["id"], "status": "cached",
                      "review_model": "gemini-3.6-flash",
                      "review": {"verdict": "likely_equivalent", "summary": "Both use the same criteria.", "quotes": []}}
        ai_report = {"model": "gemini-4-hydrogen", "assessment_at": stamp, "reviews": [suggestion]}
        legacy = dict(ai_report, reviews=[{key: value for key, value in suggestion.items() if key != "review_model"}])
        self.assertEqual(ai_review_rows(assessment, legacy)[0]["review_model"], "gemini-4-hydrogen")
        self.assertEqual(ai_review_rows(assessment, dict(ai_report, assessment_at="old")), [])
        self.assertEqual(ai_review_rows(assessment, dict(ai_report, reviews=[dict(suggestion, status="unsupported_review")])), [])
        with TemporaryDirectory() as folder, mock.patch("src.Arbitrage.dashboard.live_games", return_value=[]), mock.patch(
            "src.Arbitrage.dashboard.refresh_reviewed_pairs", return_value=[]
        ), mock.patch("src.Arbitrage.dashboard.price_pairs", return_value=[]) as price:
            reviews, evidence, ai = (Path(folder) / name for name in ("reviews.json", "assessment.json", "ai.json"))
            for path, value in ((reviews, []), (evidence, assessment), (ai, ai_report)):
                path.write_text(json.dumps(value), encoding="utf-8")
            snapshot = build_snapshot(reviews, assessment_path=evidence, ai_review_path=ai)
        row, = snapshot["ai_reviews"]
        self.assertEqual(row["closes_at"], right["close_time"])
        self.assertEqual(row["polymarket_url"], candidate["polymarket_event_url"])
        self.assertEqual(row["verdict"], "likely_equivalent")
        self.assertEqual(row["review_model"], "gemini-3.6-flash")
        self.assertEqual(snapshot["matched_pairs"], [])
        self.assertEqual(price.call_args.args[0], [])

    def test_polymarket_us_link_requires_exact_event_membership(self):
        def fetch(url, params=None):
            if params:
                return {"events": [
                    {"slug": "next-week", "markets": [{"slug": "rotc-next-week-gte80"}]},
                    {"slug": "this-week", "markets": [{"slug": "rotc-this-week-gte80"}]},
                ]}, {}
            return {"event": {"slug": "different-event", "markets": [{"slug": "rotc-other-gte80"}]}}, {}

        urls = polymarket_us_event_urls({
            "rotc-this-week-gte80": "Same question", "rotc-this-week-gte90": "Same question",
        }, fetch)
        self.assertEqual(urls, {"rotc-this-week-gte80": "https://polymarket.us/event/this-week"})

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
        self.assertEqual(opportunity["kalshi_url"], "https://kalshi.com/markets/k/k-event")

    def test_snapshot_lists_matched_pairs_when_pricing_finds_no_opportunity(self):
        fixture = Path(__file__).parent / "fixtures" / "scan.json"
        with mock.patch("src.Arbitrage.dashboard.price_pairs", return_value=[]):
            snapshot = build_snapshot(None, fixture)
        self.assertEqual(snapshot["opportunities"], [])
        pair, = snapshot["matched_pairs"]
        self.assertEqual((pair["kalshi_id"], pair["polymarket_id"]), ("K-EXAMPLE", "P-EXAMPLE"))
