"""Offline provider-schema and cutoff checks; no network or production secrets."""
import datetime as dt
import unittest

from integrated.adapters import extra_data


CUTOFF = dt.datetime(2026, 11, 19, 7, 45,
                     tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))


class ExtraDataTests(unittest.TestCase):
    def test_fred_dated_yield_and_missing_dot(self):
        row = extra_data.fred_yield({'observations': [
            {'date': '2026-11-19', 'value': '4.3'},
            {'date': '2026-11-18', 'value': '.'},
            {'date': '2026-11-17', 'value': '4.20'},
            {'date': '2026-11-16', 'value': '4.15'}]}, CUTOFF)
        self.assertEqual((row['date'], row['value'], row['change_bp']),
                         ('2026-11-17', '4.20', '5.00'))

    def test_fred_stale_or_invalid_is_unavailable(self):
        for value, date in [('NaN', '2026-11-17'), ('4.2', '2026-11-10')]:
            row = extra_data.fred_yield({'observations': [
                {'date': date, 'value': value},
                {'date': '2026-11-09', 'value': '4.0'}]}, CUTOFF)
            self.assertEqual(row['status'], 'UNAVAILABLE')

    def test_adr_symbol_date_and_previous_close(self):
        quote = {'Global Quote': {'01. symbol': 'INFY', '05. price': '20',
                 '07. latest trading day': '2026-11-18', '08. previous close': '19'}}
        row = extra_data.adr_quote(quote, 'INFY', CUTOFF)
        self.assertEqual(row['status'], 'PROVISIONAL')
        self.assertAlmostEqual(float(row['change_pct']), (20 - 19) * 100 / 19)
        for field, value in [('01. symbol', 'WIT'),
                             ('07. latest trading day', '2026-11-19'),
                             ('05. price', 'NaN'), ('08. previous close', '0')]:
            bad = {'Global Quote': {**quote['Global Quote'], field: value}}
            self.assertEqual(extra_data.adr_quote(bad, 'INFY', CUTOFF)['status'],
                             'UNAVAILABLE')

    def test_missing_keys_do_not_fetch_or_become_zero(self):
        def forbidden(_):
            self.fail('Network fetch attempted')
        row = extra_data.run(CUTOFF, '', '', fetch=forbidden)
        self.assertEqual(row['requests'], {'fred': 0, 'alpha': 0})
        self.assertEqual(row['us_10y']['status'], 'UNAVAILABLE')
        self.assertTrue(all(a['status'] == 'UNAVAILABLE' for a in row['adrs'].values()))

    def test_bounded_requests_and_no_key_in_result(self):
        urls = []
        def fake(url):
            urls.append(url)
            if 'stlouisfed' in url:
                return {'observations': [
                    {'date': '2026-11-18', 'value': '4.2'},
                    {'date': '2026-11-17', 'value': '4.1'}]}
            symbol = url.split('symbol=')[1].split('&')[0]
            return {'Global Quote': {'01. symbol': symbol, '05. price': '20',
                    '07. latest trading day': '2026-11-18',
                    '08. previous close': '19'}}
        row = extra_data.run(CUTOFF, 'fred-secret-fixture', 'alpha-secret-fixture', fetch=fake)
        self.assertEqual(row['requests'], {'fred': 1, 'alpha': 4})
        self.assertEqual(len(urls), 5)
        self.assertNotIn('secret-fixture', repr(row))


if __name__ == '__main__':
    unittest.main()
