import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from integrated.collect import clean,digest,option_summary
from integrated.review import validate,IST
from integrated.deliver import reserve
from nse_report.calculations import score_summary
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.s={'schema_version':1,'report_date':'2026-10-28','cutoff_IST':'2026-10-28T07:45:00+05:30','trading_day':'OPEN','completed_sessions':{'NSE':['2026-10-27']},'score':clean(score_summary({'fii_futures':-1}))}
        self.r={'schema_version':1,'report_date':'2026-10-28','snapshot_sha256':digest(self.s),'summary':'Synthetic test only','alerts':['Missing signals','Units unresolved','VIX unknown'],'mcp_context':[]}
        self.now=dt.datetime(2026,10,28,7,59,tzinfo=IST)
    def test_valid_partial(self):
        q=validate(self.s,self.r,self.now,True);self.assertEqual(q['score_range'],[-6,4]);self.assertEqual(q['available'],1)
    def test_changed_snapshot_rejected(self):
        self.s['trading_day']='CLOSED'
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now)
    def test_score_override_rejected(self):
        self.r['score']=6
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now)
    def test_tampered_score_rejected(self):
        self.s['score']['score']=6;self.r['snapshot_sha256']=digest(self.s)
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now)
    def test_old_report_rejected(self):
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now+dt.timedelta(days=1),True)
    def test_late_delivery_rejected(self):
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now+dt.timedelta(minutes=20),True)
    def test_unknown_session_rejected(self):
        self.s['trading_day']='UNVERIFIED';self.r['snapshot_sha256']=digest(self.s)
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now,True)
    def test_stale_mcp_rejected(self):
        self.r['mcp_context']=[{'source':'nse-bhavcopy','data_date':'2026-10-26','text':'stale'}]
        with self.assertRaises(ValueError):validate(self.s,self.r,self.now)
    def test_duplicate_reservation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';reserve(p,{},lambda p:None)
            with self.assertRaises(ValueError):reserve(p,{},lambda p:None)
    def test_failed_reservation_commit_blocks_send(self):
        def fail(p):raise RuntimeError('synthetic remote failure')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json'
            with self.assertRaises(RuntimeError):reserve(p,{},fail)
            self.assertTrue(p.exists())
if __name__=='__main__':unittest.main()

class RetrievalClockTests(unittest.TestCase):
    def test_quote_clock_does_not_change_selected_sessions(self):
        from unittest.mock import Mock,patch
        from integrated.adapters import flows
        cutoff=dt.datetime(2026,10,28,7,45,tzinfo=IST)
        retrieval=cutoff+dt.timedelta(minutes=8)
        dates=['2026-10-27','2026-10-26'];key='synthetic'
        api=Mock();api.get.return_value={'x':{'instrument_token':key,'oi':100}}
        bars={d:{'close':'100','oi_raw':100} for d in dates}
        q={'status':'PASS','last_trade_time_IST':'2026-10-27T15:30:00+05:30'}
        with patch.object(flows,'search_future',return_value={'instrument_key':key}),patch.object(flows,'daily_bars',return_value=bars),patch.object(flows,'quote',return_value=q) as quote:
            result=flows.futures_check(api,'synthetic','synthetic',cutoff,dates,{('NFO',dates[0]):'synthetic'},observed_now=retrieval)
        self.assertEqual(quote.call_args.args[2],retrieval)
        self.assertEqual(result['latest_date'],'2026-10-27')
