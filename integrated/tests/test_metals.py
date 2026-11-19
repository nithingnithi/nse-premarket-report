"""Offline gold/silver spot checks; provider responses are synthetic fixtures."""
import datetime as dt
import unittest

from integrated.adapters import metals


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CUTOFF = dt.datetime(2026, 11, 19, 7, 45, tzinfo=IST)
RECEIVED = dt.datetime(2026, 11, 19, 7, 46, tzinfo=IST)


def payload(symbol, **changes):
    return {'symbol': symbol, 'currency': 'USD', 'price': 100.25,
            'updatedAt': '2026-11-19T02:15:30Z', **changes}


class MetalSpotTests(unittest.TestCase):
    def test_fresh_timed_spot_is_display_only(self):
        row = metals.spot_row(payload('XAU'), 'XAU', CUTOFF, RECEIVED)
        self.assertEqual((row['status'], row['value'], row['unit']),
                         ('PROVISIONAL', '100.25', 'USD per troy oz'))
        self.assertEqual(row['asof_IST'], '2026-11-19T07:45:30+05:30')
        self.assertTrue(row['after_cutoff'])
        self.assertIn('excluded', row['reason'])

    def test_invalid_identity_price_or_time_is_unavailable(self):
        cases = [
            (payload('XAU'), 'XAG'),
            (payload('XAG', currency='INR'), 'XAG'),
            (payload('XAG', price=float('nan')), 'XAG'),
            (payload('XAG', price=0), 'XAG'),
            (payload('XAG', updatedAt='2026-11-19T02:15:30'), 'XAG'),
            (payload('XAG', updatedAt='2026-11-19T02:16:10Z'), 'XAG'),
            (payload('XAG', updatedAt='2026-11-19T02:13:00Z'), 'XAG'),
        ]
        for data, symbol in cases:
            with self.subTest(data=data, symbol=symbol):
                self.assertEqual(metals.spot_row(data, symbol, CUTOFF, RECEIVED)['status'],
                                 'UNAVAILABLE')

    def test_late_collection_withholds_even_fresh_spot(self):
        late = dt.datetime(2026, 11, 19, 8, 1, tzinfo=IST)
        data = payload('XAU', updatedAt='2026-11-19T02:30:30Z')
        self.assertIn('after 08:00', metals.spot_row(data, 'XAU', CUTOFF, late)['reason'])

    def test_two_documented_calls_and_provider_failure(self):
        urls = []
        def fetch(url):
            urls.append(url)
            if url.endswith('/XAG'):
                raise RuntimeError('synthetic provider failure')
            return payload('XAU')
        rows = metals.run(CUTOFF, fetch=fetch, clock=lambda: RECEIVED)
        self.assertEqual(urls, ['https://api.gold-api.com/price/XAU',
                                'https://api.gold-api.com/price/XAG'])
        self.assertEqual(rows['GOLD']['status'], 'PROVISIONAL')
        self.assertEqual(rows['SILVER']['status'], 'UNAVAILABLE')
        self.assertNotIn('synthetic provider failure', str(rows))


if __name__ == '__main__':
    unittest.main()
