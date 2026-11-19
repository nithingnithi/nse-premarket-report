"""Branch-only spot-metals schema probe. No prices, keys or raw replies in logs."""
import os
import re
from urllib.parse import urlencode
from integrated.adapters.extra_data import fetch_json

SAFE_KEY = re.compile(r'[A-Za-z0-9 _./%-]{1,48}\Z')


def safe_keys(value):
    if not isinstance(value, dict):
        return []
    return sorted(k for k in value if isinstance(k, str) and SAFE_KEY.fullmatch(k)
                  and not any(word in k.lower() for word in ('key', 'token', 'secret')))[:30]


def shape(value):
    if isinstance(value, dict):
        return {'type': 'object', 'keys': safe_keys(value),
                'children': {k: safe_keys(value[k]) for k in safe_keys(value)
                             if isinstance(value[k], dict)}}
    if isinstance(value, list):
        return {'type': 'list', 'length': len(value),
                'first_keys': safe_keys(value[0]) if value else []}
    return {'type': type(value).__name__}


def main():
    key = os.environ.get('ALPHAVANTAGE_API_KEY', '')
    if not key:
        raise SystemExit('Alpha Vantage secret is absent; no request sent.')
    for symbol in ('GOLD', 'SILVER'):
        try:
            url = 'https://www.alphavantage.co/query?' + urlencode({
                'function': 'GOLD_SILVER_SPOT', 'symbol': symbol, 'apikey': key})
            result = shape(fetch_json(url))
        except Exception:
            result = {'type': 'REQUEST_FAILED'}
        print(symbol, result)
    print('Spot-metal schema probe finished; no report or Telegram send.')


if __name__ == '__main__':
    main()
