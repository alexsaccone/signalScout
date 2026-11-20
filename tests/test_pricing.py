from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest import mock

from src.Arbitrage.api import POLY_US, POLY_US_URL
from src.Arbitrage.pricing import kalshi_fee_rate, opportunity, price_pairs, Quote


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

    def test_us_price_uses_binary_book_and_fee_over_later_close(self):
        market = dict(POLY, venue=POLY_US, minimum_trade_qty="5", close_time=NOW + timedelta(days=100))
        fetch = mock.Mock(return_value=({"marketData": {
            "marketSlug": market["id"], "state": "MARKET_STATE_OPEN", "transactTime": NOW.isoformat(),
            "bids": [{"px": {"value": ".60", "currency": "USD"}, "qty": "10.5"}],
            "offers": [{"px": {"value": ".61", "currency": "USD"}, "qty": "7"}],
        }}, {}))
        with mock.patch("src.Arbitrage.pricing.kalshi_fee_rate", return_value=Decimal("0")), mock.patch(
            "src.Arbitrage.pricing.kalshi_quotes", return_value={"yes": quote(".40")}
        ):
            row, = price_pairs([(KALSHI, market)], lambda: NOW, fetch)
        fetch.assert_called_once_with(f"{POLY_US_URL}/v1/markets/{market['id']}/book")
        self.assertEqual(row["polymarket_side"], "no")
        self.assertEqual(row["polymarket_ask"], Decimal(".40"))
        self.assertEqual(row["estimated_fees"], Decimal(".23"))
        self.assertEqual(row["daily_roi_pct"], row["net_return_pct"] / 100)
        self.assertEqual(row["capital_until"], market["close_time"].isoformat())
