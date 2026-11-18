"""Synthetic, offline regression cases for the morning PDF data path."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from integrated.collect import global_row, index_daily, option_summary
from integrated.adapters import flows, global_data
from integrated.render import render


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class ReportEnrichmentTests(unittest.TestCase):
    def test_new_bank_nifty_strike_keeps_current_levels_but_withholds_change(self):
        expiry = '2026-11-17'
        def row(strike, side, ident, oi):
            return {'FinInstrmTp': 'IDO', 'XpryDt': expiry, 'StrkPric': str(strike),
                    'OptnTp': side, 'FinInstrmId': ident, 'NewBrdLotQty': 30,
                    'OpnIntrst': oi}
        old = {'date': '2026-11-12', 'data': [{'symbol': 'BANKNIFTY',
            'selected_option_expiry': expiry, 'source_rows': [row(100, 'CE', 1, 20), row(100, 'PE', 2, 30)]}]}
        new = {'date': '2026-11-13', 'data': [{'symbol': 'BANKNIFTY',
            'selected_option_expiry': expiry, 'source_rows': [row(100, 'CE', 1, 25), row(100, 'PE', 2, 35),
                                                               row(110, 'CE', 3, 10), row(110, 'PE', 4, 15)]}]}
        result = option_summary(old, new, 'BANKNIFTY')
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['strikes'], 2)
        self.assertIn('2 added, 0 removed, 0 changed IDs', result['reason'])
        self.assertAlmostEqual(float(result['pcr_current']), 50 / 35)
        self.assertIsNone(result['pcr_previous'])
        self.assertIsNone(result['pcr_direction'])
        self.assertIsNone(result['call_oi_change'])

    def test_global_prior_close_and_after_cutoff_are_distinct(self):
        cutoff = dt.datetime(2026, 11, 16, 7, 45, tzinfo=IST)
        row = global_row('DOW JONES', {'status': 'PASS', 'last_price': 100,
            'last_trade_IST': '2026-11-13T23:59:00+05:30'}, cutoff)
        self.assertEqual((row['status'], row['value']), ('PRIOR QUOTE', 100))
        row = global_row('GIFT NIFTY', {'status': 'PASS', 'last_price': 101,
            'last_trade_IST': '2026-11-16T07:45:56+05:30'}, cutoff)
        self.assertEqual((row['status'], row['value']), ('AFTER CUTOFF', None))
        self.assertIn('after 07:45', row['reason'])
        row = global_row('STALE', {'status': 'PASS', 'last_price': 99,
            'last_trade_IST': '2026-11-09T07:44:00+05:30'}, cutoff)
        self.assertEqual((row['status'], row['value']), ('STALE', None))
    def test_global_change_uses_documented_net_change_not_ohlc_close(self):
        cutoff=dt.datetime(2026,11,18,7,45,tzinfo=IST)
        row=global_row('DOW JONES',{'status':'PASS','last_price':100,
            'ohlc_close_raw':100,'provider_net_change_raw':-5,
            'last_trade_IST':'2026-11-18T01:29:00+05:30'},cutoff)
        self.assertEqual(row['previous_close'],'105')
        self.assertAlmostEqual(float(row['change_pct']),-5/105*100)

    def test_indicator_change_uses_prior_completed_daily_close(self):
        cutoff=dt.datetime(2026,11,18,7,45,tzinfo=IST)
        class FakeAPI:
            auth_failed=False
            def get(self,path,params,version):
                if '/days/1/' in path:
                    return {'candles':[
                        ['2026-11-18T00:00:00+05:30',80,82,79,float('nan'),0,0],
                        ['2026-11-17T00:00:00+05:30',78,81,77,80,0,0]]}
                return {'candles':[['2026-11-18T07:43:00+05:30',81,82,80,81,0,0]]}
        instrument={'instrument_key':'GLOBAL_INDICATOR|BZUSD','name':'Oil (Brent)'}
        result=global_data.indicator_check(FakeAPI(),instrument,cutoff)
        row=global_row('Oil (Brent)',result,cutoff)
        self.assertEqual((row['previous_close'],row['change_pct']),('80','1.25'))

    def test_indicator_selects_last_completed_bar_at_report_cutoff(self):
        cutoff=dt.datetime(2026,11,18,7,45,tzinfo=IST)
        class FakeAPI:
            auth_failed=False
            last_response_at=dt.datetime(2026,11,18,7,55,tzinfo=IST)
            def get(self,path,params,version):
                if '/days/1/' in path:
                    return {'candles':[['2026-11-17T00:00:00+05:30',78,81,77,80,0,0]]}
                return {'candles':[
                    ['2026-11-18T07:54:00+05:30',92,93,91,92,0,0],
                    ['2026-11-18T07:44:00+05:30',90,91,89,90,0,0]]}
        result=global_data.indicator_check(FakeAPI(),{'instrument_key':'GLOBAL_INDICATOR|BZUSD'},cutoff)
        row=global_row('Oil (Brent)',result,cutoff)
        self.assertEqual(result['bar_start_IST'],'2026-11-18T07:44:00+05:30')
        self.assertEqual((row['status'],row['value'],row['change_pct']),('PROVISIONAL',90,'12.5'))

    def test_indicator_ignores_invalid_after_cutoff_but_rejects_invalid_before(self):
        cutoff=dt.datetime(2026,11,18,7,45,tzinfo=IST)
        observed=cutoff+dt.timedelta(minutes=10)
        good=['2026-11-18T07:44:00+05:30',90,91,89,90,0,0]
        bad_later=['2026-11-18T07:54:00+05:30',92,93,91,float('nan'),0,0]
        result=global_data.indicator_candles({'candles':[bad_later,good]},
            {'instrument_key':'GLOBAL_INDICATOR|BZUSD'},observed,cutoff)
        self.assertEqual(result['last_closed_minute_price'],90)
        bad_earlier=['2026-11-18T07:43:00+05:30',90,91,89,float('nan'),0,0]
        with self.assertRaises(global_data.CheckFailure):
            global_data.indicator_candles({'candles':[bad_earlier,good]},
                {'instrument_key':'GLOBAL_INDICATOR|BZUSD'},observed,cutoff)
        with self.assertRaises(global_data.CheckFailure):
            global_data.indicator_candles({'candles':[bad_later]},
                {'instrument_key':'GLOBAL_INDICATOR|BZUSD'},observed,cutoff)

    def test_indicator_invalid_completed_baseline_keeps_change_unavailable(self):
        cutoff=dt.datetime(2026,11,18,7,45,tzinfo=IST)
        class FakeAPI:
            auth_failed=False
            def get(self,path,params,version):
                if '/days/1/' in path:
                    return {'candles':[['2026-11-17T00:00:00+05:30',78,81,77,float('nan'),0,0]]}
                return {'candles':[['2026-11-18T07:43:00+05:30',81,82,80,81,0,0]]}
        result=global_data.indicator_check(FakeAPI(),{'instrument_key':'GLOBAL_INDICATOR|BZUSD'},cutoff)
        row=global_row('Oil (Brent)',result,cutoff)
        self.assertEqual(row['value'],81)
        self.assertNotIn('change_pct',row)
        self.assertIn('daily close',row['change_reason'])

    def test_index_daily_requires_two_exact_completed_sessions(self):
        class FakeAPI:
            def get(self, path, version):
                self.path = path
                self.version = version
                return {'candles': [
                    ['2026-11-13T00:00:00+05:30', 101, 106, 100, 105, 0, 0],
                    ['2026-11-12T00:00:00+05:30', 101, 102, 99, 100, 0, 0]]}
        api = FakeAPI()
        result = index_daily(api, 'NSE_INDEX|Nifty 50', ['2026-11-13', '2026-11-12'],
                             dt.datetime(2026, 11, 16, 7, 45, tzinfo=IST))
        self.assertEqual((result['close'], result['previous_close'], result['change_pct']), ('105', '100', '5'))
        self.assertIn('NSE_INDEX%7CNifty%2050/days/1/2026-11-13/2026-11-12', api.path)
        self.assertEqual(api.version, 'v3')

    def test_pdf_shows_observed_values_without_changing_score(self):
        s = json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        r = json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        s['spot'] = {'NIFTY': {'status': 'PASS', 'close': '105', 'change_pct': '5', 'latest_date': '2026-10-27'}}
        s['vix_daily'] = {'status': 'PASS', 'close': '16', 'change_pct': '-2', 'latest_date': '2026-10-27'}
        s['options']['BANKNIFTY'] = {'status': 'PARTIAL', 'expiry': '2026-10-29', 'pcr_current': '1.25',
            'pcr_previous': None, 'call_walls': ['110'], 'put_walls': ['100'], 'max_pain': ['100'],
            'reason': 'Contract universe changed: 2 added, 0 removed, 0 changed IDs; PCR direction and OI change withheld'}
        s['flows'] = [{'check': 'NIFTY futures', 'status': 'PASS', 'expiry': '2026-10-29',
            'daily_observations': [{'close': '105', 'oi_raw': 120, 'date': '2026-10-27'},
                                   {'close': '100', 'oi_raw': 100, 'date': '2026-10-26'}]},
            {'check': 'FII cash', 'status': 'PASS', 'net_sum_last_3_raw': '6', 'net_sum_last_5_raw': '10',
             'observations': [{'date': f'2026-10-{d}', 'net_raw': '2'} for d in (27, 26, 23, 22, 21)]}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.pdf'
            render(s, r, path)
            reader = PdfReader(path)
            self.assertEqual(len(reader.pages), 2)
            content = '\n'.join(page.extract_text() for page in reader.pages)
            for expected in ('D 16', 'NIFTY spot', 'BANKNIFTY', '1.25', 'Contract universe changed',
                             'OI 120', '10-27:+2', 'Opening picture', 'Insufficient data for final bias'):
                self.assertIn(expected, content)
            self.assertEqual(s['score']['score'], -1)


if __name__ == '__main__':
    unittest.main()
