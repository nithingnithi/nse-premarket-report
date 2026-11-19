"""Offline checks for the three-page visual delivery format."""
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from integrated.adapters.corporate_events import reviewed_events
from integrated.brief_v3 import traditional_pivots
from integrated.visual_report import render_visual


class VisualReportTests(unittest.TestCase):
    def fixtures(self):
        root = Path('integrated/tests/fixtures')
        return (json.loads((root/'snapshot.json').read_text()),
                json.loads((root/'review.json').read_text()))

    def test_three_page_structure_and_existing_score(self):
        s, review = self.fixtures()
        before = json.dumps(s['score'], sort_keys=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(s, review, path)
            pages = PdfReader(path).pages
            self.assertEqual(len(pages), 3)
            self.assertIn('Opening dashboard', pages[0].extract_text())
            self.assertIn('SCORE -1 / 1/6 valid', pages[0].extract_text())
            self.assertIn('Flows, options & levels', pages[1].extract_text())
            self.assertIn('News, events & data quality', pages[2].extract_text())
            self.assertIn('SYNTHETIC FIXTURE', pages[0].extract_text())
        self.assertEqual(json.dumps(s['score'], sort_keys=True), before)

    def test_missing_reasons_and_after_cutoff_quotes(self):
        s, review = self.fixtures()
        s['global'] = [{'name':'GIFT NIFTY','status':'AFTER CUTOFF','value':99999,
                        'asof':'2026-10-28T07:46:00+05:30',
                        'reason':'Quote arrived after the cutoff'}]
        s['options'] = {'BANKNIFTY':{'status':'UNAVAILABLE','pcr_current':'1.25',
                         'reason':'Contract universe changed: 2 added, 0 removed'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(s, review, path)
            pages = PdfReader(path).pages
            content = '\n'.join(page.extract_text() for page in pages)
            self.assertNotIn('99999', content)
            self.assertNotIn('1.25', content)
            self.assertIn('Quote after 07:45 cutoff', content)
            self.assertIn('Contract universe changed', content)

    def test_news_links_and_futures_same_session_requirement(self):
        s, review = self.fixtures()
        s['news'] = [{'title':'India market headline','source':'Fixture News',
                      'url':'https://example.org/report',
                      'published_IST':'2026-10-28T07:00:00+05:30'}]
        s['flows'] = [{'check':'NIFTY futures','status':'PASS','expiry':'2026-10-29',
                       'instrument_key':'NSE_FO|fixture',
                       'daily_observations':[{'date':'2026-10-27','close':'110','oi_raw':120},
                                             {'date':'2026-10-25','close':'100','oi_raw':100}]}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(s, review, path)
            reader = PdfReader(path)
            self.assertIn('India market headline', reader.pages[2].extract_text())
            annotations = reader.pages[2].get('/Annots', [])
            self.assertTrue(any('example.org/report' in str(a.get_object()) for a in annotations))
            # The fixture lacks D-1 NFO session, so it cannot show a build-up.
            self.assertNotIn('LONG BUILD', reader.pages[1].extract_text())

    def test_current_only_option_levels_and_long_api_reasons_fit(self):
        s, review = self.fixtures()
        s['completed_sessions'] = {'NSE':['2026-10-27','2026-10-26'],
                                   'BSE':['2026-10-27','2026-10-26']}
        s['spot'] = {'BANKNIFTY':{'status':'PASS','latest_date':'2026-10-27',
                                  'close':'105','change_pct':'1'}}
        s['options'] = {'BANKNIFTY':{'status':'PARTIAL','expiry':'2026-10-29',
                        'pcr_current':'1.25','pcr_previous':None,
                        'call_walls':['110'],'put_walls':['100'],'max_pain':['105'],
                        'call_oi_change':None,'put_oi_change':None,
                        'reason':'Contract universe changed: 16 added, 0 removed, '
                                 '0 changed IDs; PCR direction and OI change withheld'}}
        s['extra_data'] = {'adrs':{'Infosys':{'status':'PROVISIONAL','date':'2026-10-27',
                          'unit':'USD per ADR','change_pct':'1'},
                          'Wipro':{'status':'UNAVAILABLE',
                          'reason':'Alpha Vantage ADR quote or symbol missing'}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(s, review, path)
            pages = PdfReader(path).pages
            self.assertEqual(len(pages), 3)
            self.assertIn('Previous-session breadth not collected',pages[0].extract_text())
            self.assertIn('2026-10-27 EOD; time N/A',pages[0].extract_text())
            self.assertIn('1.25',pages[1].extract_text())
            self.assertIn('Current levels only',pages[1].extract_text())
            self.assertIn('OI change withheld',pages[1].extract_text())
            self.assertIn('PREVIOUS PCR\nN/A',pages[1].extract_text())
            s['options']['BANKNIFTY'].update(strikes=198,matched_comparison={
                'strikes':190,'previous_strikes':190,'pcr_previous':'1.34','pcr_current':'1.18',
                'call_oi_change':1500,'put_oi_change':-600})
            render_visual(s, review, path)
            page=PdfReader(path).pages[1].extract_text()
            self.assertIn('PCR (ALL CURRENT STRIKES)\n1.25',page)
            self.assertIn('PCR (MATCHED: PRIOR / CURRENT)\n1.34 / 1.18',page)
            self.assertIn('CALL / PUT OI CHANGE (MATCHED)\n+1,500 / -600',page)
            self.assertIn('190 matched strikes (prior 190, current 198)',page)

    def test_metal_spot_unit_and_after_cutoff_label(self):
        s, review = self.fixtures()
        s['extra_data'] = {'metals':{
            'GOLD':{'status':'PROVISIONAL','value':'4000','unit':'USD per troy oz',
                    'asof_IST':'2026-10-28T07:46:00+05:30'},
            'SILVER':{'status':'PROVISIONAL','value':'50','unit':'wrong unit',
                      'asof_IST':'2026-10-28T07:44:00+05:30'}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(s, review, path)
            page = PdfReader(path).pages[0].extract_text()
            self.assertIn('$4,000', page)
            self.assertIn('LIVE 28 Oct 07:46:00 IST', page)
            self.assertIn('GOLD LIVE 28 Oct 07:46', PdfReader(path).pages[2].extract_text())
            self.assertNotIn('50\n28 Oct', page)

    def test_three_index_pivot_panel_uses_the_exact_exchange_session(self):
        self.assertEqual(traditional_pivots('120','90','105'), ((90,75,60),(120,135,150)))
        self.assertIsNone(traditional_pivots('NaN','90','105'))
        self.assertIsNone(traditional_pivots('120','90','125'))
        snapshot, review = self.fixtures()
        snapshot['completed_sessions'] = {'NSE':['2026-10-27'], 'BSE':['2026-10-26']}
        snapshot['spot'] = {
            'NIFTY':{'status':'PASS','latest_date':'2026-10-27','high':'120','low':'90','close':'105'},
            'BANKNIFTY':{'status':'PASS','latest_date':'2026-10-27','close':'105'},
            'SENSEX':{'status':'PASS','latest_date':'2026-10-26','high':'1200','low':'900','close':'1050'},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'visual.pdf'
            render_visual(snapshot, review, path)
            page = PdfReader(path).pages[1].extract_text()
            for expected in ('S 90 / 75 / 60', 'R 120 / 135 / 150', 'BANK NIFTY\nS N/A',
                             'SENSEX\nS 900 / 750 / 600', 'PDH: 1,200', 'PDL: 900'):
                self.assertIn(expected, page)
            snapshot['completed_sessions']['BSE'] = ['2026-10-27']
            render_visual(snapshot, review, path)
            stale = PdfReader(path).pages[1].extract_text()
            self.assertIn('SENSEX\nS N/A', stale)
            self.assertNotIn('1,200', stale)

    def test_reviewed_corporate_events_require_prior_filing_and_exact_report_date(self):
        snapshot, review = self.fixtures()
        day = snapshot['report_date']
        event = {'kind':'IPO opens','title':'Fixture Industries','note':'Bidding opens today',
                 'announced_on':'2026-10-27','url':'https://www.sebi.gov.in/filings/example'}
        with tempfile.TemporaryDirectory() as directory:
            calendar = Path(directory)/'corporate.json'
            calendar.write_text(json.dumps({day:[event,{**event,'title':'Late fixture','announced_on':day}]}))
            result = reviewed_events(day,calendar)
            self.assertEqual(result['status'],'REVIEWED')
            self.assertEqual(len(result['items']),1)
            self.assertEqual(reviewed_events('2026-10-29',calendar)['status'],'UNAVAILABLE')
            snapshot['india_corporate_events']=result
            path=Path(directory)/'visual.pdf'
            render_visual(snapshot,review,path)
            page=PdfReader(path).pages[2]
            self.assertIn('INDIAN CORPORATE EVENTS',page.extract_text())
            self.assertIn('Fixture Industries',page.extract_text())
            self.assertNotIn('Late fixture',page.extract_text())
            self.assertNotIn('CORPORATE EVENTS — N/A',page.extract_text())
            self.assertIn(event['url'],[a.get_object()['/A']['/URI'] for a in page['/Annots']])


if __name__ == '__main__':
    unittest.main()
