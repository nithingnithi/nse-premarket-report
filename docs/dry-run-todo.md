# Captured-data dry run and remaining work

This first replay uses evidence captured 26 Oct evening / 27 Oct early morning,
with report date 27 Oct 2026, cutoff 07:45 IST and target delivery 08:00 IST.
It is intentionally partial. It is not a live collection or a scheduler test.
Codex reviewed the saved evidence in the current chat; there is no unattended
model API call. No new key, paid AI service or Marketaux request was used.

## This trial

- Python recomputes futures changes, build-up, aggregate FII positions, raw cash
  sums and the missing-aware score from the committed saved snapshot.
- Draft mapping for this trial: Nifty short covering +1; aggregate FII net short
  -1. PCR, strike walls and both cash signals are unavailable. Score 0, n=2/6,
  range [-4,+4]: INSUFFICIENT DATA TO ASSIGN FINAL BIAS.
- Cash stays raw because the monetary scale is unresolved. No crore conversion.
- India VIX 17.16 is retained as a captured observation; caution flag UNKNOWN
  because freshness and timestamp meaning are not independently validated.
- The saved option probe only retained row counts, not per-strike OI data. No PCR,
  OI walls, support/resistance or max-pain value can be reconstructed from it.
- Saved news belongs to a different 12-hour window; it is excluded, not presented
  as current news. Required window is (26 Oct 19:45, 27 Oct 07:45] IST.
- Global values are old snapshots with original provider timestamps; US values
  are not labelled final closes. No cross-asset causal or opening-gap claim.
- Source links and calendar qualifications are retained in the two-page PDF.
- GitHub's delivery workflow embeds this visually reviewed PDF and verifies its
  SHA-256 before upload and after a Telegram verification download. It does not
  recollect data, call an AI model or regenerate the report in GitHub yet.

To reproduce locally with the report dependencies available:

`python3 -m nse_report.dry_run data/dry-run/2026-10-27.json output/pdf/nse-morning-dry-run-2026-10-27.pdf`

`python3 -m unittest discover -s tests -v`

The renderer is specific to this labelled dated replay, not a generic daily
report engine. Its report copy must not be reused unchanged for another date.

## To do before unattended production

| Priority | Pending item | Treatment in this run |
|---|---|---|
| High | Choose and validate unattended AI execution without silently adding cost. No model/API key is configured by this work. | Codex review in this chat only. |
| High | Integrate validated probes into one snapshot with cutoff, retrieval time, session identity, row provenance and per-field errors. Never leak observations after cutoff. | Saved evidence replay. |
| High | Retain complete current/previous option rows, exact expiry/underlying/contract inventory; prove prev_oi baseline session and whole-chain freshness. | PCR/walls/OI change/max pain N/A. |
| High | Independently reconcile raw OI count/lot semantics and FII/DII monetary scale with an authoritative same-date source. | Raw units, no inferred conversion; cash points missing. |
| High | Reconcile provider NSE/NFO sessions with current exchange calendars, including special sessions and holidays; do not rely on weekday-only scheduling. | Provider-declared dates only. |
| High | Confirm live scoring policy, Nifty/Bank Nifty scope, expiry-day/roll handling and separate VIX threshold. Draft mapping is trial-only. | No production scoring enabled. |
| High | Prove fresh 07:45 IST collection, final US-session values, reliable GIFT instrument identity, global benchmark units and VIX timestamp semantics. | Captured global values; VIX UNKNOWN. |
| High | Connect fresh 12-hour news with UTC/IST filtering, quota-aware requests, partial failure retention and publisher timestamps/links. Review relevance and syndicated duplication. | News N/A for this window. |
| High | Add persistent delivery idempotency across separate runs, not just concurrency. Do not resend on an uncertain sendDocument outcome. | One push-triggered trial; reruns blocked by attempt guard. |
| High | Connect Codex Schedule only after validating local execution/credentials and PDF delivery; target 08:00 IST is not a timing guarantee. | No recurring schedule activated. |
| Medium | Renew/revalidate reviewed Indian/Fed calendar snapshots before 02 Nov; expand selected calendar coverage. | Partial reviewed calendar; missing times/consensus N/A. |
| Medium | Automate PDF generation in the delivery runtime and verify dynamic content, two-page layout, bias consistency and safe escaping. | Locally generated and visually reviewed PDF embedded in GitHub. |
| Medium | Add hashed dependency lock/transitive pins and SHA-pinned actions if introducing installs/actions. | Existing bundled ReportLab 4.4.9 and pypdf 6.10.0 used locally; no install/action in delivery job. |
| Low | Revisit NSE MCP session failures only after a material change. Review nselib access permission/timeout/zero-fill issues before considering it. | Neither used. |

No API failure is hidden as a successful data check. A successful delivery result
means only that Telegram accepted the PDF and a downloaded copy matched its hash;
it does not establish data readiness, user readability or morning delivery timing.
