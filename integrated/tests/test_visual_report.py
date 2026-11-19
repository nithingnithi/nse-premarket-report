"""Offline checks for the three-page visual delivery format."""
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

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
            self.assertIn('GOLD LIVE 28 Oct 07:46', PdfReader(path).pages[2].extract_text())
            self.assertNotIn('50\n28 Oct', page)


if __name__ == '__main__':
    unittest.main()
