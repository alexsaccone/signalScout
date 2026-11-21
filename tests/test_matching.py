from pathlib import Path
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from src.Arbitrage.api import normalize_market, POLY_US, utc_timestamp
from src.Arbitrage.searcher import review_candidates, review_leads, verified_pairs


class MatchingTest(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "scan.json").read_text(encoding="utf-8"))
        now = utc_timestamp(fixture["as_of"])
        self.kalshi = normalize_market(fixture["kalshi"][0], "kalshi", now)
        self.poly = normalize_market(fixture["polymarket"][0], "polymarket", now)
        self.reviews = fixture["reviewed_pairs"]

    def matching_contracts(self):
        event = "the Boston Celtics vs Miami Heat game on November 20, 2026 at 7 PM ET"
        condition = f"Alex Example scores at least 20 points in {event}"
        terms = "Use https://www.nba.com/stats as the official source. If the game is canceled, settle at 50-50."
        kalshi = dict(self.kalshi, title="Player points", rules=f"If {condition}, then the market resolves to Yes.",
                      secondary_rules=terms)
        poly = dict(self.poly, title="Alex Example: 20+ points",
                    rules=f'This market will resolve to "Yes" if {condition.replace("November", "Nov.")}.\n{terms}',
                    resolution="https://www.nba.com/stats")
        return kalshi, poly

    def test_reviewed_pair_keeps_canonical_ids_and_outcomes(self):
        pair, = verified_pairs([self.kalshi], [self.poly], self.reviews * 2)
        self.assertEqual((pair[0]["id"], pair[1]["id"]), ("K-EXAMPLE", "P-EXAMPLE"))
        self.assertEqual(pair[1]["tokens"], {"yes": "20", "no": "10"})

    def test_manual_leads_keep_possible_fixtures_with_unverified_rules(self):
        kalshi, poly = self.matching_contracts()
        left = dict(kalshi, rules=kalshi["rules"].replace("Miami Heat game", "Miami Heat NBA game"))
        right = dict(poly, rules=poly["rules"].replace("Miami Heat game", "Miami Heat NBA game")
                     .replace("settle at 50-50", "settle at fair market price"))
        other_day = dict(right, id="different-date", rules=right["rules"].replace("Nov. 20", "Nov. 21"))
        self.assertEqual(review_candidates([left], [right]), [])
        lead, = review_leads([left], [other_day, right])
        self.assertEqual(lead["event_date"], "2026-11-20")
        self.assertEqual(lead["polymarket"]["rules"], right["rules"])
        self.assertEqual(list(verified_pairs([left], [right], [])), [])

        left = dict(left, title="Boston wins 1st Half")
        first_half = dict(right, title="Boston Celtics leading at halftime?")
        full_match = dict(right, id="full-match", title="Boston Celtics wins")
        lead, = review_leads([left], [first_half, full_match])
        self.assertEqual(lead["polymarket"]["id"], right["id"])

    def test_title_similarity_without_full_terms_is_insufficient(self):
        self.assertEqual(review_candidates([self.kalshi], [self.poly]), [])

    def test_discovery_limits_apply_independently_to_each_polymarket_venue(self):
        left, international = self.matching_contracts()
        markets = [dict(international, id="A", venue=POLY_US), dict(international, id="B", venue=POLY_US), international]
        expected = {"A", international["id"]}
        with patch.multiple("src.Arbitrage.searcher", MAX_SUGGESTIONS=1, MAX_LEADS=1, MAX_POSTINGS=2):
            self.assertEqual({row["polymarket"]["id"] for row in review_candidates([left], markets)}, expected)
            self.assertEqual({row["polymarket"]["id"] for row in review_leads([left], markets)}, expected | {"B"})
            fuzzy = [dict(market, rules=market["rules"].replace("at least 20 points", "exactly 20 points"))
                     for market in markets]
            self.assertEqual({row["polymarket"]["id"] for row in review_leads([left], fuzzy)}, expected)

    def test_reworded_titles_and_equivalent_terms_are_suggested_for_review(self):
        kalshi, poly = self.matching_contracts()
        candidate, = review_candidates([kalshi], [poly])
        self.assertEqual(candidate["polymarket"]["title"], poly["title"])
        self.assertEqual(list(verified_pairs([kalshi], [poly], [])), [])

    def test_events_players_and_payout_details_must_match(self):
        kalshi, poly = self.matching_contracts()
        for wrong, replacement in (
            ("Miami Heat", "Atlanta Hawks"),
            ("Nov. 20", "Nov. 21"),
            ("7 PM", "8 PM"),
            ("Alex Example", "Alex Samples"),
            ("at least 20", "more than 20"),
            ("50-50", "a fair market price"),
            ("www.nba.com/stats", "www.espn.com/stats"),
        ):
            with self.subTest(term=wrong):
                changed = dict(poly, title=kalshi["title"], rules=poly["rules"].replace(wrong, replacement))
                self.assertEqual(review_candidates([kalshi], [changed]), [])

    def test_accepts_a_separate_scheduled_event_clause(self):
        kalshi, poly = self.matching_contracts()
        left = dict(kalshi, rules=kalshi["rules"].replace("Miami Heat game", "Miami Heat NBA game"))
        right = dict(poly, rules=(
            "In the upcoming NBA game between Boston Celtics and Miami Heat, "
            "originally scheduled for Friday, November 20, 2026 at 7 PM ET "
            "(as of creation of the first market related to the event):\n\n"
            'If Alex Example scores at least 20 points, this market will resolve to "Yes".\n\n'
            + kalshi["secondary_rules"]
        ))
        self.assertEqual(len(review_candidates([left], [right])), 1)
        wrong = dict(right, rules=right["rules"].replace("and Miami Heat", "and Milwaukee Bucks"))
        self.assertEqual(review_candidates([left], [wrong]), [])

    def test_paraphrased_point_threshold_and_settlement_clauses(self):
        kalshi, poly = self.matching_contracts()
        source = "https://www.nba.com/stats"
        kalshi["secondary_rules"] += " Otherwise, this market will resolve to No."
        poly["rules"] = (
            'In the upcoming NBA game between Boston Celtics and Miami Heat, scheduled for '
            'Nov. 20, 2026 at 7:00 p.m. ET: This market will resolve to "Yes" if Alex Example '
            'records 20 or more points. If the game is cancelled, this market will resolve to '
            '"50-50." Otherwise, this market will resolve to "No." '
            f'The resolution source for this market is {source}.'
        )
        kalshi["rules"] = kalshi["rules"].replace("vs Miami Heat game on", "versus Miami Heat NBA game on")
        candidate, = review_candidates([kalshi], [poly])
        self.assertEqual(candidate["polymarket"]["rules"], poly["rules"])
        self.assertEqual(list(verified_pairs([kalshi], [poly], [])), [])

        for old, new in (
            ("20 or more", "more than 20"), ("records 20 or more", "records exactly 20"),
            ("20 or more points", "20 or more assists"), ("Alex Example", "Alex Samples"),
            ("50-50", "a fair market price"), ("is cancelled", "is postponed"),
            ('"No."', '"Yes."'), ("7:00 p.m.", "7:10 p.m."),
            (source, "https://example.org/stats"),
        ):
            with self.subTest(term=old):
                changed = dict(poly, rules=poly["rules"].replace(old, new))
                self.assertEqual(review_candidates([kalshi], [changed]), [])

    def test_matches_whole_final_minute_and_exclusive_next_midnight(self):
        kalshi, poly = self.matching_contracts()
        kalshi["secondary_rules"] += (
            " The result may be posted through Friday, Nov. 20, 2026 at 11:59 p.m. ET, "
            "including the entire final minute."
        )
        for cutoff in (
            "before midnight ET at the start of November 21, 2026",
            "before 12:00 a.m. ET on November 21, 2026",
            "before November 21, 2026 at 00:00 ET",
        ):
            with self.subTest(cutoff=cutoff):
                right = dict(poly, rules=f"{poly['rules']} The result may be posted {cutoff}.")
                [pair] = review_candidates([kalshi], [right])
                self.assertEqual(pair["polymarket"]["rules"], right["rules"])

    def test_ambiguous_cutoff_goes_to_manual_leads(self):
        kalshi, poly = self.matching_contracts()
        kalshi["rules"] = kalshi["rules"].replace(
            ", then the market", ", with the result posted by Friday, Nov. 20, 2026 at 11:59 p.m. ET, then the market"
        )
        poly["rules"] = poly["rules"].replace(
            " at 7 PM ET.", " at 7 PM ET, with the result posted by midnight ET on November 21, 2026."
        )
        self.assertEqual(review_candidates([kalshi], [poly]), [])
        [lead] = review_leads([kalshi], [poly])
        self.assertEqual(lead["reason"], "Compare the end-of-day cutoff wording")

    def test_keeps_other_end_of_day_cutoffs_distinct(self):
        kalshi, poly = self.matching_contracts()
        kalshi["secondary_rules"] += " Use the value at November 20, 2026 at 11:59 p.m. ET."
        right = dict(poly, rules=f"{poly['rules']} Use the value at November 21, 2026 at 12:00 a.m. ET.")
        self.assertEqual(review_candidates([kalshi], [right]), [])

        kalshi, poly = self.matching_contracts()
        kalshi["secondary_rules"] += (
            " The result may be posted through the end of the 11:59 p.m. ET minute on November 20, 2026."
        )
        for cutoff in (
            "before midnight ET at the start of November 22, 2026",
            "before midnight CT at the start of November 21, 2026",
            "by November 21, 2026 at 12:00 a.m. ET",
            "before midnight ET on November 21, 2026",
            "before Sunday, November 21, 2026 at 12:00 a.m. ET",
        ):
            with self.subTest(cutoff=cutoff):
                right = dict(poly, rules=f"{poly['rules']} The result may be posted {cutoff}.")
                self.assertEqual(review_candidates([kalshi], [right]), [])

    def test_unrecognized_deadline_and_quoted_condition_stay_distinct(self):
        kalshi, poly = self.matching_contracts()
        kalshi["secondary_rules"] += " If no score is posted within 48 hours, settle at 50-50."
        poly["rules"] += " If no score is posted within 72 hours, settle at 50-50."
        self.assertEqual(review_candidates([kalshi], [poly]), [])

        kalshi, poly = self.matching_contracts()
        kalshi["rules"] = kalshi["rules"].replace("at least 20 points", '"at least 20 points"')
        poly["rules"] = poly["rules"].replace("at least 20 points", '"20 or more points"')
        self.assertEqual(review_candidates([kalshi], [poly]), [])

        kalshi, poly = self.matching_contracts()
        phrase = "Boston Celtics vs Miami Heat game"
        kalshi["rules"] = kalshi["rules"].replace(phrase, f'"{phrase}" in Game 1')
        poly["rules"] = poly["rules"].replace(phrase, f'"{phrase.replace("vs", "versus")}" in Game 1')
        self.assertEqual(review_candidates([kalshi], [poly]), [])

    def test_requires_a_confirmed_settlement_source(self):
        kalshi, poly = self.matching_contracts()
        self.assertEqual(review_candidates([dict(kalshi, secondary_rules="")], [poly]), [])
        wrong = dict(poly, resolution="https://www.espn.com/stats")
        self.assertEqual(review_candidates([kalshi], [wrong]), [])

    def test_rejects_an_unnamed_player_or_undated_fixture(self):
        kalshi, poly = self.matching_contracts()
        for original, ambiguous in (("Alex Example", "the player"), (", 2026", "")):
            with self.subTest(term=original):
                left = dict(kalshi, rules=kalshi["rules"].replace(original, ambiguous))
                right = dict(poly, rules=poly["rules"].replace(original, ambiguous))
                self.assertEqual(review_candidates([left], [right]), [])

    def test_bounds_duplicate_results_when_exchange_closing_times_differ(self):
        kalshi, poly = self.matching_contracts()
        copies = [dict(poly, id=f"P-{index:03d}",
                       close_time=poly["close_time"] + timedelta(days=2)) for index in range(100)]
        matches = review_candidates([kalshi], list(reversed(copies)))
        self.assertEqual([pair["polymarket"]["id"] for pair in matches], ["P-000", "P-001", "P-002"])

    def test_market_terms_change_invalidates_the_review(self):
        for changed in (
            dict(self.poly, title="Will Example A win Game 2?"),
            dict(self.poly, rules="Settle only if Example A wins by 2."),
            dict(self.poly, tokens={"no": "20", "yes": "10"}),
            dict(self.poly, resolution="Another results source"),
        ):
            with self.subTest(changed=changed):
                self.assertEqual(list(verified_pairs([self.kalshi], [changed], self.reviews)), [])
