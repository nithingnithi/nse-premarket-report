import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stdout
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import yfinance_probe as probe

IST = ZoneInfo('Asia/Kolkata')
NY = ZoneInfo('America/New_York')
JP = ZoneInfo('Asia/Tokyo')


def frame(symbol, rows):
    result = pd.DataFrame({'Close': [price for _, price in rows]},
                          index=pd.DatetimeIndex([stamp for stamp, _ in rows]))
    result.attrs['source_id'] = symbol
    return result


def schedule(market, start, end):
    return mcal.get_calendar(market).schedule(start, end)


class ProbeTests(unittest.TestCase):
    def test_disabled_default(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(probe.main(['--cutoff-ist', '2026-10-30T07:45:00+05:30']), 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'DISABLED')

    def test_completed_close_and_change(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 28, tzinfo=NY), 100.0),
                                (dt.datetime(2026, 10, 29, tzinfo=NY), 110.0)])
        row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                              schedule('NYSE', '2026-10-27', '2026-10-30'), 'America/New_York')
        self.assertEqual(row['status'], 'COMPLETED_CLOSE')
        self.assertEqual(row['change_pct'], 10)
        self.assertEqual(row['bar_date'], '2026-10-29')

    def test_unfinished_bar_is_live_snapshot_not_close(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        bars = frame('^N225', [(dt.datetime(2026, 10, 28, tzinfo=JP), 100.0),
                                (dt.datetime(2026, 10, 29, tzinfo=JP), 110.0),
                                (dt.datetime(2026, 10, 30, tzinfo=JP), 999.0)])
        row = probe.normalize('Nikkei 225', '^N225', bars, cutoff,
                              schedule('JPX', '2026-10-27', '2026-10-30'), 'Asia/Tokyo')
        self.assertEqual(row['status'], 'COMPLETED_CLOSE')
        self.assertEqual(row['close'], 110)
        self.assertEqual(row['live_snapshot']['value'], 999)

    def test_weekend_uses_friday_session(self):
        cutoff = dt.datetime(2026, 10, 31, 12, 0, tzinfo=IST)
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 29, tzinfo=NY), 100.0),
                                (dt.datetime(2026, 10, 30, tzinfo=NY), 110.0)])
        row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                              schedule('NYSE', '2026-10-28', '2026-10-31'), 'America/New_York')
        self.assertEqual(row['status'], 'COMPLETED_CLOSE')
        self.assertEqual(row['bar_date'], '2026-10-30')

    def test_holiday_not_stale(self):
        cutoff = dt.datetime(2026, 11, 26, 18, 0, tzinfo=IST)  # US Thanksgiving
        bars = frame('^GSPC', [(dt.datetime(2026, 11, 24, tzinfo=NY), 100.0),
                                (dt.datetime(2026, 11, 25, tzinfo=NY), 110.0)])
        row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                              schedule('NYSE', '2026-11-23', '2026-11-26'), 'America/New_York')
        self.assertEqual(row['status'], 'COMPLETED_CLOSE')
        self.assertEqual(row['bar_date'], '2026-11-25')

    def test_stale_missing_newer_session(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 27, tzinfo=NY), 100.0),
                                (dt.datetime(2026, 10, 28, tzinfo=NY), 110.0)])
        row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                              schedule('NYSE', '2026-10-27', '2026-10-30'), 'America/New_York')
        self.assertEqual(row['status'], 'STALE')
        self.assertEqual(row['lag_sessions'], 1)

    def test_invalid_or_missing_close_not_zero(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        for missing in (None, 0, float('nan'), -1):
            with self.subTest(value=missing):
                bars = frame('^GSPC', [(dt.datetime(2026, 10, 28, tzinfo=NY), 100.0),
                                        (dt.datetime(2026, 10, 29, tzinfo=NY), missing)])
                row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                                      schedule('NYSE', '2026-10-27', '2026-10-30'), 'America/New_York')
                self.assertEqual(row['status'], 'UNAVAILABLE')
                self.assertNotIn('close', row)

    def test_missing_previous_close(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 29, tzinfo=NY), 110.0)])
        row = probe.normalize('S&P 500', '^GSPC', bars, cutoff,
                              schedule('NYSE', '2026-10-27', '2026-10-30'), 'America/New_York')
        self.assertEqual(row['status'], 'UNAVAILABLE')
        self.assertIn('Previous', row['reason'])

    def test_unzoned_timestamp_and_source_mismatch(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        cal = schedule('NYSE', '2026-10-27', '2026-10-30')
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 29), 100.0)])
        self.assertEqual(probe.normalize('S&P 500', '^GSPC', bars, cutoff, cal,
                                         'America/New_York')['status'], 'UNAVAILABLE')
        bars = frame('WRONG', [(dt.datetime(2026, 10, 29, tzinfo=NY), 100.0)])
        self.assertIn('symbol', probe.normalize('S&P 500', '^GSPC', bars, cutoff, cal,
                                               'America/New_York')['reason'])

    def test_unexpected_schema_and_future_bar(self):
        cutoff = dt.datetime(2026, 10, 30, 7, 45, tzinfo=IST)
        cal = schedule('NYSE', '2026-10-27', '2026-10-30')
        bars = frame('^GSPC', [(dt.datetime(2026, 10, 28, tzinfo=NY), 100.0),
                                (dt.datetime(2026, 10, 29, tzinfo=NY), 110.0),
                                (dt.datetime(2026, 10, 30, tzinfo=NY), 999.0)])
        self.assertEqual(probe.normalize('S&P 500', '^GSPC', bars, cutoff, cal,
                                         'America/New_York')['close'], 110)
        bars = bars.drop(columns=['Close'])
        self.assertEqual(probe.normalize('S&P 500', '^GSPC', bars, cutoff, cal,
                                         'America/New_York')['status'], 'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
