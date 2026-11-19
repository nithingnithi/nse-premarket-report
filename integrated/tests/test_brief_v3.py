"""Offline rule and layout checks for the morning brief."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfReader
from reportlab.platypus import Paragraph
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
                                         'Fed US yields','OPEC crude oil','Indian equities slip as banks decline',
                                         'Celebrity lottery tips',
                                         'Oil Indicators Found in a Reservoir'))]
        selected=select_news(rows)
        self.assertEqual(len(selected),6)
        self.assertIn('Indian equities slip as banks decline',[x['title'] for x in selected])
        self.assertNotIn('Celebrity lottery tips',[x['title'] for x in selected])
        us,india=select_events([{'agency':'BLS','title':'Consumer Price Index','date_IST':'2030-01-08'},
                                {'agency':'BLS','title':'Outdoor Recreation Statistics','date_IST':'2030-01-08'},
                                {'agency':'RBI','title':'RBI decision','date_IST':'2030-01-08'}],
                               '2030-01-08',[('NIFTY','2030-01-08')])
        self.assertEqual(len(us),1);self.assertEqual(len(india),2)

    def test_india_first_and_global_stories_never_fill_missing_india_slots(self):
        domestic = ['SEBI weighs MTF limits', 'RBI reacts to Fed rate decision',
                    'FIIs buy Indian equities', 'Sensex rises', 'NSE reviews listing norms',
                    'Indian banks raise deposit rates']
        overseas = ['Fed rate decision moves Treasury yields', 'OPEC reviews crude oil output',
                    'ECB rate cut', 'Wall Street selloff widens', 'US celebrity picks a credit card']
        rows = [{'title': title, 'url': f'https://example.org/{i}',
                 'published_IST':'2030-01-08T07:00:00+05:30'}
                for i, title in enumerate(overseas + domestic)]
        titles = [row['title'] for row in select_news(rows + [rows[-1]])]
        self.assertEqual(set(titles[:6]), set(domestic))
        self.assertEqual(len(titles), 8)

        sparse = select_news(rows[:len(overseas)+1])
        self.assertEqual(sparse[0]['title'], domestic[0])
        self.assertEqual(len(sparse), 1)
        self.assertEqual(len(select_news(rows[:len(overseas)+2])), 3)
        self.assertEqual(select_news(rows, limit=1)[0]['title'], titles[0])

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
            self.assertEqual(len(pages),3)
            snapshot=pages[0].extract_text()
            page=pages[1].extract_text()
            self.assertIn('Pre-Market Snapshot',snapshot)
            self.assertIn('RATES, COMMODITIES AND CURRENCY',snapshot)
            self.assertIn('US close %; ADR/NSE premium N/A without ratio',snapshot)
            self.assertIn('WHY IT MATTERS TODAY',page)
            self.assertIn('KEY NEWS / LAST 12 HOURS',page)
            self.assertIn('OPENING PICTURE',page)
            self.assertIn('example.org',page)
            self.assertIn('India market report 7',page)
            self.assertIn('8 shown of 8 matched',page)
            for forbidden in ('PARTIAL TRIAL','MCP','GitHub Actions','shadow, not counted'):
                self.assertNotIn(forbidden,page)
    def test_eight_news_items_clear_page_footer(self):
        s=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        r=json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        s['news']=[{'title':f'India market report {i} with important recent factual developments affecting the next trading session',
                    'source':'example.org','url':f'https://example.org/{i}',
                    'published_IST':'2026-10-28T06:30:00+05:30'} for i in range(8)]
        with tempfile.TemporaryDirectory() as d:
            positions=[]
            original=Paragraph.drawOn
            def traced(paragraph,canvas,x,y,*args,**kwargs):
                if 'India market report 7' in paragraph.getPlainText():
                    positions.append(y)
                return original(paragraph,canvas,x,y,*args,**kwargs)
            path=Path(d)/'brief.pdf'
            with patch.object(Paragraph,'drawOn',traced):render(s,r,path)
            self.assertEqual(len(positions),1)
            self.assertGreaterEqual(positions[0],55)
    def test_snapshot_does_not_turn_gap_into_model_bias_or_show_after_cutoff_quote(self):
        s=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        r=json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        s['completed_sessions']={'NSE':['2026-10-27']}
        s['spot']={'NIFTY':{'status':'PASS','latest_date':'2026-10-27','close':'100','change_pct':'2'}}
        s['global']=[{'name':'GIFT NIFTY','status':'PROVISIONAL','value':95,
                      'asof':'2026-10-28T07:44:00+05:30'},
                     {'name':'NIKKEI 225','status':'PROVISIONAL','value':999,
                      'asof':'2026-10-28T07:46:00+05:30'}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'brief.pdf';render(s,r,path)
            page=PdfReader(path).pages[0].extract_text()
            self.assertIn('Gap-down',page)
            self.assertIn('-5 pts',page)
            self.assertIn('Insufficient Data To\nAssign Final Bias',page)
            self.assertNotIn('999',page)
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
