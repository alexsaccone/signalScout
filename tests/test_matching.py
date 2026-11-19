from pathlib import Path
import json
import unittest

from src.Arbitrage.api import normalize_market, utc_timestamp
from src.Arbitrage.searcher import review_candidates, verified_pairs


class MatchingTest(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "scan.json").read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        self.kalshi = normalize_market(fixture["kalshi"][0], "kalshi", now)
        self.poly = normalize_market(fixture["polymarket"][0], "polymarket", now)
        self.reviews = fixture["reviewed_pairs"]

    def test_reviewed_pair_keeps_canonical_ids_and_outcomes(self):
        pair, = verified_pairs([self.kalshi], [self.poly], self.reviews * 2)
        self.assertEqual((pair[0]["id"], pair[1]["id"]), ("K-EXAMPLE", "P-EXAMPLE"))
        self.assertEqual(pair[1]["tokens"], {"yes": "20", "no": "10"})

    def test_similar_titles_are_only_suggestions(self):
        self.assertEqual(review_candidates([self.kalshi], [self.poly]), self.reviews)
        self.assertEqual(list(verified_pairs([self.kalshi], [self.poly], [])), [])

    def test_reworded_titles_are_suggested_without_approving_them(self):
        kalshi = dict(self.kalshi, title="Boston Celtics at Miami Heat Winner")
        poly = dict(self.poly, title="Miami Heat vs. Boston Celtics Moneyline")
        other = dict(self.poly, id="unrelated", title="Miami Dolphins vs. Buffalo Bills")
        candidate, = review_candidates([kalshi], [other, poly])
        self.assertEqual(candidate["polymarket"]["title"], poly["title"])
        self.assertEqual(list(verified_pairs([kalshi], [poly], [])), [])

    def test_market_terms_change_invalidates_the_review(self):
        for changed in (
            dict(self.poly, title="Will Example A win Game 2?"),
            dict(self.poly, rules="Settle only if Example A wins by 2."),
            dict(self.poly, tokens={"no": "20", "yes": "10"}),
            dict(self.poly, resolution="Another results source"),
        ):
            with self.subTest(changed=changed):
                self.assertEqual(list(verified_pairs([self.kalshi], [changed], self.reviews)), [])
