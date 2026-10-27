# Step 21: calculations and proposed report policy

Status: **math implemented; directional mappings below await user approval**.
No provider adapter, report, schedule or Telegram delivery calls these helpers yet.
The existing manual access probes are unchanged. Target remains 07:45 IST cutoff,
08:00 IST delivery, Telegram only, personal use and free data.

## Implemented calculations

`nse_report/calculations.py` is standard-library-only. Run the synthetic suite from
the repository root with `python3 -m unittest discover -s tests -v`.
All fixtures are invented, including their dates and contract identifiers.

| Calculation | Definition and guard |
|---|---|
| Futures build-up | Same provider, contract, expiry, unit and two explicit completed sessions. Price/OI changes classify the four combinations; either unchanged means no directional classification. |
| PCR | Sum put OI / sum call OI for one underlying, one expiry and a complete explicit contract universe. Zero call denominator yields N/A, not zero or infinity. |
| OI change / PCR direction | Exact same expiry, underlying, universe, provider and unit across the two required sessions. Changes are current minus previous. Ratios use exact fractions. |
| OI walls | All strikes tied for highest call/put OI retained. An all-zero side has no meaningful wall. This does not establish option writing or reliable support/resistance. |
| Max pain | At each listed candidate strike S: sum(callOI(K) × max(S−K,0) + putOI(K) × max(K−S,0)). Keep all minimizing listed strikes. All-zero OI yields N/A. No premium, lot conversion or price prediction. |
| FII index-futures | Net = long−short; ratio explicitly long/short, N/A if short=0. Long share = long/(long+short), N/A if both=0. Aggregate index futures, not Nifty-only positions. |
| FII/DII cash | Buy−sell daily; sums over exactly the latest three/five supplied completed NSE sessions. Require all five unique sessions, consistent participant/provider/unit. Preserve raw units. |
| Six-signal aggregator | Only explicit −1/0/+1/None for the six named signals. Zero is available neutral; None is missing. No weights, bonus or seventh signal. |

Missing required values raise `MissingData`; invalid or conflicting observations
raise `DataError`. A future adapter must retain the reason and render N/A; it must
never catch either error and replace it with zero. Current option metrics can be
calculated independently when the previous-session comparison is unavailable.
Duplicates fail even if identical; no arbitrary first-row selection.

Normalized observations require declared provenance and explicit session dates.
These checks establish internal consistency only. They do **not** authenticate a
source, establish access permission, prove freshness or validate the meaning of
provider fields. The adapter must check the cutoff, expected trading calendar,
actual row contract identities, OI baseline dates and source metadata first.
Common OptionChain metadata must come from validated row identities, not merely
be copied over mixed raw rows. Parse decimal JSON numbers as Decimal or exact
strings; floats and booleans are rejected by numeric helpers.

## Synthetic worked examples — not market observations

| Input | Hand result |
|---|---|
| Previous price=100, OI=1,000; current 105/1,100 | Δprice +5, ΔOI +100: long build-up |
| Same previous; current 95/1,100 | −5/+100: short build-up |
| Same previous; current 105/900 | +5/−100: short covering |
| Same previous; current 95/900 | −5/−100: long unwinding |
| Strikes 100/110/120; calls 10/20/10; puts 30/20/10 | Calls=40, puts=60, PCR=1.5; call wall=110, put wall=100 |
| Previous calls 8/18/9, puts 25/18/7, same strikes/expiry | Calls=35, puts=50, PCR=10/7. ΔcallOI=+5, ΔputOI=+10, ΔPCR=1/14 (up). Per-strike changes: calls +2/+2/+1; puts +5/+2/+3. |
| Same current chain; candidate settlement 100/110/120 | Payout 400/200/400 in points × supplied OI units; max pain=110 |
| FII long=120, short=80 | Net=+40, long/short=1.5, long share=60% |
| FII cash nets, latest first: −10,+20,−5,+15,−30 | Three sessions +5; five sessions −10, raw amount units |
| DII cash nets, latest first: +10,−20,+5,−15,+30 | Three sessions −5; five sessions +10, raw amount units |
| Points +1,+1,+1,0,0,missing | S=+3, n=5/6, m=1, range [+2,+4]: INSUFFICIENT DATA TO ASSIGN FINAL BIAS |
| Points +1,+1,+1,+1,+1,missing | S=+5, n=5/6, range [+4,+6]: PROVISIONAL BULLISH |
| Points 0,0,0,0,missing,missing | S=0, n=4/6, range [−2,+2]: PROVISIONAL NEUTRAL |

The test suite covers these examples, missing/invalid values, zero denominators,
tied walls/max pain, duplicate rows, mixed metadata, stale declared sessions,
explicit expiry-day selection and all 4,096 combinations of six values chosen
from −1/0/+1/missing. An independent exhaustive completion oracle verifies every
partial-score range/category. Synthetic success does not validate live data.

## Suggested changes — approval required before implementation

These mappings fill gaps in the requested model; they are **proposals**, not
validated predictive rules. The helpers do not implement these mappings.

| Signal | Proposed +1 | Proposed −1 | Proposed 0 / unavailable |
|---|---|---|---|
| Futures build-up | Long build-up or short covering | Short build-up or long unwinding | Either price or OI unchanged → 0; absent/invalid comparison → missing |
| PCR direction | PCR rising vs previous completed session | PCR falling | Unchanged → 0; unverified baseline, incomplete universe or zero denominator → missing |
| Strike walls | Both unique highest call and put OI strikes move up | Both move down | Other clear movement → 0; ties, absent wall or unavailable baseline → missing |
| FII futures | Latest aggregate index-futures net long−short >0 | Net <0 | Exactly zero → 0; unavailable positions → missing; L/S ratio shown as context |
| FII cash | Five-session net sum >0 | Sum <0 | Exactly zero → 0; incomplete five-session window → missing |
| DII cash | Five-session net sum >0 | Sum <0 | Exactly zero → 0; incomplete five-session window → missing |

Three-session cash sums remain context, not extra points. A positive DII point and
a negative FII point cancel within this equal-point model, regardless of rupee
magnitude; do not claim DII purchases absorbed FII sales. No DII-offset bonus.
PCR and strike-wall movement share the same option OI and may double-count it.
Futures build-up and aggregate FII positioning can overlap economically too.
Six available signals therefore do not imply six independent confirmations or
calibrated confidence. Rising PCR can also reflect hedging; this sign mapping is
a heuristic and needs later evaluation, not causal language in the report.

Proposed scope: **Nifty gets the six-signal headline; Bank Nifty metrics are
context**, without inventing a combined index score. A later Bank Nifty score
would reuse broad institutional flows and must not be called independent evidence.

Proposed expiry policy: choose the nearest actual provider expiry **on or after
the report trading date**, including/flagging expiry day; use the same selected
contract for both historical sessions. Roll after expiry, never compare different
contracts across the roll. Select futures and options separately from their own
validated inventories. Do not infer expiry from a weekday or label Bank Nifty as
weekly. The existing probes' strictly-after-today selection remains unchanged
until this policy is approved and adapted for report cutoff dates.

Proposed separate VIX flag: **CAUTION at India VIX ≥20**, UNKNOWN when missing or
stale; below threshold says only NO_THRESHOLD_FLAG, never "safe". Threshold 20 is
an uncalibrated proposed heuristic, not an exchange rule. The helper requires an
explicit threshold and cannot change the six-point score.

Approved original aggregation remains S≥+3 bullish, S≤−3 bearish, otherwise
neutral. Display raw S, n/6, missing names and range [S−m,S+m]. If the range crosses
categories, show INSUFFICIENT DATA TO ASSIGN FINAL BIAS. Otherwise with missing
signals prefix PROVISIONAL. With all inputs present, show bias plus availability;
do not label that high confidence solely because n=6.

## Unverified before live integration

- Independent NSE calendar reconciliation and expected session selection at cutoff.
- OI units, option prev_oi session meaning and whole-chain snapshot freshness.
- Cash amount scale; no inferred crore conversion. Same-unit signs require no
  scaling, but do not excuse unresolved units in printed monetary amounts.
- Source access at 07:45 IST, after provider retention updates/rollovers, and news
  quota availability. Reviewed calendar snapshots still need timely renewal.
- End-to-end PDF layout, actual report delivery and scheduler execution. No morning
  report is deployed or enabled by this step.

## Primary references consulted

- [NSE current equity-derivatives contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications): use current contract inventory/specifications; old weekly pages can be stale.
- [Upstox explanation of price/OI classifications](https://upstox.com/learning-center/share-market/how-to-use-open-interest-for-intraday-trading-complete-guide/article-1858/): conventional build-up labels, not proof of future price direction.
- [Upstox API documentation](https://upstox.com/developer/api-documentation/): provider schemas reviewed in prior access steps; no additional live call or permission claim from this math suite.

User decision needed: accept or revise the proposed six mappings, Nifty headline
scope, expiry-day inclusion and separate VIX threshold before live scoring/PDF work.
