# NSE data access and nselib fallback review

Reviewed on 2026-10-26 for this personal, noncommercial pre-market report.

## Session diagnostic update — 26 October 2026

**Status: not ready for unattended use.** No further unchanged workflow rerun is needed.

- Confirmed: updated GitHub [run 40343842773](https://github.com/nithingnithi/nse-premarket-report/actions/runs/40343842773), job 121645385604, also failed. Bhavcopy failed at `tools/call` in both attempts. CM Market failed at `tools/call` once and `notifications/initialized` once. Initialization therefore succeeded; the 404s occurred later in the session.
- Confirmed: a local run of the same probe reproduced the intermittent failures. Bhavcopy succeeded on its second attempt; CM Market failed both attempts. This is not exclusively a GitHub-runner problem.
- Confirmed: installed the official MCP Python SDK 2.3.0 in an isolated task-local virtual environment and made a bounded live comparison. Both services returned HTTP 200 and assigned a session during initialization, then returned HTTP 404 to subsequent requests carrying that session. The SDK run failed overall for both services; no validated data samples completed. The CM `tools/call` HTTP response was 200, but the following `tools/list` schema request failed with 404. A single successful HTTP response is not a successful end-to-end data check.
- Possible risk: upstream session routing or session-lifetime behavior may be involved. The exact root cause is unverified; these results do not establish that the endpoint URLs are missing, that NSE blocks GitHub, or that the custom client alone caused the failures.
- Local evidence: `outputs/nse-mcp-sdk-comparison-2026-10-26.json`. The HTTP trace records method, status and session-presence booleans, never session identifiers. TLS verification remained enabled. No SDK dependency was added to the GitHub workflow.

Next: retain these MCPs for interactive research with per-request validation; require a reliable, tested source before scheduling the report. Upstox reactivation remains pending, and the nselib fallback remains unevaluated for permitted unattended access. Calculations and PDF work can proceed separately with clearly labelled missing data and synthetic fixtures.

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
