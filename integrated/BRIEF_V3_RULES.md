# Morning brief scoring rules

The score still has six slots, each `-1`, `0`, `+1`, or missing (`None`). The
existing `+3` bullish and `-3` bearish boundaries are unchanged. Incomplete
coverage keeps the existing possible-range and provisional-bias rules.

- **Nifty futures build-up:** Compare the same Upstox instrument and expiry on
  the two latest completed NFO sessions. Long build-up and short covering are
  `+1`; short build-up and long unwinding are `-1`; zero price or OI change is
  `0`. Missing, mixed, or invalid bars are `None`.
- **Nifty PCR direction:** The same expiry and comparable contract universe
  must pass archive validation. Rising OI PCR is `+1`, falling is `-1`, and
  unchanged is `0`. Invalid or missing comparisons are `None`.
- **Nifty strike walls:** Require one call wall, one put wall, and the completed
  Nifty spot close strictly between them. Closer put support is `+1`; closer
  call resistance is `-1`. A tie, multiple walls, or missing level is `None`.
  This heuristic overlaps PCR; the report displays both contributions.
- FII futures, FII cash, and DII cash retain their existing mappings. There is
  no DII-offset bonus.

India VIX remains outside the score. Completed-session VIX close `>=20` or
one-day rise `>=8%` means `CAUTION`; otherwise `NORMAL`. Missing daily data
means `UNKNOWN`. The values are configured in `brief_v3.py`.

News is selected from the fixed 12-hour cutoff window. The dated handoff is
the per-date cache: the collector exits before further provider requests when
that date's handoff already exists. The 12-request cap includes retries.
