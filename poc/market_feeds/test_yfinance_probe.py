import datetime as dt, io, json, unittest
from contextlib import redirect_stdout
from zoneinfo import ZoneInfo
import yfinance_probe as probe
IST=ZoneInfo('Asia/Kolkata')
NOW=dt.datetime(2026,10,30,7,45,tzinfo=IST)
class FakeFrame:
    def __init__(self,rows):
        self.index=[r[0] for r in rows]; self.values=[r[1] for r in rows]; self.empty=not rows
    def __getitem__(self,key):
        if key!='Close': raise KeyError(key)
        return self.values
class ProbeTests(unittest.TestCase):
    def test_disabled_default(self):
        out=io.StringIO()
        with redirect_stdout(out): self.assertEqual(probe.main(['--cutoff-ist',NOW.isoformat()]),0)
        self.assertEqual(json.loads(out.getvalue())['status'],'DISABLED')
    def test_empty(self):
        self.assertEqual(probe.normalize('X','X',FakeFrame([]),NOW)['status'],'UNAVAILABLE')
    def test_future_candle_ignored(self):
        frame=FakeFrame([(NOW-dt.timedelta(days=1),100),(NOW+dt.timedelta(hours=2),999)])
        self.assertEqual(probe.normalize('X','X',frame,NOW)['close'],100)
    def test_stale(self):
        self.assertEqual(probe.normalize('X','X',FakeFrame([(NOW-dt.timedelta(days=7),100)]),NOW)['status'],'STALE')
    def test_unzoned(self):
        self.assertEqual(probe.normalize('X','X',FakeFrame([(dt.datetime(2026,10,29,8),100)]),NOW)['status'],'UNAVAILABLE')
    def test_change(self):
        frame=FakeFrame([(NOW-dt.timedelta(days=2),100),(NOW-dt.timedelta(days=1),110)])
        a=probe.normalize('X','X',frame,NOW)
        self.assertEqual(a['status'],'OBSERVED'); self.assertEqual(a['change_pct'],10)
if __name__=='__main__': unittest.main()
