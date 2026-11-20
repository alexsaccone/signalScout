from contextlib import redirect_stderr, redirect_stdout
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import requests

from src.Arbitrage.ai_filter import atomic_write, main
from src.Arbitrage.api import fetch_json, KALSHI_URL, more_kalshi, ScanError
from src.Arbitrage.pricing import OUTPUT_FIELDS


def response(status, body=None, headers=None):
    reply = requests.Response()
    reply.status_code = status
    reply.headers.update(headers or {})
    reply.json = mock.Mock(return_value=body)
    return reply


class ReliabilityTest(unittest.TestCase):
    def test_rate_limit_and_timeout_retry_then_succeed(self):
        responses = [response(429, headers={"Retry-After": "3"}), requests.Timeout(), response(200, [])]
        with mock.patch("src.Arbitrage.api.requests.get", side_effect=responses) as get, mock.patch(
            "src.Arbitrage.api.sleep"
        ) as pause:
            self.assertEqual(fetch_json("https://example.com")[0], [])
        self.assertEqual(pause.call_args_list, [mock.call(3), mock.call(2)])
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 15))

    def test_cursor_loop_and_page_limit_are_incomplete(self):
        page = response(200, {"markets": [{}], "cursor": "next"})
        for cap, message in ((1, "page limit"), (2, "repeated pagination cursor")):
            with self.subTest(cap=cap), mock.patch("src.Arbitrage.api.requests.Session.get", return_value=page):
                with self.assertRaisesRegex(ScanError, message):
                    more_kalshi(cap, datetime.now(timezone.utc))

    def test_partial_fetch_preserves_snapshot_and_complete_empty_replaces_it(self):
        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / "opportunities.csv"
            snapshot.write_bytes(b"previous snapshot\n")
            reviews = Path(directory) / "reviews.json"
            reviews.write_text("[]", encoding="utf-8")
            candidates = Path(directory) / "candidates.json"
            args = ["--reviewed-pairs", str(reviews), "--output", str(snapshot), "--review-candidates", str(candidates)]
            partial = response(200, {"markets": [{}], "cursor": "next"})
            failures = [partial] + [response(503)] * 3
            empty = response(200, {"markets": [], "cursor": ""})
            def partial_fetch(url, **_):
                return failures.pop(0) if url.startswith(KALSHI_URL) else empty

            with mock.patch("src.Arbitrage.api.requests.Session.get", side_effect=partial_fetch), mock.patch(
                "src.Arbitrage.api.sleep"
            ), redirect_stderr(StringIO()) as error:
                self.assertEqual(main(args), 1)
                self.assertIn("Scan failed", error.getvalue())
            self.assertEqual(snapshot.read_bytes(), b"previous snapshot\n")

            with mock.patch("src.Arbitrage.api.requests.Session.get", return_value=empty), redirect_stdout(StringIO()) as output:
                self.assertEqual(main(args), 0)
                self.assertIn("0 opportunities", output.getvalue())
            with snapshot.open(newline="", encoding="utf-8") as output:
                self.assertEqual(list(csv.reader(output)), [list(OUTPUT_FIELDS)])

    def test_write_failure_keeps_previous_snapshot_and_removes_temp_file(self):
        def fail(output):
            output.write("partial")
            raise OSError("disk full")

        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / "opportunities.csv"
            snapshot.write_text("previous", encoding="utf-8")
            with self.assertRaisesRegex(OSError, "disk full"):
                atomic_write(snapshot, fail)
            self.assertEqual(snapshot.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).iterdir()), [snapshot])

    def test_reviewed_scan_reads_only_the_reviewed_market_ids(self):
        fixture_path = Path(__file__).parent / "fixtures" / "scan.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        now = datetime.fromisoformat(fixture["as_of"])
        pages = [
            response(200, {"markets": fixture["kalshi"], "cursor": ""}),
            response(200, {"markets": fixture["polymarket"]}),
        ]
        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / "opportunities.csv"
            reviews = Path(directory) / "reviewed.json"
            reviews.write_text(json.dumps(fixture["reviewed_pairs"]), encoding="utf-8")
            args = ["--reviewed-pairs", str(reviews), "--output", str(snapshot)]
            with mock.patch("src.Arbitrage.api.requests.Session.get", side_effect=pages) as get, mock.patch(
                "src.Arbitrage.ai_filter.datetime", wraps=datetime
            ) as clock, mock.patch("src.Arbitrage.ai_filter.price_pairs") as price, redirect_stdout(StringIO()):
                clock.now.return_value = now
                price.return_value = []
                self.assertEqual(main(args), 0)
                pair, = list(price.call_args.args[0])
            self.assertEqual([leg["id"] for leg in pair], ["K-EXAMPLE", "P-EXAMPLE"])
            queries = [call.kwargs["params"] for call in get.call_args_list]
            self.assertEqual(queries, [{"tickers": "K-EXAMPLE"},
                                       {"condition_ids": ["P-EXAMPLE"], "closed": "false", "limit": 100}])
