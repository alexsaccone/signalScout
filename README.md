# SignalScout

## Market dashboard

The [Markets page](https://alexsaccone.github.io/signalScout/) shows estimates
for reviewed contract pairs and documented settlement differences. The
[Games page](https://alexsaccone.github.io/signalScout/games/) shows upcoming
Polymarket moneyline odds.
**Matched pairs** lists all open verified pairs, including pairs without a
profitable quote.
The GitHub Actions workflow refreshes the snapshot roughly every two hours.
Select **Refresh data** to check for the latest published snapshot. The dashboard
shows when it finished checking and keeps the last loaded data if a check fails.
A failed run leaves the previous snapshot online, with its original update
time. Polymarket odds cover games starting within three days.

Every **Publish dashboard** run scans Kalshi, Polymarket International, and
Polymarket US for markets closing within 1,095 days. The **Cross-venue
closing window** filter shows open pairs with later trading closes more than
4 days, 30 days, or a year away. The
**settlement-review** artifact includes `assessment.json` with verified pairs,
cancellation-only differences, proven rule mismatches, and uncertain leads.
The scanner compares normalized market terms and complete governing PDFs.
When both markets reference governing PDFs, a pair can qualify through
matching complete text under supported normalizations or an identical
document. The scanner can also prove specific mismatches between published
Polymarket rules and reviewed versions of Kalshi rulebooks. Incomplete,
unfamiliar, or inconclusive evidence goes to manual review. Resolution checks
run in Python against public venue APIs. A rule that explicitly includes the
full 11:59 p.m. minute can match a rule that ends immediately before midnight
the next day in the same time zone. Ambiguous cutoff wording goes to review
when paired. The
[AI review note](docs/settlement-ai-review.md) describes an optional human-review
pilot for the uncertain cases.

The workflow checks the verified market terms and both governing documents again
before pricing. Automatically verified pairs are included in that run; its
artifact records the evidence. Add confirmed manual reviews to
`data/reviewed_pairs.json` via a pull request to include them on scheduled
runs. A merge triggers a fresh pricing and dashboard run. The dashboard shows
**Cancellation differences** separately for pairs whose only proven difference
is how they pay out when the event is canceled. **Shared events, different
rules** lists documented payout conflicts, such as different deadlines for
the same appointment. These contracts are excluded from opportunity pricing.
If discovery fails, the
workflow can still publish game odds and manually approved opportunities.

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

Live discovery pulls public Kalshi, Polymarket International, and Polymarket US
markets closing within 24 hours by default. Use `--hours 26280` to scan the
same 1,095-day window as the dashboard. The discovery
command checks the dated event, participants, affirmative outcome, and published
settlement terms, including the result source and exceptions. It writes pairs
whose terms it can match to `candidates.json` for manual review. Discovery
recognizes equivalent player-stat thresholds, start times, settlement-source
statements, and common payout wording. It compares unsupported clauses as
written, so the list can still miss equivalent contracts.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --review-candidates candidates.json
```

Compare both contracts' outcomes and settlement rules. Copy confirmed pairs
from `candidates.json` into the JSON array in `data/reviewed_pairs.json`.
The fixture shows the format under `reviewed_pairs`. When pricing, the
scanner fetches reviewed markets by ID and checks that their terms and
outcome tokens are current, that they are still tradable, and that they
close within the 1,095-day supported window.

```powershell
.\.venv\Scripts\python.exe -m src.Arbitrage.ai_filter --reviewed-pairs data/reviewed_pairs.json
```

The review file starts empty. Until a pair passes review and current pricing,
`opportunities.csv` contains only the column headers.

The scanner uses the best available buy price and size on each order book,
venue taker fees, and whole matched contracts. The CSV reports the older of
the two quote times, total estimated net return, and daily ROI. Daily ROI is
the net return percentage divided by the fractional days from the quote to
the later listed trading close. Actual settlement can occur at a different time.
The dashboard sorts opportunities by daily ROI by default. Quotes older
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
