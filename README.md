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

Omit `--fixture` to scan public markets closing in the next 30 days. Use
`--review-candidates candidates.json` to export similarly titled contracts for review.
Copy pairs with equivalent outcomes and settlement rules into a JSON array, then
pass it as `--reviewed-pairs reviewed.json`. Pairs whose listed terms or outcome
tokens change require a fresh review. The fixture shows the file format under
`reviewed_pairs`.
