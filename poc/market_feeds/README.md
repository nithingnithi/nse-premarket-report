# Experimental global and NSE/BSE market data probes

**Not integrated with production.** Offline CI runs fixtures only. A separate manual-only yfinance diagnostic workflow is opt-in and has not been run. Neither probe is called by `integrated/collect.py`, scoring, or Telegram delivery. By default, they make **no network calls**.

## Offline tests

```bash
cd poc/market_feeds
python3 -m pip install -r requirements-offline.txt
python3 -m unittest -v test_yfinance_probe.py
node --test test_chain_validation.mjs
python3 yfinance_probe.py
node nse_bse_probe.mjs
```

## Optional manually authorized live testing

Only run after confirming applicable data-access and redistribution terms.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-live.txt
python3 yfinance_probe.py --live > yfinance-result.json
```

The manual GitHub workflow is `.github/workflows/poc-yfinance-manual-live.yml`. It has `contents: read`, no secrets or schedule, and keeps a bounded summary artifact for one day. Do not run it until live provider testing is authorized. NSE/BSE live calls remain disabled pending access-terms review; do not bypass provider protections.

`yfinance` is unofficial. NYSE, JPX and HKEX daily bars are compared with exchange calendar sessions, including weekends, holidays and early closes. `freshness.json` sets per-exchange session lag and post-close delay. An unfinished bar is marked `LIVE_SNAPSHOT` and never used as a completed close. Brent, gold, FX, dollar index and US yield remain unavailable because their instrument-specific session rules are not validated. The optional NSE/BSE chain validator is metadata-only and returns `PARTIAL` even for a complete-looking chain until coverage, OI units and timestamp meaning are independently confirmed. No PCR, max pain or signals are calculated.

`COMPLETED_CLOSE` means only that the bar date matches a calendar session closed before the cutoff plus configured delay; it is not exchange-certified. `LIVE_SNAPSHOT`, `PARTIAL`, `STALE`, `UNAVAILABLE` and `DISABLED` never become zeros. Provider identity and close semantics still require live verification.

To qualify for later production consideration: obtain explicit permission for the intended automated access and redistribution; run tests in the actual GitHub-hosted environment on multiple trading mornings; compare snapshots with official records; document latency and failures. Keep all results outside source control. Production scoring stays unchanged (+3/-3) and new derivatives signals remain shadow-only.
