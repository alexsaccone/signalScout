import csv
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from src.Arbitrage.ai_filter import main


class ScannerTest(unittest.TestCase):
    def test_default_fixture_output_preserves_the_live_report(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            location = Path(directory)
            live = location / "opportunities.csv"
            live.write_text("previous live report\n", encoding="utf-8")
            subprocess.run(
                [sys.executable, "-B", str(root / "src/Arbitrage/ai_filter.py"),
                 "--fixture", str(root / "tests/fixtures/scan.json")],
                cwd=location, check=True, capture_output=True,
            )
            self.assertEqual(live.read_text(encoding="utf-8"), "previous live report\n")
            with (location / "opportunities.example.csv").open(newline="", encoding="utf-8") as snapshot:
                row, = csv.DictReader(snapshot)
            self.assertEqual(row["kalshi_name"], "Will Example A win?")

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
