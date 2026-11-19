from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from src.Arbitrage.dashboard import live_pairs
from src.Arbitrage.searcher import market_terms, verified_pairs
from src.Arbitrage.settlement_verification import assessment_report

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
BOOK = "https://assets.kalshi.com/contract_terms/EXAMPLE.pdf"
OTHER_BOOK = "https://assets.kalshi.com/contract_terms/OTHER.pdf"


def contracts(payout="No", rulebook=BOOK):
    fixture = "the Boston Celtics vs Miami Heat NBA game on November 20, 2026 at 7 PM ET"
    condition = f"Boston Celtics wins in {fixture}"
    source = "Use https://www.nba.com/stats as the official source."
    remaining = "Otherwise, this market will resolve to No."
    kalshi = {
        "id": "KXEXAMPLE-EVENT-CELTICS", "event_id": "KXEXAMPLE-EVENT", "title": "Boston Celtics wins",
        "subtitle": "", "rules": f"If {condition}, then the market resolves to Yes.",
        "secondary_rules": f"{source}\nIf the game is canceled, this market will resolve to No.\n{remaining}",
        "resolution": {}, "close_time": NOW + timedelta(days=2),
    }
    poly = {
        "id": "poly-1", "title": "Boston Celtics game winner", "subtitle": "",
        "rules": (f'This market will resolve to "Yes" if {condition}.\n'
                  f"{source}\nIf the game is cancelled, this market will resolve to {payout}.\n"
                  f"{remaining}\nGoverning contract terms: {rulebook}"),
        "secondary_rules": "", "resolution": "https://www.nba.com/stats",
        "close_time": NOW + timedelta(days=2), "tokens": {"yes": "10", "no": "11"},
    }
    return kalshi, poly


class SettlementVerificationTest(unittest.TestCase):
    def assess(self, left, right):
        lead = {"kalshi": market_terms(left), "polymarket": market_terms(right)}
        return assessment_report([left], [right], [], [lead], NOW)

    @patch("src.Arbitrage.settlement_verification.rulebook_digest", return_value="same")
    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_verifies_shared_governing_rules_and_classifies_cancellation(self, _, __):
        left, right = contracts()
        report = assessment_report([left], [right], [], [], NOW)
        self.assertEqual([row["pair"]["polymarket"]["id"] for row in report["verified"]], [right["id"]])
        self.assertEqual(report["manual_review"], [])
        _, right = contracts(payout="50-50")
        right["rules"] = right["rules"].replace("50-50.", '"50-50."').replace("\n", "\r\n")
        report = self.assess(left, right)
        difference, = report["cancellation_only"]
        self.assertEqual((difference["kalshi_cancellation"], difference["polymarket_cancellation"]), ("no", "50-50"))
        self.assertEqual(report["verified"], [])

    @patch("src.Arbitrage.settlement_verification.rulebook_digest", side_effect=lambda url: url)
    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_mismatch_missing_reference_and_quoted_references_stay_manual(self, _, __):
        left, different_book = contracts(rulebook=OTHER_BOOK)
        _, right = contracts(payout="50-50")
        different_source = dict(right, rules=right["rules"].replace("nba.com", "example.com"),
                                resolution="https://www.example.com/stats")
        different_payout = dict(right, rules=right["rules"].replace("Otherwise, this market will resolve to No.",
                                                                   "Otherwise, this market will resolve to Yes."))
        quoted_reference = dict(right, rules=right["rules"].replace("Governing contract terms:", '"\nGoverning contract terms:') + '\n"')
        for changed in (different_book, different_source, different_payout, quoted_reference):
            with self.subTest(rule=changed["rules"]):
                report = self.assess(left, changed)
                self.assertEqual(len(report["manual_review"]), 1)
                self.assertEqual(report["cancellation_only"], [])
                self.assertEqual(report["verified"], [])

    @patch("src.Arbitrage.settlement_verification.rulebook_digest", return_value="same")
    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_live_handoff_rechecks_documents_and_market_terms(self, _, digest):
        left, right = contracts()
        _, alternative = contracts(payout="50-50")
        alternative["id"] = "poly-2"
        report = assessment_report([left], [right, alternative], [], [], NOW)

        def refresh(reviews, now):
            return verified_pairs([left], [right, alternative], reviews)

        with patch("src.Arbitrage.dashboard.refresh_reviewed_pairs", side_effect=refresh):
            pairs, differences = live_pairs([], report, NOW)
            self.assertEqual([(k["id"], p["id"]) for k, p in pairs], [(left["id"], right["id"])])
            self.assertEqual([row["polymarket_id"] for row in differences], [alternative["id"]])

            right["rules"] += "\nA changed payout clause."
            pairs, differences = live_pairs([], report, NOW)
            self.assertEqual(pairs, [])
            self.assertEqual(len(differences), 1)

            digest.return_value = "changed"
            self.assertEqual(live_pairs([], report, NOW), ([], []))
