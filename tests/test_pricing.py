from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest import mock

from src.Arbitrage.pricing import kalshi_fee_rate, opportunity, Quote


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
KALSHI = {"id": "K", "title": "Example", "close_time": NOW + timedelta(days=1)}
POLY = {"id": "P", "title": "Example", "tokens": {"no": "10"}, "close_time": NOW + timedelta(days=1)}


def quote(price, size="10", now=NOW, minimum="1"):
    return Quote(Decimal(price), Decimal(size), now, Decimal(minimum))


class PricingTest(unittest.TestCase):
    def price(self, left, right, k_rate="0", p_rate="0"):
        return opportunity(left, right, KALSHI, POLY, "yes", "no", Decimal(k_rate), Decimal(p_rate), NOW)

    def test_break_even_is_not_profitable(self):
        self.assertIsNone(self.price(quote(".03"), quote(".97")))

    def test_fees_overturn_a_small_gross_edge(self):
        self.assertIsNone(self.price(quote(".49"), quote(".49"), ".07", ".04"))

    def test_stale_missing_and_insufficient_quotes_are_skipped(self):
        right = quote(".40", minimum="5")
        for left in (
            None,
            quote(".40", now=NOW - timedelta(seconds=61)),
            quote(".40", now=NOW + timedelta(seconds=6)),
            quote(".40", size="4.99"),
            quote("0"),
        ):
            with self.subTest(left=left):
                self.assertIsNone(self.price(left, right))

    def test_event_fee_overrides_series_rate(self):
        fetch = mock.Mock(side_effect=[
            ({"event": {"series_ticker": "SERIES", "fee_multiplier_override": 2}}, {}),
            ({"series": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1}}, {}),
        ])
        self.assertEqual(kalshi_fee_rate({"event_id": "EVENT"}, fetch), Decimal(".14"))
