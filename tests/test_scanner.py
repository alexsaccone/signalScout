import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from src.Arbitrage.ai_filter import main


class ScannerTest(unittest.TestCase):
    def test_replay_writes_a_snapshot_without_network(self):
        fixture = Path(__file__).parent / "fixtures" / "scan.json"
        with TemporaryDirectory() as directory, mock.patch(
            "requests.sessions.Session.request", side_effect=AssertionError("Unexpected HTTP request")
        ):
            output = Path(directory) / "opportunities.csv"
            main(["--fixture", str(fixture), "--output", str(output)])
            with output.open(newline="", encoding="utf-8") as snapshot:
                row, = csv.DictReader(snapshot)

        self.assertEqual(row["kalshi_name"], "Will Example A win?")
        self.assertEqual(row["polymarket_token"], "10")
        self.assertEqual(row["max_contracts"], "10")
        self.assertEqual(row["estimated_fees"], "0.27000")
        self.assertEqual(row["estimated_net_profit"], "0.73000")
