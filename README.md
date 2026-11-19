TODO:

- Establish and evaluate a pregame sports prediction baseline.

## Market dashboard

The [SignalScout dashboard](https://alexsaccone.github.io/signalScout/) shows
upcoming Polymarket moneyline odds and estimates for reviewed contract pairs.
The GitHub Actions workflow refreshes the snapshot roughly every two hours.
A failed run leaves the previous snapshot online, with its original update
time. Polymarket odds cover games starting within three days.

Add confirmed reviews to `data/reviewed_pairs.json` to include them in the
scheduled scan. An empty review list still publishes upcoming game odds.

To preview the dashboard offline, generate its labeled fixture snapshot from
the repository root with the Python environment below.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.dashboard --fixture tests/fixtures/scan.json
cd src/website
npm ci
npm run dev
```

Use Node.js 22. On macOS and Linux, run the first command with `python` from
the activated environment.

## Running the market scanner

Run these commands from the repository root. The scanner uses Python 3.12.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --fixture tests/fixtures/scan.json --output opportunities.csv
```

### macOS and Linux

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.Arbitrage.ai_filter --fixture tests/fixtures/scan.json --output opportunities.csv
```

### Live scans

Live discovery searches public markets closing within 24 hours. Use
`--hours` to adjust the discovery window. When pricing a list of reviewed
pairs, the scanner fetches those markets by ID and checks that they are
still tradable and close within 30 days.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --review-candidates candidates.json
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --reviewed-pairs reviewed.json --output opportunities.csv
```

On macOS and Linux, use `python` from the activated environment in these commands.

The first command exports similarly titled contracts for review. Copy pairs
with equivalent outcomes and settlement rules into a JSON array in
`reviewed.json`. The fixture shows the format under `reviewed_pairs`.
Pairs whose listed terms or outcome tokens change require a fresh review.

The scanner uses the best available buy price and size on each order book,
venue taker fees, and whole matched contracts. The CSV reports the older of
the two quote times and estimated net return as a percentage. Quotes older
than 60 seconds and unsupported fee models are skipped.

A complete scan with no opportunities writes a header-only CSV. A failed or
incomplete scan exits with status 1 and preserves the previous snapshot.
