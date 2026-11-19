"""Branch-only spot-metals schema probe. No prices or raw replies in logs."""
import re
from integrated.adapters.extra_data import fetch_json

SAFE_KEY = re.compile(r'[A-Za-z0-9 _./%-]{1,48}\Z')


def safe_keys(value):
    if not isinstance(value, dict):
        return []
    return sorted(k for k in value if isinstance(k, str) and SAFE_KEY.fullmatch(k)
                  and not any(word in k.lower() for word in ('key', 'token', 'secret')))[:30]


def shape(value):
    if isinstance(value, dict):
        notice = str(value.get('Information', value.get('Note', ''))).lower()
        category = ('PREMIUM' if 'premium' in notice else
                    'RATE_LIMIT' if any(word in notice for word in ('rate limit', 'requests per day', 'calls per day')) else
                    'KEY_REJECTED' if 'invalid api' in notice else
                    'OTHER_NOTICE' if notice else None)
        nominal = value.get('currency')
        timestamp = value.get('updatedAt')
        return {'type': 'object', 'keys': safe_keys(value),
                'notice_category': category,
                'currency': nominal if isinstance(nominal, str) and re.fullmatch(r'[A-Z]{3}', nominal) else None,
                'symbol': value.get('symbol') if value.get('symbol') in ('XAU','XAG') else None,
                'updatedAt': timestamp if isinstance(timestamp, str) and re.fullmatch(r'[0-9T: +Z.-]{1,35}', timestamp) else None,
                'price_type': type(value.get('price')).__name__,
                'children': {k: safe_keys(value[k]) for k in safe_keys(value)
                             if isinstance(value[k], dict)}}
    if isinstance(value, list):
        return {'type': 'list', 'length': len(value),
                'first_keys': safe_keys(value[0]) if value else []}
    return {'type': type(value).__name__}


def main():
    for symbol in ('XAU', 'XAG'):
        try:
            url = 'https://api.gold-api.com/price/' + symbol
            result = shape(fetch_json(url))
        except Exception:
            result = {'type': 'REQUEST_FAILED'}
        print(symbol, result)
    print('Gold API schema probe finished; no report or Telegram send.')


if __name__ == '__main__':
    main()
