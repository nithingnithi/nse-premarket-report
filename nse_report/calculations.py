"""Pure calculations on explicitly normalized inputs; no live policy defaults.

Metadata checks enforce internal consistency, not source authenticity, freshness,
permission, OI baseline meaning or independently reconciled units. Adapters must
validate those before supplying inputs. MissingData must become an unavailable
signal, never zero. Ratios use Fraction to avoid rounded direction comparisons.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction


class DataError(ValueError):
    """Malformed, conflicting or inconsistent input."""


class MissingData(DataError):
    """A required observation is absent."""


def number(value, name, *, positive=False, integer=False):
    if value is None:
        raise MissingData(f"Missing {name}")
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise DataError(f"Invalid {name}: use int, decimal string or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise DataError(f"Invalid {name}") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise DataError(f"Invalid {name}")
    if integer and result != result.to_integral_value():
        raise DataError(f"Nonintegral {name}")
    return int(result) if integer else result


def iso_day(value):
    if value is None:
        raise MissingData("Missing date")
    if not isinstance(value, str):
        raise DataError("Expected ISO date")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise DataError("Invalid date") from None
    if result.isoformat() != value:
        raise DataError("Expected YYYY-MM-DD")
    return result


def text_id(value):
    if value is None or value == "":
        raise MissingData("Missing identity/unit")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DataError("Invalid identity/unit")
    return value


def session_pair(latest, previous):
    if iso_day(previous) >= iso_day(latest):
        raise DataError("Expected two distinct sessions, latest first")


@dataclass(frozen=True)
class FutureBar:
    instrument: str
    expiry: str
    session: str
    close: object
    oi: object
    unit: str
    provider: str


def futures_build_up(current, previous, *, latest_session, previous_session):
    session_pair(latest_session, previous_session)
    for bar, expected in ((current, latest_session), (previous, previous_session)):
        if bar.session != expected:
            raise DataError("Unexpected futures session")
        if iso_day(bar.expiry) < iso_day(bar.session):
            raise DataError("Observation after contract expiry")
        for value in (bar.instrument, bar.unit, bar.provider):
            text_id(value)
    if (current.instrument, current.expiry, current.unit, current.provider) != (
        previous.instrument, previous.expiry, previous.unit, previous.provider
    ):
        raise DataError("Mixed futures contracts, units or providers")
    price_change = number(current.close, "close", positive=True) - number(
        previous.close, "previous close", positive=True)
    old_oi = number(previous.oi, "previous OI", integer=True)
    oi_change = number(current.oi, "OI", integer=True) - old_oi
    kind = "NO_DIRECTIONAL_BUILD_UP"
    if price_change and oi_change:
        kind = {
            (True, True): "LONG_BUILD_UP", (False, True): "SHORT_BUILD_UP",
            (True, False): "SHORT_COVERING", (False, False): "LONG_UNWINDING",
        }[(price_change > 0, oi_change > 0)]
    return {"classification": kind, "price_change": price_change,
            "oi_change": oi_change,
            "oi_change_pct": Fraction(100 * oi_change, old_oi) if old_oi else None,
            "oi_unit": current.unit}


@dataclass(frozen=True)
class OptionRow:
    strike: object
    call_oi: object
    put_oi: object


@dataclass(frozen=True)
class OptionChain:
    underlying: str
    expiry: str
    session: str
    unit: str
    provider: str
    rows: tuple


def validated_chain(chain, expected_strikes):
    for value in (chain.underlying, chain.unit, chain.provider):
        text_id(value)
    if iso_day(chain.session) > iso_day(chain.expiry):
        raise DataError("Chain session after expiry")
    expected = [number(k, "expected strike", positive=True) for k in expected_strikes]
    if not expected:
        raise MissingData("No validated contract universe")
    if len(set(expected)) != len(expected):
        raise DataError("Duplicate expected strikes")
    rows = {}
    for row in chain.rows:
        strike = number(row.strike, "strike", positive=True)
        if strike in rows:
            raise DataError("Duplicate option strike")
        rows[strike] = (number(row.call_oi, "call OI", integer=True),
                        number(row.put_oi, "put OI", integer=True))
    if set(rows) - set(expected):
        raise DataError("Unexpected option strikes")
    if set(expected) - set(rows):
        raise MissingData("Incomplete option universe")
    return dict(sorted(rows.items()))


def option_metrics(chain, *, expected_strikes):
    rows = validated_chain(chain, expected_strikes)
    calls, puts = sum(v[0] for v in rows.values()), sum(v[1] for v in rows.values())
    max_call, max_put = max(v[0] for v in rows.values()), max(v[1] for v in rows.values())
    payouts = {s: sum(c * max(s - k, 0) + p * max(k - s, 0)
                      for k, (c, p) in rows.items()) for s in rows}
    minimum = min(payouts.values())
    return {
        "call_oi": calls, "put_oi": puts,
        "pcr": Fraction(puts, calls) if calls else None,
        "call_walls": tuple(k for k, v in rows.items() if max_call and v[0] == max_call),
        "put_walls": tuple(k for k, v in rows.items() if max_put and v[1] == max_put),
        "max_pain_strikes": tuple(k for k, v in payouts.items()
                                  if calls + puts and v == minimum),
        "payout_by_strike": payouts,
        "payout_unit": f"index points x {chain.unit}",
    }


def compare_options(current, previous, *, expected_strikes,
                    latest_session, previous_session):
    session_pair(latest_session, previous_session)
    if (current.session, previous.session) != (latest_session, previous_session):
        raise DataError("Unexpected option baseline sessions")
    if (current.underlying, current.expiry, current.unit, current.provider) != (
        previous.underlying, previous.expiry, previous.unit, previous.provider
    ):
        raise DataError("Mixed option underlying, expiry, units or providers")
    # Materialize an iterable once so both snapshots use the same universe.
    universe = tuple(expected_strikes)
    new = option_metrics(current, expected_strikes=universe)
    old = option_metrics(previous, expected_strikes=universe)
    new_rows, old_rows = validated_chain(current, universe), validated_chain(previous, universe)
    delta = new["pcr"] - old["pcr"] if new["pcr"] is not None and old["pcr"] is not None else None
    return {"current": new, "previous": old, "pcr_change": delta,
            "pcr_direction": None if delta is None else (
                "UP" if delta > 0 else "DOWN" if delta < 0 else "UNCHANGED"),
            "call_oi_change": new["call_oi"] - old["call_oi"],
            "put_oi_change": new["put_oi"] - old["put_oi"],
            "strike_oi_changes": {k: (new_rows[k][0] - old_rows[k][0],
                                      new_rows[k][1] - old_rows[k][1]) for k in new_rows}}


def fii_positions(long_count, short_count, *, session, expected_session, unit):
    iso_day(session)
    iso_day(expected_session)
    text_id(unit)
    if session != expected_session:
        raise DataError("Unexpected FII positions session")
    longs = number(long_count, "FII longs", integer=True)
    shorts = number(short_count, "FII shorts", integer=True)
    return {"long": longs, "short": shorts, "net": longs - shorts,
            "long_short_ratio": Fraction(longs, shorts) if shorts else None,
            "long_share": Fraction(longs, longs + shorts) if longs + shorts else None,
            "unit": unit, "scope": "aggregate index futures"}


@dataclass(frozen=True)
class CashRow:
    participant: str
    session: str
    buy: object
    sell: object
    unit: str
    provider: str


def cash_trends(rows, *, participant, expected_sessions, unit, provider):
    if participant not in ("FII", "DII"):
        raise DataError("Expected FII or DII")
    text_id(unit)
    text_id(provider)
    sessions = tuple(expected_sessions)
    days = [iso_day(s) for s in sessions]
    if len(days) != 5 or days != sorted(set(days), reverse=True):
        raise DataError("Require five distinct sessions, latest first")
    by_day = {}
    for row in rows:
        iso_day(row.session)
        if row.session in by_day:
            raise DataError("Duplicate cash session")
        if (row.participant, row.unit, row.provider) != (participant, unit, provider):
            raise DataError("Mixed cash participant, unit or provider")
        by_day[row.session] = number(row.buy, "buy") - number(row.sell, "sell")
    if set(by_day) - set(sessions):
        raise DataError("Unexpected cash sessions; select the required five explicitly")
    if set(sessions) - set(by_day):
        raise MissingData("Missing required cash sessions")
    return {"daily_net": {s: by_day[s] for s in sessions},
            "net_3_sessions": sum(by_day[s] for s in sessions[:3]),
            "net_5_sessions": sum(by_day[s] for s in sessions), "unit": unit}


SIGNALS = ("futures_build_up", "pcr_direction", "strike_walls", "fii_futures", "fii_cash", "dii_cash")


def category(score, *, bullish_threshold=3, bearish_threshold=-3):
    if (type(bullish_threshold) is not int or type(bearish_threshold) is not int
            or bullish_threshold != 3 or bearish_threshold != -3):
        raise DataError("Six-signal thresholds must remain +3/-3")
    return "BULLISH" if score >= bullish_threshold else "BEARISH" if score <= bearish_threshold else "NEUTRAL"


def score_summary(signals, *, bullish_threshold=3, bearish_threshold=-3):
    """Aggregate explicitly supplied points; does not map data to points."""
    if set(signals) - set(SIGNALS):
        raise DataError("Unknown signal; VIX is separate")
    values = {key: signals.get(key) for key in SIGNALS}
    if any(v is not None and (type(v) is not int or v not in (-1, 0, 1))
           for v in values.values()):
        raise DataError("Signal must be -1, 0, +1 or None")
    missing = tuple(k for k, v in values.items() if v is None)
    raw = sum(v for v in values.values() if v is not None)
    m = len(missing)
    low, high = raw - m, raw + m
    possible = tuple(c for c in ("BEARISH", "NEUTRAL", "BULLISH")
                     if any(category(s, bullish_threshold=bullish_threshold, bearish_threshold=bearish_threshold) == c for s in range(low, high + 1)))
    if len(possible) > 1:
        bias = "INSUFFICIENT DATA TO ASSIGN FINAL BIAS"
    else:
        bias = ("PROVISIONAL " if m else "") + possible[0]
    return {"signals": values, "score": raw, "available": 6 - m, "total": 6,
            "missing": missing, "missing_count": m, "score_range": (low, high),
            "possible_categories": possible, "bias": bias}


def vix_caution(value, *, threshold):
    limit = number(threshold, "explicit VIX threshold", positive=True)
    if value is None:
        return "UNKNOWN"
    return "CAUTION" if number(value, "VIX", positive=True) >= limit else "NO_THRESHOLD_FLAG"


def select_expiry(expiries, *, report_date, include_report_date):
    """Require an explicit expiry-day choice; never infer weekly labels."""
    if type(include_report_date) is not bool:
        raise DataError("Explicit expiry-day policy required")
    day = iso_day(report_date)
    dates = sorted({iso_day(e) for e in expiries})
    eligible = [e for e in dates if e > day or (include_report_date and e == day)]
    if not eligible:
        raise MissingData("No eligible provider expiry")
    return eligible[0].isoformat()
