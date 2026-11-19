"""Optional dated FRED and Alpha Vantage observations. Never affect model signals."""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
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


ALPHA_RATE_LIMIT = 'Alpha Vantage rate limit reached'
ALPHA_EMPTY_QUOTE = 'Alpha Vantage returned no ADR quote'


def alpha_error(payload):
    if not isinstance(payload, dict):
        return 'Alpha Vantage returned an unexpected response'
    for key in ('Note', 'Information', 'Error Message'):
        message = payload.get(key)
        if not isinstance(message, str) or not message:
            continue
        message = message.lower()
        if any(term in message for term in ('rate limit', 'call frequency', 'requests per day')):
            return ALPHA_RATE_LIMIT
        if any(term in message for term in ('premium', 'subscription', 'entitlement')):
            return 'Alpha Vantage access or subscription required'
        return 'Alpha Vantage rejected or restricted the request'
    return None


def adr_observation(day, price, previous, cutoff, endpoint):
    if day >= cutoff.date():
        return unavailable('ADR observation is after the report cutoff')
    if (cutoff.date() - day).days > 5:
        return unavailable('ADR observation is stale')
    return {'status': 'PROVISIONAL', 'value': str(price), 'date': day.isoformat(),
            'previous': str(previous), 'change_pct': str((price - previous) * 100 / previous),
            'unit': 'USD per ADR', 'source': 'Alpha Vantage ' + endpoint,
            'reason': 'End-of-day observation; publication time not supplied'}


def adr_quote(payload, symbol, cutoff):
    error = alpha_error(payload)
    if error:
        return unavailable(error)
    quote = payload.get('Global Quote')
    if not quote:
        return unavailable(ALPHA_EMPTY_QUOTE)
    if not isinstance(quote, dict) or quote.get('01. symbol') != symbol:
        return unavailable('Alpha Vantage quote symbol does not match ' + symbol)
    try:
        date = dt.date.fromisoformat(quote['07. latest trading day'])
        price = positive(quote['05. price'])
        previous = positive(quote['08. previous close'])
    except (KeyError, TypeError, ValueError):
        return unavailable('Alpha Vantage ADR date, price or previous close invalid')
    return adr_observation(date, price, previous, cutoff, 'GLOBAL_QUOTE')


def adr_daily(payload, symbol, cutoff):
    error = alpha_error(payload)
    if error:
        return unavailable(error)
    metadata, series = payload.get('Meta Data'), payload.get('Time Series (Daily)')
    if not isinstance(series, dict) or not series:
        return unavailable('Alpha Vantage returned no ADR daily bars')
    if (not isinstance(metadata, dict) or metadata.get('2. Symbol') != symbol
            or metadata.get('5. Time Zone') not in ('US/Eastern', 'America/New_York')):
        return unavailable('Alpha Vantage daily symbol or exchange timezone mismatch')
    try:
        dates = sorted((dt.date.fromisoformat(key) for key in series), reverse=True)
        day, prior = [date for date in dates if date < cutoff.date()][:2]
        price = positive(series[day.isoformat()]['4. close'])
        previous = positive(series[prior.isoformat()]['4. close'])
        if (day - prior).days > 5:
            return unavailable('Alpha Vantage ADR previous close is stale')
    except (KeyError, TypeError, ValueError):
        return unavailable('Alpha Vantage ADR needs two valid daily closes')
    return adr_observation(day, price, previous, cutoff, 'TIME_SERIES_DAILY')


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
    def fetch_alpha(symbol, endpoint, normalize, **params):
        result['requests']['alpha'] += 1
        try:
            url = 'https://www.alphavantage.co/query?' + urlencode({
                'function': endpoint, 'symbol': symbol, 'apikey': alpha_key, **params})
            return normalize(fetch(url), symbol, cutoff)
        except HTTPError as exc:
            if exc.code == 429:
                return unavailable(ALPHA_RATE_LIMIT)
            return unavailable(f'Alpha Vantage request failed (HTTP {exc.code})')
        except Exception:
            return unavailable('Alpha Vantage request or JSON validation failed')

    rate_limited = False
    for name, symbol in (('Infosys', 'INFY'), ('HDFC Bank', 'HDB'),
                         ('ICICI Bank', 'IBN'), ('Wipro', 'WIT')):
        if not alpha_key:
            row = unavailable('ALPHAVANTAGE_API_KEY missing')
        elif rate_limited:
            row = unavailable(ALPHA_RATE_LIMIT)
        else:
            row = fetch_alpha(symbol, 'GLOBAL_QUOTE', adr_quote)
            if row['reason'] == ALPHA_EMPTY_QUOTE:
                row = fetch_alpha(symbol, 'TIME_SERIES_DAILY', adr_daily, outputsize='compact')
            rate_limited = row['reason'] == ALPHA_RATE_LIMIT
        result['adrs'][name] = row
    return result
