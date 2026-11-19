from datetime import datetime, timezone
import unittest
from unittest import mock

from src.Arbitrage.api import more_kalshi, more_poly, normalize_market


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
KALSHI = {
    "status": "active", "market_type": "binary", "ticker": "K-EXAMPLE",
    "event_ticker": "K-EVENT", "title": "Will Example A win?",
    "yes_ask_dollars": "0.4300", "no_ask_dollars": "0.5800",
    "yes_sub_title": "Example A", "close_time": "2026-11-20T19:00:00Z",
}
POLY = {
    "active": True, "closed": False, "acceptingOrders": True,
    "conditionId": "P-EXAMPLE", "question": "Will Example A win?",
    "outcomes": '["No", "Yes"]', "clobTokenIds": '["10", "20"]',
    "outcomePrices": '["0.58", "0.43"]',
    "endDate": "2026-11-20T14:00:00-05:00", "endDateIso": "2026-11-20",
}


class IngestionTest(unittest.TestCase):
    def test_current_payloads_use_utc_and_current_price_fields(self):
        kalshi = normalize_market(KALSHI, "kalshi", NOW)
        poly = normalize_market(POLY, "polymarket", NOW)
        self.assertEqual(kalshi["close_time"], poly["close_time"])
        self.assertEqual(kalshi["close_time"].hour, 19)
        self.assertEqual(kalshi["id"], "K-EXAMPLE")
        self.assertEqual(poly["tokens"], {"yes": "20", "no": "10"})

    def test_ignores_non_tradable_or_out_of_window_markets(self):
        for payload, venue in (
            (dict(KALSHI, status="closed"), "kalshi"),
            (dict(KALSHI, close_time="2026-11-18T10:30:00Z"), "kalshi"),
            (dict(POLY, acceptingOrders=False), "polymarket"),
            (dict(POLY, endDate="2027-01-02T00:00:00Z"), "polymarket"),
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(normalize_market(payload, venue, NOW))

    def test_kalshi_skips_malformed_row_and_keeps_other_results(self):
        with mock.patch("src.Arbitrage.api.requests.get") as get, self.assertLogs(level="WARNING"):
            get.return_value.json.return_value = {"markets": [{"bad": "record"}, KALSHI], "cursor": ""}
            self.assertEqual([market["id"] for market in more_kalshi(2, NOW)], ["K-EXAMPLE"])
        self.assertEqual(get.call_args.kwargs["params"]["status"], "open")

    def test_polymarket_requests_the_next_cursor(self):
        with mock.patch("src.Arbitrage.api.requests.get") as get:
            requests_made = []
            get.side_effect = lambda url, params, timeout: requests_made.append(dict(params)) or mock.Mock(
                json=mock.Mock(side_effect=[{"markets": [POLY], "next_cursor": "next"}] if len(requests_made) == 1
                                          else [{"markets": []}])
            )
            self.assertEqual(len(more_poly(2, NOW)), 1)
        self.assertEqual(requests_made[1]["after_cursor"], "next")
