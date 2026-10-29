import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader
from integrated.cloud_review import make_review
from integrated.news_selection import select
from integrated.render import render
from integrated.shadow_history import append
from integrated.collect import close_change
from integrated.dry_run import unavailable

ROOT=Path(__file__).parent/'fixtures'

class ReportV2Tests(unittest.TestCase):
    def test_previous_close_change_and_missing_baseline(self):
        self.assertEqual(close_change('105','100')['change_pct'],'5')
        self.assertIsNone(close_change('105',None)['change_pct'])

    def test_missing_field_reasons_are_kept(self):
        snapshot=json.loads((ROOT/'snapshot.json').read_text())
        labels=dict(unavailable(snapshot))
        self.assertIn('Completed-session quote unavailable',labels['Nifty spot'])
        self.assertIn('Same-expiry option baseline unavailable',labels['NIFTY PCR'])

    def test_news_window_relevance_and_syndication(self):
        cutoff=dt.datetime(2026,10,29,7,45,tzinfo=dt.timezone(dt.timedelta(hours=5,minutes=30)))
        def article(title,hour,url):
            return {'title':title,'published_IST':(cutoff+dt.timedelta(hours=hour)).isoformat(),
                    'url':url,'source':'example.com'}
        rows=[article('Nifty rises after RBI decision',-1,'https://example.com/one'),
              article('Nifty rises after RBI decision!',-1,'https://example.com/two'),
              article('Best credit card for travel',-2,'https://example.com/three'),
              article('Crude oil moves before market open',-13,'https://example.com/four'),
              article('Federal Reserve rate decision',-11,'https://example.com/five')]
        chosen=select(rows,cutoff)
        self.assertEqual(len(chosen),2)
        self.assertIn('Federal Reserve',chosen[1]['title'])

    def test_history_appends_runs_and_replaces_same_attempt(self):
        snapshot=json.loads((ROOT/'snapshot.json').read_text())
        snapshot['shadow_signals']={'futures_build_up':{'value':1,'reason':'same contract'},
                                    'pcr_direction':{'value':None,'reason':'baseline missing'}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.csv'
            append(path,snapshot,'101','1');append(path,snapshot,'101','1')
            append(path,snapshot,'102','1')
            with path.open(newline='') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['official_score'],'-1')
            self.assertEqual(rows[0]['shadow_futures_build_up'],'1')
            self.assertEqual(rows[0]['shadow_pcr_direction'],'N/A')

    def test_two_page_pdf_shows_shadow_reason_and_unique_wall(self):
        snapshot=json.loads((ROOT/'snapshot.json').read_text())
        snapshot['shadow_signals']={'futures_build_up':{'value':None,'reason':'Same-contract baseline missing'},
                                    'pcr_direction':{'value':1,'reason':'PCR rose'},
                                    'strike_walls':{'value':None,'reason':'Tied call wall'}}
        snapshot['options']={'NIFTY':{'status':'PROVISIONAL','expiry':'2026-11-03',
                   'pcr_current':'1.1','call_walls':['23000'],'put_walls':['22500'],
                   'max_pain':['22700']}}
        snapshot['indices']={'Nifty':{'last_price':'22750','change':'50'}}
        snapshot['news']=[{'title':'<b>Nifty market</b>','source':'Example News',
                          'published_IST':'2026-10-28T06:30:00+05:30','url':'https://example.com/news'}]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.pdf';render(snapshot,make_review(snapshot),path)
            pdf=PdfReader(path)
            self.assertEqual(len(pdf.pages),2)
            page1=pdf.pages[0].extract_text()
            self.assertIn('shadow, not counted',page1)
            self.assertIn('Same-contract baseline missing',page1)
            self.assertIn('23,000',page1)
            self.assertIn('250 pts',page1)
            self.assertNotIn('MCP',page1)
            self.assertNotIn('PASS',page1)

if __name__=='__main__':unittest.main()
