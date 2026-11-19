# SignalScout

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
```

### macOS and Linux

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

### Live scans

Live discovery pulls public Kalshi and Polymarket markets closing within
24 hours. Use `--hours` to adjust the discovery window. The discovery
command writes possible matches to `candidates.json` for manual review.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --review-candidates candidates.json
```

Compare both contracts' outcomes and settlement rules. Copy confirmed pairs
from `candidates.json` into the JSON array in `data/reviewed_pairs.json`.
The fixture shows the format under `reviewed_pairs`. When pricing, the
scanner fetches reviewed markets by ID and checks that their terms and
outcome tokens are current, that they are still tradable, and that they
close within 30 days.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --reviewed-pairs data/reviewed_pairs.json
```

The review file starts empty. Until a pair passes review and current pricing,
`opportunities.csv` contains only the column headers.

The scanner uses the best available buy price and size on each order book,
venue taker fees, and whole matched contracts. The CSV reports the older of
the two quote times and estimated net return as a percentage. Quotes older
than 60 seconds and unsupported fee models are skipped.

A complete scan with no opportunities writes a header-only CSV. A failed or
incomplete scan exits with status 1 and preserves the previous snapshot.

### Offline example

This command reads synthetic fixture data and writes one example opportunity
to `opportunities.example.csv`.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --fixture tests/fixtures/scan.json
```

On macOS and Linux, use `python` from the activated environment in the
scanner commands above.

## Pregame sports baseline

Run the historical Setka table-tennis evaluation from the repository root.

```powershell
.\.venv\Scripts\python.exe -m src.ML.model
```

On macOS and Linux, use `python` from the activated environment. The evaluator
uses Elo player ratings from prior dates to predict each match. After a
day is complete, its results update the ratings for future days. The output
includes calibration bins, Brier score, log loss, and comparison with constant
50% predictions. Use `--test-start YYYY-MM-DD` to set another holdout start date.

On the bundled 2022 data, the default July 3–8 holdout has 1,598 matches after
one same-name match and four duplicate records were excluded from the full
dataset. The baseline scored 0.2468 Brier and 0.6869 log loss, compared with
0.2500 and 0.6931 for constant 50% predictions. In the 60–80% prediction bin,
the observed win rate was 58.6% across 297 matches. The dashboard shows venue
odds. This historical evaluation does not establish performance on current games.
