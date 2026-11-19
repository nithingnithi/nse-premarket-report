"""Dated, display-only gold and silver spot references from Gold API."""
import datetime as dt
from zoneinfo import ZoneInfo
from integrated.adapters.extra_data import fetch_json, positive, unavailable


IST = ZoneInfo('Asia/Kolkata')
SYMBOLS = {'GOLD': 'XAU', 'SILVER': 'XAG'}
MAX_AGE = dt.timedelta(seconds=90)


def live_spot_row(payload, symbol, received_at):
    """Validate a current quote against the time it was received."""
    if not isinstance(payload, dict) or payload.get('symbol') != symbol:
        return unavailable('Gold API spot symbol or response schema missing')
    if payload.get('currency') != 'USD':
        return unavailable('Gold API spot currency is not USD')
    try:
        value = positive(payload['price'])
        observed = dt.datetime.fromisoformat(payload['updatedAt'].replace('Z', '+00:00'))
        if (observed.tzinfo is None or received_at.tzinfo is None or
                observed.utcoffset() != dt.timedelta(0)):
            raise ValueError('Timezone missing')
    except (KeyError, AttributeError, TypeError, ValueError):
        return unavailable('Gold API spot price or UTC timestamp invalid')
    age = received_at - observed
    if age < dt.timedelta(0):
        return unavailable('Spot timestamp is after request completion')
    if age > MAX_AGE:
        return unavailable('Gold API spot observation is over 90 seconds old')
    return {'status': 'PROVISIONAL', 'value': str(value),
            'asof_IST': observed.astimezone(IST).isoformat(),
            'unit': 'USD per troy oz', 'source': 'Gold API',
            'reason': 'Timed spot reference, excluded from the six-signal score'}


def spot_row(payload, symbol, cutoff, received_at):
    if cutoff.tzinfo is None or received_at.tzinfo is None:
        return unavailable('Gold API spot price or UTC timestamp invalid')
    if received_at > cutoff + dt.timedelta(minutes=15):
        return unavailable('Spot fetched after 08:00 IST report window')
    row = live_spot_row(payload, symbol, received_at)
    if row['status'] == 'PROVISIONAL':
        row['after_cutoff'] = dt.datetime.fromisoformat(row['asof_IST']) > cutoff
    return row


def run(cutoff, fetch=fetch_json, clock=None):
    if clock is None:
        clock = lambda: dt.datetime.now(dt.timezone.utc)
    rows = {}
    for name, symbol in SYMBOLS.items():
        if clock() > cutoff + dt.timedelta(minutes=15):
            rows[name] = unavailable('Spot fetched after 08:00 IST report window')
            continue
        try:
            payload = fetch('https://api.gold-api.com/price/' + symbol)
            rows[name] = spot_row(payload, symbol, cutoff, clock())
        except Exception:
            rows[name] = unavailable('Gold API spot request or JSON validation failed')
    return rows
