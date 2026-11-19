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

For a live run, install `requirements-live.txt` and omit `--fixture`. The first live run downloads the text matching model.
