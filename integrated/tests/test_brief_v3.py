"""Offline rule and layout checks for the morning brief."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader
from integrated.brief_v3 import futures_point, option_points, vix_flag, select_news, select_events, caption
from integrated.render import render

class BriefV3Tests(unittest.TestCase):
    def test_same_future_contract_and_missing_baseline(self):
        row={'check':'NIFTY futures','status':'PASS','instrument_key':'NSE_FO|1','expiry':'2030-01-10',
             'daily_observations':[{'date':'2030-01-08','close':'105','oi_raw':120},
                                   {'date':'2030-01-07','close':'100','oi_raw':100}]}
        self.assertEqual(futures_point([row],['2030-01-08','2030-01-07']),1)
        row['daily_observations'].pop()
        self.assertIsNone(futures_point([row],['2030-01-08','2030-01-07']))
    def test_pcr_walls_and_vix(self):
        option={'status':'PROVISIONAL','pcr_current':'1.2','pcr_previous':'1.1',
                'pcr_direction':'UP','call_walls':['120'],'put_walls':['95']}
        spot={'status':'PASS','close':'100'}
        self.assertEqual(option_points(option,spot),(1,1))
        option['put_walls']=['95','90']
        self.assertEqual(option_points(option,spot),(1,None))
        option['put_walls']=['90'];option['call_walls']=['110']
        self.assertEqual(option_points(option,spot),(1,None))
        self.assertEqual(vix_flag({'status':'PASS','close':'19','change_pct':'8'}),'CAUTION')
        self.assertEqual(vix_flag({'status':'PASS','close':'20','change_pct':'-1'}),'CAUTION')
        self.assertEqual(vix_flag({'status':'PASS','close':'19','change_pct':'7.9'}),'NORMAL')
        self.assertEqual(vix_flag({'status':'UNAVAILABLE'}),'UNKNOWN')
    def test_news_ranking_and_event_filter(self):
        rows=[{'title':title,'url':f'https://example.org/{i}','published_IST':'2030-01-08T07:00:00+05:30','source':'example.org'}
              for i,title in enumerate(('RBI rupee India markets','Nifty FII India stocks','India Sensex banking',
                                         'Fed US yields','OPEC crude oil','Celebrity lottery tips',
                                         'Oil Indicators Found in a Reservoir'))]
        selected=select_news(rows)
        self.assertEqual(len(selected),5)
        self.assertNotIn('Celebrity lottery tips',[x['title'] for x in selected])
        us,india=select_events([{'agency':'BLS','title':'Consumer Price Index','date_IST':'2030-01-08'},
                                {'agency':'BLS','title':'Outdoor Recreation Statistics','date_IST':'2030-01-08'},
                                {'agency':'RBI','title':'RBI decision','date_IST':'2030-01-08'}],
                               '2030-01-08',[('NIFTY','2030-01-08')])
        self.assertEqual(len(us),1);self.assertEqual(len(india),2)
    def test_caption_six_lines_and_pdf(self):
        s=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        r=json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        s['global']=[{'name':'GIFT NIFTY','value':110,'status':'PROVISIONAL','change_pct':'1','asof':'2026-10-28T07:44:00+05:30'},
                     {'name':'Oil (Brent)','value':80},{'name':'USD INR','value':90}]
        s['spot']={'NIFTY':{'status':'PASS','close':'100'}}
        s['news']=[{'title':f'India market report {i}','source':'example.org','url':f'https://example.org/{i}',
                    'published_IST':'2026-10-28T06:30:00+05:30'} for i in range(8)]
        s['news_note']='8 shown of 8 matched in the window.'
        self.assertEqual(len(caption(s,r).splitlines()),6)
        self.assertIn('+10.00 pts',caption(s,r))
        s['global'][0]['status']='PRIOR QUOTE'
        self.assertIn('GIFT vs Nifty close: N/A',caption(s,r))
        s['global'][0]['status']='PROVISIONAL'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.pdf';render(s,r,path)
            pages=PdfReader(path).pages
            self.assertEqual(len(pages),2)
            page=pages[0].extract_text()
            self.assertIn('Opening picture',page)
            self.assertIn('example.org',page)
            self.assertIn('India market report 7',page)
            self.assertIn('8 shown of 8 matched',page)
            for forbidden in ('PARTIAL TRIAL','MCP','GitHub Actions','shadow, not counted'):
                self.assertNotIn(forbidden,page)
    def test_pdf_explains_missing_market_and_source_fields(self):
        s=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        r=json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        s['global']=[{'name':'GIFT NIFTY','status':'AFTER CUTOFF','value':None,
                      'reason':'Last trade was after 07:45 IST'},
                     {'name':'NIKKEI 225','status':'AFTER CUTOFF','value':None,
                      'reason':'Last trade was after 07:45 IST'},
                     {'name':'Oil (Brent)','status':'PROVISIONAL','value':81,
                      'change_reason':'Previous daily close has invalid OHLCV/OI values.'}]
        s['spot']={'NIFTY':{'status':'UNAVAILABLE','reason':'Daily close missing for required session'}}
        s['news']=[];s['news_note']='News unavailable: quota exhausted today'
        s['calendar']=[];s['calendar_note']='Published calendar download failed'
        s['india_corporate_events']='N/A: official results, ex-date and IPO feed not validated'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.pdf';render(s,r,path)
            content='\n'.join(page.extract_text() for page in PdfReader(path).pages)
            for expected in ('Quote after 07:45 cutoff','Daily close missing',
                             'quota exhausted today','Published calendar download failed',
                             'official results, ex-date and IPO feed not validated',
                             'Previous daily close has invalid OHLCV/OI values'):
                self.assertIn(expected,content)

if __name__=='__main__':unittest.main()
