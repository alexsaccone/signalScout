from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import requests

from src.Arbitrage.settlement_ai_review import FALLBACK_MODEL, PRIMARY_MODEL, review_queue, review_with_gemini, valid_review


KALSHI_QUOTE = "If the event is canceled, each side pays fair value."
POLY_QUOTE = "If the event is canceled, the market settles to No."
DIFFERENCE = {
    "verdict": "different_rules",
    "summary": "The venues pay differently on cancellation.",
    "quotes": [
        {"venue": "kalshi", "page": 1, "quote": KALSHI_QUOTE},
        {"venue": "polymarket", "page": 0, "quote": POLY_QUOTE},
    ],
}


def assessment():
    candidate = {
        "pair": {
            "kalshi": {"id": "KXTEST-EVENT-YES", "rules": "The fixture winner pays Yes.", "secondary_rules": ""},
            "polymarket": {"id": "test-yes", "rules": POLY_QUOTE, "secondary_rules": ""},
        },
        "evidence": {
            "kalshi_rulebook": "https://assets.kalshi.com/contract_terms/TEST.pdf", "kalshi_sha256": "digest",
            "polymarket_source": "inline_rules",
        },
        "reason": "The rules differ in wording.",
    }
    return {"generated_at": "2026-11-22T17:00:00Z", "verified": [], "manual_review": [candidate]}


class SettlementAIReviewTest(unittest.TestCase):
    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini", return_value=(DIFFERENCE, None, 0))
    def test_reviews_manual_queue_and_reuses_unchanged_evidence(self, gemini, document):
        report = assessment()
        original = deepcopy(report)
        cache = {}
        first = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(first["counts"], {"reviewed": 1})
        self.assertEqual(first["review_counts_by_model"], {PRIMARY_MODEL: 1})
        self.assertEqual(report, original)
        self.assertEqual(gemini.call_args.args[1][-1]["type"], "document")
        del next(iter(cache.values()))["model"]
        self.assertEqual(review_queue(report, cache, "test-key", pause=0)["counts"], {"cached": 1})
        self.assertEqual(gemini.call_count, 1)
        self.assertEqual(document.call_count, 1)
        report["manual_review"][0]["evidence"]["kalshi_sha256"] = "changed"
        self.assertEqual(review_queue(report, cache, "test-key", pause=0)["counts"], {"reviewed": 1})
        self.assertEqual(gemini.call_count, 2)

    def test_requires_real_quotes_and_full_evidence_for_equivalence(self):
        sources = {"kalshi": ("", KALSHI_QUOTE), "polymarket": (POLY_QUOTE,)}
        self.assertTrue(valid_review(DIFFERENCE, sources))
        self.assertFalse(valid_review(dict(DIFFERENCE, verdict="likely_equivalent"), sources))
        fabricated = deepcopy(DIFFERENCE)
        fabricated["quotes"][0]["quote"] = "If the event is canceled, the market pays Yes."
        self.assertFalse(valid_review(fabricated, sources))
        fabricated["quotes"][0] = dict(DIFFERENCE["quotes"][0], page=0)
        self.assertFalse(valid_review(fabricated, sources))

    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini", return_value=(None, "quota_exhausted", 60))
    def test_quota_stops_calls_and_next_run_prioritizes_untried_pairs(self, gemini, _):
        report = assessment()
        other = deepcopy(report["manual_review"][0])
        other["pair"]["polymarket"]["id"] = "next-pair"
        report["manual_review"].append(other)
        cache = {}
        self.assertEqual(review_queue(report, cache, None)["counts"], {"missing_api_key": 2})
        gemini.assert_not_called()
        first = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(first["api_attempts_by_model"], {PRIMARY_MODEL: 1, FALLBACK_MODEL: 1})
        self.assertEqual(first["counts"], {"quota_exhausted": 2})
        self.assertFalse(any("review" in entry for entry in cache.values()))
        review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(gemini.call_count, 4)
        self.assertIn("next-pair", gemini.call_args.args[1][0]["text"])

    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini")
    def test_timeout_falls_back_and_the_next_pair_tries_hydrogen(self, gemini, _):
        report = assessment()
        other = deepcopy(report["manual_review"][0])
        other["pair"]["polymarket"]["id"] = "next-pair"
        report["manual_review"].append(other)
        gemini.side_effect = [requests.ReadTimeout(), (DIFFERENCE, None, 0), (DIFFERENCE, None, 0)]
        cache = {}

        result = review_queue(report, cache, "test-key", pause=0)

        self.assertEqual(result["api_attempts"], 3)
        self.assertEqual(result["counts"], {"reviewed": 2})
        self.assertEqual([row["review_model"] for row in result["reviews"]], [FALLBACK_MODEL, PRIMARY_MODEL])
        self.assertEqual(sum("review" in entry for entry in cache.values()), 2)

    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini")
    def test_rechecks_flash_only_after_pairs_without_ai_reviews(self, gemini, _):
        report = assessment()
        cache = {}
        gemini.side_effect = [(None, "quota_exhausted", 60), (DIFFERENCE, None, 0)]
        flash, = review_queue(report, cache, "test-key", pause=0)["reviews"]
        self.assertEqual(flash["review_model"], FALLBACK_MODEL)
        old_candidate = report["manual_review"][0]
        for id in ("new-pair-1", "new-pair-2"):
            other = deepcopy(old_candidate)
            other["pair"]["polymarket"]["id"] = id
            report["manual_review"].append(other)

        gemini.reset_mock()
        gemini.side_effect = [(None, "invalid_response", 0)] * 4
        incomplete = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual([row["status"] for row in incomplete["reviews"]], ["cached", "invalid_response", "invalid_response"])
        self.assertEqual(gemini.call_count, 4)
        self.assertTrue(all("new-pair-" in call.args[1][0]["text"] for call in gemini.call_args_list))

        gemini.reset_mock()
        gemini.side_effect = [(DIFFERENCE, None, 0)] * 3
        first = review_queue(report, cache, "test-key", limit=1, pause=0)
        self.assertEqual([row["status"] for row in first["reviews"]], ["cached", "reviewed", "deferred"])
        self.assertIn("new-pair-1", gemini.call_args.args[1][0]["text"])

        gemini.reset_mock()
        second = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual([row["review_model"] for row in second["reviews"]], [PRIMARY_MODEL] * 3)
        self.assertEqual([row["status"] for row in second["reviews"]], ["reviewed", "cached", "reviewed"])
        self.assertIn("new-pair-2", gemini.call_args_list[0].args[1][0]["text"])
        self.assertIn("test-yes", gemini.call_args_list[1].args[1][0]["text"])
        self.assertEqual(cache[flash["fingerprint"]]["review"], DIFFERENCE)
        self.assertNotEqual(second["reviews"][0]["fingerprint"], flash["fingerprint"])
        self.assertEqual(review_queue(report, cache, None)["review_counts_by_model"], {PRIMARY_MODEL: 3})

    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini")
    def test_model_cooldown_uses_flash_and_failed_recheck_keeps_its_review(self, gemini, _):
        report = assessment()
        other = deepcopy(report["manual_review"][0])
        other["pair"]["polymarket"]["id"] = "next-pair"
        report["manual_review"].append(other)
        cache = {}
        gemini.side_effect = [(None, "api_http_503", 60), (DIFFERENCE, None, 0), (DIFFERENCE, None, 0)]
        first = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(first["api_attempts_by_model"], {PRIMARY_MODEL: 1, FALLBACK_MODEL: 2})

        gemini.side_effect = [(None, "quota_exhausted", 60)]
        second = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(second["api_attempts_by_model"], {PRIMARY_MODEL: 1})
        self.assertEqual([row["review_model"] for row in second["reviews"]], [FALLBACK_MODEL] * 2)
        self.assertEqual([row["hydrogen_recheck_status"] for row in second["reviews"]], ["quota_exhausted"] * 2)

    @patch("src.Arbitrage.settlement_ai_review.requests.post")
    def test_gemini_request_and_parse_completed_response(self, post):
        reply = post.return_value
        reply.status_code = 200
        reply.json.return_value = {
            "status": "completed", "steps": [
                {"type": "thought"},
                {"type": "model_output", "content": [{"type": "text", "text": json.dumps(DIFFERENCE)}]},
            ],
        }
        self.assertEqual(review_with_gemini("test-key", [], FALLBACK_MODEL), (DIFFERENCE, None, 0))
        self.assertEqual(post.call_args.kwargs["json"]["model"], FALLBACK_MODEL)
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertFalse(post.call_args.kwargs["json"]["store"])
        self.assertNotIn("tools", post.call_args.kwargs["json"])
        reply.json.return_value["status"] = "incomplete"
        self.assertEqual(review_with_gemini("test-key", []), (None, "invalid_response", 0))
        reply.status_code = 503
        reply.headers = {"Retry-After": "30"}
        self.assertEqual(review_with_gemini("test-key", []), (None, "api_http_503", 30))


if __name__ == "__main__":
    unittest.main()
