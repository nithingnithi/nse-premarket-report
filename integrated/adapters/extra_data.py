"""Optional dated FRED and Alpha Vantage observations. Never affect model signals."""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch_json(url):
    # URLs contain API keys. Never log requests, responses or exception text.
    request = Request(url, headers={'User-Agent': 'NSEMorningReport/1.0'})
    with build_opener(NoRedirect()).open(request, timeout=12) as response:
        body = response.read(256001)
    if len(body) > 256000:
        raise ValueError('Oversize response')
    return json.loads(body)


def unavailable(reason):
    return {'status': 'UNAVAILABLE', 'reason': reason}


def positive(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and number > 0:
            return number
    except (InvalidOperation, TypeError, ValueError):
        pass
    raise ValueError('Missing or invalid positive value')


def fred_yield(payload, cutoff):
    if not isinstance(payload, dict) or not isinstance(payload.get('observations'), list):
        return unavailable('FRED observations schema missing')
    observations = []
    for item in payload['observations']:
        try:
            date = dt.date.fromisoformat(item['date'])
            if date >= cutoff.date():
                continue
            value = positive(item['value'])
            if value >= 30:
                raise ValueError('Implausible yield')
            observations.append((date, value))
        except (KeyError, TypeError, ValueError):
            continue  # FRED uses '.' for missing observations.
    observations.sort(reverse=True)
    if len(observations) < 2 or observations[0][0] == observations[1][0]:
        return unavailable('Two dated FRED yield observations unavailable')
    if (cutoff.date() - observations[0][0]).days > 5:
        return unavailable('FRED yield observation is stale')
    (day, value), (_, previous) = observations[:2]
    return {'status': 'PROVISIONAL', 'value': str(value), 'date': day.isoformat(),
            'previous': str(previous), 'change_bp': str((value - previous) * 100),
            'unit': '%', 'source': 'FRED DGS10',
            'reason': 'Observation date is known; release time is not supplied'}


def adr_quote(payload, symbol, cutoff):
    quote = payload.get('Global Quote') if isinstance(payload, dict) else None
    if not isinstance(quote, dict) or quote.get('01. symbol') != symbol:
        return unavailable('Alpha Vantage ADR quote or symbol missing')
    try:
        date = dt.date.fromisoformat(quote['07. latest trading day'])
        price = positive(quote['05. price'])
        previous = positive(quote['08. previous close'])
    except (KeyError, TypeError, ValueError):
        return unavailable('Alpha Vantage ADR date, price or previous close invalid')
    if date >= cutoff.date():
        return unavailable('ADR observation is after the report cutoff')
    if (cutoff.date() - date).days > 5:
        return unavailable('ADR observation is stale')
    return {'status': 'PROVISIONAL', 'value': str(price), 'date': date.isoformat(),
            'previous': str(previous), 'change_pct': str((price - previous) * 100 / previous),
            'unit': 'USD per ADR', 'source': 'Alpha Vantage GLOBAL_QUOTE',
            'reason': 'End-of-day quote; publication time not supplied'}


def run(cutoff, fred_key, alpha_key, fetch=fetch_json):
    result = {'us_10y': unavailable('FRED_API_KEY missing'), 'adrs': {},
              'metals': {'GOLD': unavailable('Metal response schema and unit not validated'),
                         'SILVER': unavailable('Metal response schema and unit not validated')},
              'requests': {'fred': 0, 'alpha': 0}}
    if fred_key:
        result['requests']['fred'] += 1
        try:
            url = 'https://api.stlouisfed.org/fred/series/observations?' + urlencode({
                'series_id': 'DGS10', 'api_key': fred_key, 'file_type': 'json',
                'sort_order': 'desc', 'limit': 12})
            result['us_10y'] = fred_yield(fetch(url), cutoff)
        except Exception:
            result['us_10y'] = unavailable('FRED request or JSON validation failed')
    for name, symbol in (('Infosys', 'INFY'), ('HDFC Bank', 'HDB'),
                         ('ICICI Bank', 'IBN'), ('Wipro', 'WIT')):
        if not alpha_key:
            result['adrs'][name] = unavailable('ALPHAVANTAGE_API_KEY missing')
            continue
        result['requests']['alpha'] += 1
        try:
            url = 'https://www.alphavantage.co/query?' + urlencode({
                'function': 'GLOBAL_QUOTE', 'symbol': symbol, 'apikey': alpha_key})
            result['adrs'][name] = adr_quote(fetch(url), symbol, cutoff)
        except Exception:
            result['adrs'][name] = unavailable('Alpha Vantage request or JSON validation failed')
    return result
