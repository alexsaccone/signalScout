TODO:

- Create React website visualization for SignalScout
  - Arbitrage opportunities (~updated every 2 hours)
  - Odds of upcoming games

## Running the market scanner

Use Python 3.12 in a virtual environment. Run the offline smoke test from the repository root.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.Arbitrage.ai_filter --fixture tests/fixtures/scan.json --output opportunities.csv
```

Live discovery searches public markets closing within 24 hours. Use
`--hours` to adjust the discovery window. When pricing a list of reviewed
pairs, the scanner fetches those markets by ID and checks that they are
still tradable and close within 30 days.

```sh
python -m src.Arbitrage.ai_filter --review-candidates candidates.json
python -m src.Arbitrage.ai_filter --reviewed-pairs reviewed.json --output opportunities.csv
```

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
