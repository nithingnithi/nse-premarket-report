import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from integrated.collect import clean,digest,option_summary
from integrated.review import validate,IST
from integrated.deliver import reserve,send_if_current
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
    def test_late_after_render_never_starts_telegram_send(self):
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            pdf=Path(d)/'report.pdf';pdf.write_bytes(b'synthetic-pdf')
            late=self.now+dt.timedelta(minutes=20)
            with self.assertRaises(ValueError):
                send_if_current(self.s,self.r,pdf,
                                sender=lambda *_:calls.append('sent'),clock=lambda:late)
        self.assertEqual(calls,[])
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

class CashSignalTests(unittest.TestCase):
    def row(self,nets):
        days=['2026-10-27','2026-10-26','2026-10-23','2026-10-22','2026-10-21']
        return {'check':'FII cash','status':'PASS','observations':[{'date':d,'buy_raw':str(max(n,0)),'sell_raw':str(max(-n,0)),'net_raw':str(n)} for d,n in zip(days,nets)],'net_sum_last_5_raw':str(sum(nets))},days
    def test_signs(self):
        from integrated.collect import cash_signal
        for nets,expected in [([1]*5,1),([-1]*5,-1),([0]*5,0)]:
            row,days=self.row(nets);self.assertEqual(cash_signal(row,days),expected)
    def test_invalid_coverage_and_values(self):
        from integrated.collect import cash_signal
        for change in ('missing','duplicate','stale','nan','wrong_sum','wrong_net','fail'):
            row,days=self.row([1]*5)
            if change=='missing':row['observations'].pop()
            if change=='duplicate':row['observations'][1]['date']=days[0]
            if change=='stale':row['observations'][0]['date']='2026-10-20'
            if change=='nan':row['observations'][0]['buy_raw']='NaN'
            if change=='wrong_sum':row['net_sum_last_5_raw']='0'
            if change=='wrong_net':row['observations'][0]['net_raw']='0'
            if change=='fail':row['status']='FAIL'
            with self.subTest(change=change):self.assertIsNone(cash_signal(row,days))
    def test_independent_signals_no_offset(self):
        from integrated.collect import cash_signals
        fii,days=self.row([-1]*5);dii,_=self.row([2]*5);dii['check']='DII cash'
        self.assertEqual(cash_signals([fii,dii],days),{'fii_cash':-1,'dii_cash':1})
    def test_duplicate_provider_row_unavailable(self):
        from integrated.collect import cash_signals
        row,days=self.row([1]*5);self.assertIsNone(cash_signals([row,row],days)['fii_cash'])
