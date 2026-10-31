import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from integrated.cloud_review import make_review,run
from integrated.collect import digest
from integrated.review import IST,validate
from nse_report.calculations import score_summary
from integrated.collect import clean

class CloudReviewTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,10,28,7,55,tzinfo=IST)
        self.snapshot={'schema_version':1,'report_date':'2026-10-28',
          'cutoff_IST':'2026-10-28T07:45:00+05:30','trading_day':'OPEN',
          'completed_sessions':{'NSE':['2026-10-27']},
          'score':clean(score_summary({'fii_futures':-1,'fii_cash':1,'dii_cash':1})),
          'vix_flag':'UNKNOWN'}
    def setup_root(self,root):
        (root/'handoff').mkdir()
        (root/'handoff/2026-10-28.json').write_text(json.dumps(self.snapshot))
        (root/'handoff/latest.json').write_text(json.dumps({
          'report_date':'2026-10-28','path':'handoff/2026-10-28.json',
          'snapshot_sha256':digest(self.snapshot)}))
    def test_partial_score_and_no_mcp_claim(self):
        review=make_review(self.snapshot)
        validate(self.snapshot,review,self.now,live=True)
        self.assertIn('3/6',review['summary'])
        self.assertEqual(review['mcp_context'],[])
        self.assertLessEqual(max(map(len,review['alerts'])),180)
    def test_creates_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            self.assertTrue(run(root,self.now))
            self.assertFalse(run(root,self.now))
    def test_late_workflow_trigger_skips_without_review(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            late=dt.datetime(2026,10,28,14,7,tzinfo=IST)
            self.assertFalse(run(root,late))
            self.assertFalse((root/'review_requests').exists())
    def test_stale_handoff_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            with self.assertRaises(ValueError):run(root,self.now+dt.timedelta(days=1))
    def test_early_collector_completion_waits_for_cloud_cron(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            self.assertFalse(run(root,self.now-dt.timedelta(minutes=6)))
            self.assertFalse((root/'review_requests').exists())
    def test_preflight_completion_without_snapshot_is_quiet(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(run(Path(d),dt.datetime(2026,10,28,7,35,tzinfo=IST)))
    def test_closed_session_skips(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshot['trading_day']='CLOSED';self.setup_root(root)
            self.assertFalse(run(root,self.now))
            self.assertFalse((root/'review_requests').exists())
    def test_tampered_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            self.snapshot['score']['score']=6
            (root/'handoff/2026-10-28.json').write_text(json.dumps(self.snapshot))
            with self.assertRaises(ValueError):run(root,self.now)
    def test_existing_ledger_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root)
            (root/'delivery_ledger').mkdir()
            (root/'delivery_ledger/2026-10-28.json').write_text('{}')
            self.assertFalse(run(root,self.now))
