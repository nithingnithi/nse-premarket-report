# Experimental global and NSE/BSE market data probes

**Not integrated with production.** Neither probe is called by GitHub Actions, `integrated/collect.py`, the six-signal model, or the Telegram sender. They never place trades. By default, they make **no network calls**.

## Offline tests

```bash
cd poc/market_feeds
python3 -m unittest -v test_yfinance_probe.py
python3 yfinance_probe.py
node nse_bse_probe.mjs
```

## Optional manually authorized live testing

Only run after confirming applicable data-access and redistribution terms.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install 'yfinance>=0.2.65,<1'
python3 yfinance_probe.py --live > yfinance-result.json
npm install --ignore-scripts --no-audit --no-fund
ENABLE_NSE_BSE_PROBE=true node nse_bse_probe.mjs --live > nse-bse-result.json
```

`yfinance` is unofficial and daily candle timestamps may represent session starts, not independently verified official closes. The `nse-bse-api` project invokes NSE/BSE website endpoints and can fail on a cloud runner or be restricted by exchange terms; do not bypass blocks. Its compiled PCR and max-pain output must **not** be used without an independent audit.

`OBSERVED` means only that local checks passed; it is not an exchange-certified price. `STALE`, `UNAVAILABLE` and `DISABLED` never become zeros. Preserve each source and timestamp; validate expiry, units, complete strikes, settlement vs closing price and no future-as-of-cutoff records before any later integration.

To qualify for later production consideration: obtain explicit permission for the intended automated access and redistribution; run tests in the actual GitHub-hosted environment on multiple trading mornings; compare snapshots with official records; document latency and failures. Keep all results outside source control. Production scoring stays unchanged (+3/-3) and new derivatives signals remain shadow-only.
