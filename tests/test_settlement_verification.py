from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.Arbitrage.api import GAMMA_URL, POLY_US
from src.Arbitrage.dashboard import live_pairs, shared_event_rows
from src.Arbitrage.searcher import market_terms, review_candidates, review_leads, verified_pairs
from src.Arbitrage.settlement_documents import Rulebook, rule_policy, text_policy
from src.Arbitrage.settlement_verification import FAIR_PRICE_CANCELLATION, RATING_BOOKS, assessment_report

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
BOOK = "https://assets.kalshi.com/contract_terms/EXAMPLE.pdf"
OTHER_BOOK = "https://docs.polymarket.com/markets/OTHER.pdf"
ROTC_BOOK = "https://www.polymarketexchange.com/files/products/PMUS%20-%20ROTC%20-%20%282026.09.10%29.pdf"


def rotc_catalog():
    return {"ROTC": {"versions": {"2026-09-10": {"effective": "2026-09-14", "rule": "40.2"}}}}


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

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_uses_unlinked_us_filing_and_invalidates_if_a_later_amendment_takes_effect(self, _):
        left, right = contracts()
        right.update(id="rotc-example", venue=POLY_US, listed_at="2026-10-01T00:00:00Z",
                     rules=right["rules"].split("\nGoverning contract terms:", 1)[0].replace(
                         "Use https://www.nba.com/stats as the official source.",
                         "Outcome sourced from NBA (https://www.nba.com/stats).",
                     ))
        catalog = rotc_catalog()
        with patch("src.Arbitrage.settlement_verification.load_filing_catalog", return_value=catalog), patch(
            "src.Arbitrage.settlement_verification.load_rulebook",
            side_effect={BOOK: Rulebook("same"), ROTC_BOOK: Rulebook("same")}.get,
        ), patch("src.Arbitrage.dashboard.refresh_reviewed_pairs",
                 side_effect=lambda reviews, now: verified_pairs([left], [right], reviews)):
            report = assessment_report([left], [right], [], [], NOW)
            row, = report["verified"]
            self.assertEqual(row["evidence"]["polymarket_rulebook"], ROTC_BOOK)
            self.assertEqual(live_pairs([], report, NOW)[0], [(left, right)])
            catalog["ROTC"]["versions"]["2026-11-05"] = {"effective": "2026-11-12", "rule": "40.6"}
            self.assertEqual(live_pairs([], report, NOW), ([], []))
            row, = self.assess(left, right)["manual_review"]
            self.assertIn("product certification", row["reason"])

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_inline_policy_can_verify_but_event_clarification_blocks_pricing(self, _):
        left, right = contracts()
        right.update(rules=right["rules"].split("\nGoverning contract terms:", 1)[0],
                     market_id="100", market_event_id="200")
        policy = rule_policy(right["rules"])
        with patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook("full", policy)), patch(
            "src.Arbitrage.settlement_verification.fetch_json", return_value=([], {}),
        ) as fetch, patch("src.Arbitrage.dashboard.refresh_reviewed_pairs",
                         side_effect=lambda reviews, now: verified_pairs([left], [right], reviews)):
            report = assessment_report([left], [right], [], [], NOW)
            row, = report["verified"]
            self.assertEqual(row["evidence"]["polymarket_source"], "inline_rules")
            self.assertEqual(fetch.call_args.args, (f"{GAMMA_URL}/market-clarifications", {"event_id": "200", "limit": 1}))
            self.assertEqual(live_pairs([], report, NOW)[0], [(left, right)])
            fetch.side_effect = lambda url, params: ([{}] if "event_id" in params else [], {})
            self.assertEqual(live_pairs([], report, NOW), ([], []))
            row, = self.assess(left, right)["manual_review"]
            self.assertIn("clarifications", row["reason"])

    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_same_film_at_the_exact_threshold_has_different_payouts(self, _):
        left, right = contracts()
        left.update(id="KXRT-FILM-45", resolution={"strike_type": "greater", "floor_strike": 45},
                    rules="If Example Film has a Tomatometer score of above 45 on Nov 23, 2026 at 10:00 AM ET, "
                          "then the market resolves to Yes.", secondary_rules="Only strictly greater scores count.")
        right.update(id="rotc-film-gte45", venue=POLY_US, listed_at="2026-10-01T00:00:00Z",
                     rules="This market will settle to Yes if Example Film has a Rotten Tomatoes Tomatometer score "
                           "of 45 or more on November 23, 2026 at 10:00 AM ET. Outcome sourced from Rotten Tomatoes.")
        digest = sha256(left["secondary_rules"].encode()).hexdigest()
        docs = {BOOK: Rulebook(RATING_BOOKS[0]), ROTC_BOOK: Rulebook(RATING_BOOKS[1])}
        with patch("src.Arbitrage.settlement_verification.load_filing_catalog", return_value=rotc_catalog()), patch(
            "src.Arbitrage.settlement_verification.load_rulebook", side_effect=docs.get,
        ), patch("src.Arbitrage.settlement_verification.RATING_KALSHI_SECONDARY", digest):
            report = assessment_report([left], [right], [], [], NOW)
            row, = shared_event_rows(report)
            self.assertEqual(row["difference"]["scenario"], "The Tomatometer score is exactly 45%")
            self.assertEqual(row["difference"]["kalshi_payout"], "No")
            self.assertEqual(row["difference"]["polymarket_payout"], "Yes")
            self.assertFalse(report["verified"])
            right["rules"] = right["rules"].replace("10:00 AM", "9:00 AM")
            self.assertFalse(self.assess(left, right)["different_rules"])

    @patch("src.Arbitrage.settlement_verification.load_rulebook", side_effect=lambda url: Rulebook(url))
    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_only_the_same_appointment_with_proven_different_cutoffs_goes_to_shared_events(self, _, __):
        left, right = contracts()
        left["rules"] = ("If Example Person formally holds the position of White House Press Secretary before "
                         "January 20, 2029, and is the first such subject to do so, then the market resolves to Yes.")
        right["rules"] = ('This market will settle to "Yes" if Example Person is the next person to assume the position '
                          'of White House Press Secretary by December 31, 2027 at 11:59 PM ET.\n'
                          'For full rules, see: https://polymarketexchange.com/files/product-terms/NPHC.pdf')
        right.update(venue="polymarket_us", close_time=NOW + timedelta(days=425))
        different_person = dict(right, id="poly-2", rules=right["rules"].replace("Example Person", "Other Person"))
        ambiguous = dict(right, id="poly-3", rules=right["rules"].replace("December 31, 2027", "January 19, 2029"))
        report = assessment_report([left], [right, different_person, ambiguous], [], [], NOW)
        self.assertEqual(report["verified"], [])
        self.assertEqual(len(report["manual_review"]), 1)
        row, = shared_event_rows(report)
        self.assertEqual(row["polymarket_venue"], "polymarket_us")
        self.assertEqual(row["polymarket_id"], right["id"])
        self.assertEqual(row["difference"]["kalshi_cutoff"], "2029-01-20")
        self.assertEqual(row["difference"]["polymarket_cutoff"], "2027-12-31")
        self.assertEqual((row["difference"]["kalshi_payout"], row["difference"]["polymarket_payout"]), ("Yes", "No"))

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

    @patch("src.Arbitrage.settlement_verification.load_rulebook", return_value=Rulebook("same"))
    @patch("src.Arbitrage.settlement_verification.rulebook_url", return_value=BOOK)
    def test_full_assessment_prices_only_proven_equivalent_midnight_cutoffs(self, _, __):
        left, right = contracts()
        left["secondary_rules"] += (
            " The result may be posted through the end of the 11:59 p.m. ET minute on November 20, 2026."
        )
        right["secondary_rules"] = "The result may be posted before 12:00 a.m. ET on November 21, 2026."
        report = assessment_report(
            [left], [right], review_candidates([left], [right]), review_leads([left], [right]), NOW,
        )
        self.assertEqual(len(report["verified"]), 1)

        left["secondary_rules"] = left["secondary_rules"].replace(
            "through the end of the 11:59 p.m. ET minute on", "by 11:59 p.m. ET on"
        )
        report = assessment_report(
            [left], [right], review_candidates([left], [right]), review_leads([left], [right]), NOW,
        )
        self.assertEqual(report["verified"], [])
        row, = report["manual_review"]
        self.assertEqual(row["lead_reason"], "Compare the end-of-day cutoff wording")

    def test_full_rulebook_compares_equivalent_cutoffs(self):
        last_minute = pdf(
            "A result counts through 11:59 p.m. ET on November 20, 2026, including the entire final minute."
        )
        midnight = pdf("A result counts before midnight ET at the start of November 21, 2026.")
        ambiguous = pdf("A result counts by 11:59 p.m. ET on November 20, 2026.")
        self.assertIsNotNone(last_minute.policy)
        self.assertEqual(last_minute.policy, midnight.policy)
        self.assertNotEqual(ambiguous.policy, midnight.policy)
