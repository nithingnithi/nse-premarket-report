"""Read-only experimental yfinance probe; never fetch without --live."""
import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
UTC = dt.timezone.utc
MARKETS = {
    'S&P 500': ('^GSPC', 'NYSE', 'America/New_York'),
    'Nasdaq': ('^IXIC', 'NYSE', 'America/New_York'),
    'Dow Jones': ('^DJI', 'NYSE', 'America/New_York'),
    'Nikkei 225': ('^N225', 'JPX', 'Asia/Tokyo'),
    'Hang Seng': ('^HSI', 'HKEX', 'Asia/Hong_Kong'),
    'Brent crude': ('BZ=F', None, None),
    'Gold futures': ('GC=F', None, None),
    'USD/INR': ('INR=X', None, None),
    'Dollar index': ('DX-Y.NYB', None, None),
    'US 10Y yield': ('^TNX', None, None),
}


def unavailable(name, symbol, reason, status='UNAVAILABLE', **fields):
    return {'name': name, 'symbol': symbol, 'status': status, 'reason': reason, **fields}


def positive(value):
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def normalize(name, symbol, frame, cutoff, schedule, market_tz,
              max_lag_sessions=0, settlement_delay_minutes=30):
    """Classify daily bars using dated exchange sessions, not their start timestamps."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return unavailable(name, symbol, 'Cutoff is not timezone-aware')
    if schedule is None or market_tz is None:
        return unavailable(name, symbol, 'Instrument-specific session calendar not validated')
    if frame is None or getattr(frame, 'empty', True):
        return unavailable(name, symbol, 'No daily bars')
    if not hasattr(frame, 'columns') or list(frame.columns).count('Close') != 1:
        return unavailable(name, symbol, 'Unexpected daily-bar schema')
    source_id = getattr(frame, 'attrs', {}).get('source_id')
    if source_id != symbol:
        return unavailable(name, symbol, 'Missing or mismatched provider symbol')
    try:
        values = list(frame['Close'])
        stamps = list(frame.index)
    except (KeyError, TypeError, ValueError):
        return unavailable(name, symbol, 'Unexpected daily-bar schema')
    if len(values) != len(stamps) or len(stamps) == 0:
        return unavailable(name, symbol, 'Invalid daily-bar row count')
    tz = ZoneInfo(market_tz)
    cutoff_utc = cutoff.astimezone(UTC)
    sessions = {}
    try:
        for day, row in schedule.iterrows():
            session_date = day.date() if hasattr(day, 'date') else day
            close = row['market_close'].to_pydatetime()
            if close.tzinfo is None or close.utcoffset() is None:
                raise ValueError('Unzoned session close')
            sessions[session_date] = close.astimezone(UTC)
    except (AttributeError, KeyError, TypeError, ValueError):
        return unavailable(name, symbol, 'Invalid exchange session schedule')
    if not sessions:
        return unavailable(name, symbol, 'No exchange sessions in calendar window')
    delay = dt.timedelta(minutes=settlement_delay_minutes)
    valid = {}
    for stamp, value in zip(stamps, values):
        stamp = stamp.to_pydatetime() if hasattr(stamp, 'to_pydatetime') else stamp
        if not isinstance(stamp, dt.datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            return unavailable(name, symbol, 'Unzoned or invalid bar timestamp')
        day = stamp.astimezone(tz).date()
        if day not in sessions:
            return unavailable(name, symbol, 'Bar dated on weekend, holiday, or outside calendar window', bar_date=day.isoformat())
        price = positive(value)
        if price is None:
            if sessions[day] + delay > cutoff_utc:
                continue
            return unavailable(name, symbol, 'Missing or invalid close', bar_date=day.isoformat())
        if day in valid:
            return unavailable(name, symbol, 'Duplicate daily bar', bar_date=day.isoformat())
        if stamp.astimezone(UTC) > cutoff_utc:
            continue
        valid[day] = price
    completed = sorted(day for day, close in sessions.items() if close + delay <= cutoff_utc)
    if not completed:
        return unavailable(name, symbol, 'No completed session by cutoff')
    latest = completed[-1]
    completed_bars = [day for day in completed if day in valid]
    active = sorted(day for day in valid if day not in completed and sessions[day] + delay > cutoff_utc)
    if not completed_bars:
        if active:
            day = active[-1]
            return unavailable(name, symbol, 'Daily bar is still in progress', 'LIVE_SNAPSHOT',
                               bar_date=day.isoformat(), value=round(valid[day], 5),
                               caveat='Daily bar may change; timestamp is session date, not quote time')
        return unavailable(name, symbol, 'No completed daily bar')
    day = completed_bars[-1]
    lag = completed.index(latest) - completed.index(day)
    if lag > max_lag_sessions:
        return unavailable(name, symbol, 'Missing newer completed session', 'STALE',
                           bar_date=day.isoformat(), lag_sessions=lag)
    earlier = [date for date in completed if date < day and date in valid]
    if completed.index(day) == 0 or not earlier or earlier[-1] != completed[completed.index(day)-1]:
        return unavailable(name, symbol, 'Previous completed close missing', bar_date=day.isoformat())
    previous = valid[earlier[-1]]
    close = valid[day]
    change_pct = 100 * (close / previous - 1)
    if not math.isfinite(change_pct):
        return unavailable(name, symbol, 'Invalid percent change')
    result = {'name': name, 'symbol': symbol, 'source_id': source_id,
              'source': 'yfinance (unofficial)', 'status': 'COMPLETED_CLOSE',
              'calendar': market_tz, 'bar_date': day.isoformat(),
              'session_close_ist': sessions[day].astimezone(IST).isoformat(),
              'close': round(close, 5), 'previous_close': round(previous, 5),
              'change_pct': round(change_pct, 3), 'lag_sessions': lag}
    if active:
        live_day = active[-1]
        result['live_snapshot'] = {'status': 'LIVE_SNAPSHOT', 'bar_date': live_day.isoformat(),
                                   'value': round(valid[live_day], 5),
                                   'caveat': 'Unfinished daily bar; no quote timestamp'}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--cutoff-ist', help='Timezone-aware ISO timestamp')
    parser.add_argument('--freshness-config', type=Path,
                        default=Path(__file__).with_name('freshness.json'))
    args = parser.parse_args(argv)
    limits = json.loads(args.freshness_config.read_text())
    if any(not isinstance(item.get(key), int) or item[key] < 0
           for item in limits.values()
           for key in ('max_lag_sessions', 'settlement_delay_minutes')):
        parser.error('Freshness limits must be non-negative integers')
    cutoff = dt.datetime.fromisoformat(args.cutoff_ist) if args.cutoff_ist else dt.datetime.now(IST)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        parser.error('--cutoff-ist must include a timezone offset')
    cutoff = cutoff.astimezone(IST)
    if not args.live:
        print(json.dumps({'status': 'DISABLED', 'reason': 'Pass --live for network requests',
                          'data': [], 'cutoff_ist': cutoff.isoformat()}))
        return 0
    try:
        import pandas_market_calendars as mcal
        import yfinance as yf
    except ImportError:
        print('Install PoC dependencies for --live', file=sys.stderr)
        return 2
    rows = []
    for name, (symbol, calendar_name, market_tz) in MARKETS.items():
        if calendar_name is None:
            rows.append(unavailable(name, symbol, 'Instrument-specific session calendar not validated'))
            continue
        try:
            calendar = mcal.get_calendar(calendar_name)
            local_day = cutoff.astimezone(ZoneInfo(market_tz)).date()
            schedule = calendar.schedule(local_day - dt.timedelta(days=45), local_day)
            ticker = yf.Ticker(symbol)
            frame = ticker.history(period='1mo', interval='1d', timeout=12, auto_adjust=False)
            frame.attrs['source_id'] = ticker.history_metadata.get('symbol')
            config = limits[calendar_name]
            rows.append(normalize(name, symbol, frame, cutoff, schedule, market_tz,
                                  config['max_lag_sessions'], config['settlement_delay_minutes']))
        except Exception:
            rows.append(unavailable(name, symbol, 'Provider or calendar request failed'))
    print(json.dumps({'status': 'PROBE_ONLY', 'cutoff_ist': cutoff.isoformat(),
                      'data': rows, 'production_scoring_enabled': False}, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
