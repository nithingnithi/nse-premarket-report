# NSE data access and nselib fallback review

Reviewed on 2026-10-26 for this personal, noncommercial pre-market report.

## Confirmed observations

- Both NSE MCPs returned data through the connected Codex plugins. Captured India VIX values were 17.16 in the dated bhavcopy and 17.15 in the last-published cash-market snapshot. The difference is unresolved.
- GitHub Actions [run 40342448094](https://github.com/nithingnithi/nse-premarket-report/actions/runs/40342448094), job 121640483026, failed. The downloaded job logs record HTTP 404 for both MCPs after two attempts each. The original probe did not record the failing protocol step, so these logs do not establish whether initialization, notification or the tool request failed, or why.
- NSE [explicitly documents these two no-auth MCP endpoints](https://www.nseindia.com/nse-mcp) for informational, noncommercial use. Website endpoints are a separate access path.
- The probe's summary inserted diagnostics between table rows, breaking the second row's rendering. The updated probe puts diagnostics after the complete table.
- The original probe did not retain HTTP cookies. The updated probe retains the MCP server's session/affinity cookies and records the failing protocol step for each attempt. Whether cookie handling explains the observed 404s is unverified.

## Requested fallback: nselib

[RuchiTanmay/nselib](https://github.com/RuchiTanmay/nselib) is recorded as a candidate, **not installed, enabled or used to fetch data**.

Reviewed commit: `e3b22ada842193f148dfcb2408ab1d06a44babfe`; `setup.py` declares version 2.5.1. The repository declares Apache-2.0 for its code. This does not grant rights to the underlying provider data.

Files read: README.md, setup.py, requirements.txt, nselib/libutil.py, nselib/derivatives/derivative_data.py and nselib/cash_market/cash_market_data.py. This is a targeted review, not a complete package audit. No nselib tests or live calls were executed.

| Classification | Evidence at reviewed commit | Impact |
| --- | --- | --- |
| Confirmed behavior | [libutil.py:162-182](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/libutil.py#L162-L182): browser-like website cookie warm-up and requests without timeouts. | This helper can wait indefinitely; website access permission must be established separately. |
| Confirmed behavior | [derivative_data.py:709-727](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/derivatives/derivative_data.py#L709-L727) and [755-773](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/derivatives/derivative_data.py#L755-L773): missing option fields caught as KeyError become zero. | Unavailable OI can appear as an observed zero and distort PCR/walls/scoring. |
| Confirmed behavior | [derivative_data.py:575-600](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/derivatives/derivative_data.py#L575-L600) and [678-681](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/derivatives/derivative_data.py#L678-L681): expiry is optional and the parser accepts all returned expiries when omitted. | An adapter must require one explicit, validated expiry for the report. |
| Confirmed behavior | [derivative_data.py:183-235](https://github.com/RuchiTanmay/nselib/blob/e3b22ada842193f148dfcb2408ab1d06a44babfe/nselib/derivatives/derivative_data.py#L183-L235): F&O bhavcopy handling raises on a second 403 but otherwise may return an empty DataFrame for an unsuccessful response. | Empty/error data must never be treated as zero or a valid neutral signal. |
| Possible risk | Both nselib and NSE MCP ultimately depend on NSE. | Another wrapper does not establish an independent data source or reliable fallback. |
| Unverified | No intended-access permission or working GitHub response has been established for nselib's website path. | Do not activate it as an unattended fallback yet. NSE's [website terms, clause 9](https://www.nseindia.com/static/nse-terms-of-use), prohibit systematic automated collection. |

## Required before any fallback is enabled

1. Establish documented permission for the selected access path and intended personal use.
2. Pin the reviewed library and dependencies if adopted; use bounded timeouts and retries and reject HTTP errors, empty data, duplicate contracts and missing required values.
3. Inspect actual responses, dates, timestamps, units, schema and expiry behavior. Validate against the report's previous completed NSE session and 07:45 IST cutoff.
4. Keep unavailable signals missing; preserve the six-signal scoring model and separate VIX caution. Do not silently replace missing values with zero.

Upstox reactivation is still pending. This review does not enable a schedule, change scoring or send Telegram messages.
