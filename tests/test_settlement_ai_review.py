from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import requests

from src.Arbitrage.settlement_ai_review import review_queue, review_with_gemini, valid_review


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
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini", return_value=(DIFFERENCE, None))
    def test_reviews_manual_queue_and_reuses_unchanged_evidence(self, gemini, document):
        report = assessment()
        original = deepcopy(report)
        cache = {}
        first = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(first["counts"], {"reviewed": 1})
        self.assertEqual(report, original)
        self.assertEqual(gemini.call_args.args[1][-1]["type"], "document")
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
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini", return_value=(None, "quota_exhausted"))
    def test_quota_stops_calls_and_next_run_prioritizes_untried_pairs(self, gemini, _):
        report = assessment()
        other = deepcopy(report["manual_review"][0])
        other["pair"]["polymarket"]["id"] = "next-pair"
        report["manual_review"].append(other)
        cache = {}
        self.assertEqual(review_queue(report, cache, None)["counts"], {"missing_api_key": 2})
        gemini.assert_not_called()
        first = review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(first["api_attempts"], 1)
        self.assertEqual(first["counts"], {"quota_exhausted": 2})
        self.assertFalse(any("review" in entry for entry in cache.values()))
        review_queue(report, cache, "test-key", pause=0)
        self.assertEqual(gemini.call_count, 2)
        self.assertIn("next-pair", gemini.call_args.args[1][0]["text"])

    @patch("src.Arbitrage.settlement_ai_review.document", return_value=("PDF", (KALSHI_QUOTE,)))
    @patch("src.Arbitrage.settlement_ai_review.review_with_gemini")
    def test_timeout_leaves_its_pair_pending_and_continues_review(self, gemini, _):
        report = assessment()
        other = deepcopy(report["manual_review"][0])
        other["pair"]["polymarket"]["id"] = "next-pair"
        report["manual_review"].append(other)
        gemini.side_effect = [requests.ReadTimeout(), (DIFFERENCE, None)]
        cache = {}

        result = review_queue(report, cache, "test-key", pause=0)

        self.assertEqual(result["api_attempts"], 2)
        self.assertEqual(result["counts"], {"api_timeout": 1, "reviewed": 1})
        self.assertEqual(sum("review" in entry for entry in cache.values()), 1)

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
        self.assertEqual(review_with_gemini("test-key", []), (DIFFERENCE, None))
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertFalse(post.call_args.kwargs["json"]["store"])
        self.assertNotIn("tools", post.call_args.kwargs["json"])
        reply.json.return_value["status"] = "incomplete"
        self.assertEqual(review_with_gemini("test-key", []), (None, "invalid_response"))


if __name__ == "__main__":
    unittest.main()
