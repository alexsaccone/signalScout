from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.Arbitrage.dashboard import live_pairs
from src.Arbitrage.searcher import market_terms, verified_pairs
from src.Arbitrage.settlement_documents import Rulebook, text_policy
from src.Arbitrage.settlement_verification import FAIR_PRICE_CANCELLATION, assessment_report

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
BOOK = "https://assets.kalshi.com/contract_terms/EXAMPLE.pdf"
OTHER_BOOK = "https://docs.polymarket.com/markets/OTHER.pdf"


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


def pdf(terms):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 11 Tf 60 700 Td ({terms}) Tj ET".encode("ascii"))
    page.replace_contents(content)
    output = BytesIO()
    writer.write(output)
    data = output.getvalue()
    return Rulebook(sha256(data).hexdigest(), text_policy(data))


class SettlementVerificationTest(unittest.TestCase):
    def assess(self, left, right):
        lead = {"kalshi": market_terms(left), "polymarket": market_terms(right)}
        return assessment_report([left], [right], [], [lead], NOW)

    @patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook("same"))
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

    @patch("src.Arbitrage.settlement_verification.load_rulebook", side_effect=lambda url: Rulebook(url))
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

    @patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook("same"))
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

            digest.return_value = Rulebook("changed")
            self.assertEqual(live_pairs([], report, NOW), ([], []))

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_equivalent_full_documents_with_different_content_hashes(self, _):
        left, right = contracts(rulebook=OTHER_BOOK)
        first = pdf('Use https://www.nba.com/stats as the official source. Otherwise, the market resolves to No.')
        second = pdf('The resolution source for this market is https://www.nba.com/stats. '
                     'Otherwise, this market will resolve to "No."')
        self.assertIsNotNone(first.policy)
        self.assertEqual(first.policy, second.policy)
        self.assertNotEqual(first.sha256, second.sha256)
        documents = {BOOK: first, OTHER_BOOK: second}
        with patch("src.Arbitrage.settlement_verification.load_rulebook", side_effect=documents.get):
            report = assessment_report([left], [right], [], [], NOW)
            row, = report["verified"]
            self.assertEqual(row["evidence"]["polymarket_sha256"], second.sha256)
            with patch("src.Arbitrage.dashboard.refresh_reviewed_pairs",
                       side_effect=lambda reviews, now: verified_pairs([left], [right], reviews)):
                self.assertEqual(live_pairs([], report, NOW)[0], [(left, right)])
                documents[OTHER_BOOK] = pdf('The resolution source for this market is https://www.example.com/stats. '
                                            'Otherwise, this market will resolve to "No."')
                self.assertEqual(live_pairs([], report, NOW), ([], []))
            report = self.assess(left, right)
            self.assertEqual(len(report["manual_review"]), 1)
            self.assertFalse(report["verified"])

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_versioned_kalshi_clause_proves_inline_polymarket_mismatch(self, _):
        left, right = contracts()
        left["secondary_rules"] = "Regulation play only."
        right["rules"] = right["rules"].split("\nGoverning contract terms:", 1)[0]
        digest = next(iter(FAIR_PRICE_CANCELLATION))
        with patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook(digest)):
            report = self.assess(left, right)
            row, = report["different_rules"]
            self.assertEqual(row["difference"]["polymarket_payout"], "No")
            self.assertFalse(report["cancellation_only"])
            with patch("src.Arbitrage.dashboard.refresh_reviewed_pairs",
                       side_effect=lambda reviews, now: verified_pairs([left], [right], reviews)):
                self.assertEqual(live_pairs([row["pair"]], report, NOW), ([], []))

        with patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook("changed")):
            report = self.assess(left, right)
            self.assertEqual(len(report["manual_review"]), 1)
            self.assertFalse(report["different_rules"])

    def test_pdf_does_not_normalize_conflicting_source_priority(self):
        first = "Use https://example.com/primary as the official source."
        second = "Use https://example.com/alternative as the official source."
        self.assertIsNone(pdf(f"{first} {second}").policy)

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_cancellation_only_in_independent_pdfs(self, _):
        left, right = contracts(rulebook=OTHER_BOOK)
        left["secondary_rules"] = left["secondary_rules"].replace(
            "If the game is canceled, this market will resolve to No.\n", "")
        right["rules"] = right["rules"].replace("If the game is cancelled, this market will resolve to No.\n", "")
        documents = {
            BOOK: pdf("If the game is canceled, this market will resolve to No."),
            OTHER_BOOK: pdf('If the game is cancelled, this market will resolve to "50-50."'),
        }
        with patch("src.Arbitrage.settlement_verification.load_rulebook", side_effect=documents.get):
            report = assessment_report([left], [right], [], [], NOW)
            row, = report["cancellation_only"]
            self.assertEqual((row["kalshi_cancellation"], row["polymarket_cancellation"]), ("no", "50-50"))
            self.assertFalse(report["verified"])
