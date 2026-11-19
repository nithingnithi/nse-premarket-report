"""No live providers in CI."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from integrated.adapters import sbi

IST = ZoneInfo('Asia/Kolkata')
CUTOFF = dt.datetime(2026, 11, 19, 7, 45, tzinfo=IST)
NSE = 'https://nsearchives.nseindia.com/corporate/SBIN_fixture.pdf'


def announcement(date, title='SBIN fixture', description='Board meeting date: 23-Nov-2026'):
    return (f'<item><title>{title}</title><link>{NSE}</link>'
            f'<description>{description}</description><pubDate>{date}</pubDate></item>')


def rss(*items):
    return ('<rss><channel>' + ''.join(items) + '</channel></rss>').encode()


class SBISources(unittest.TestCase):
    def test_rss_board_dates_and_cutoff(self):
        result = sbi.filings(rss(
            announcement('16-Nov-2026 18:35:00'),
            announcement('19-Nov-2026 07:46:00', description='Board meeting date: 24-Nov-2026'),
            announcement('18-Nov-2026 23:00:00', title='SBI Life Insurance Company'),
        ), 'board_meetings', CUTOFF)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual([row['date'] for row in result['upcoming']], ['2026-11-23'])
        self.assertEqual(result['upcoming'][0]['url'], NSE)
        self.assertEqual(result['notices'], [])
        self.assertEqual(sbi.filings(rss(announcement('19 Nov 26')),
                                     'board_meetings', CUTOFF)['status'], 'PARTIAL')

    def test_rescheduled_meeting_does_not_promote_older_date(self):
        result = sbi.filings(rss(
            announcement('16-Nov-2026 18:35:00'),
            announcement('18-Nov-2026 21:00:00', description='Board meeting postponed'),
        ), 'board_meetings', CUTOFF)
        self.assertEqual((result['status'], result['upcoming']), ('PARTIAL', []))

    def test_announcements_are_bounded_to_the_news_window(self):
        result = sbi.filings(rss(
            announcement('18-Nov-2026 19:45:00'),
            announcement('19-Nov-2026 07:45:00'),
            announcement('19-Nov-2026 07:46:00'),
        ), 'announcements', CUTOFF)
        self.assertEqual(len(result['notices']), 1)
        self.assertEqual(result['notices'][0]['published_IST'], CUTOFF.isoformat(timespec='seconds'))

    def test_action_dates_and_known_announcement_requirement(self):
        def dividend(ex_date, announced):
            return {'name': 'Dividend', 'expiry_date': ex_date,
                    'amount': 17.35, 'event_details': [
                        {'name': 'Announcement date', 'value': announced},
                        {'name': 'Record date', 'value': ex_date}]}
        result = sbi.actions([
            dividend('15 May 2026', '1 May 2026'),
            dividend('24 Nov 2026', '18 Nov 2026'),
            dividend('25 Nov 2026', '19 Nov 2026'),
            dividend('14 Dec 2026', '18 Nov 2026'),
        ], CUTOFF.date())
        self.assertEqual(result['last_dividend']['date'], '2026-05-15')
        self.assertEqual([row['date'] for row in result['upcoming']], ['2026-11-24'])

    def test_provider_failure_does_not_look_like_empty_success(self):
        result = sbi.run(None, CUTOFF, rss_fetch=lambda _: b'<html>blocked</html>')
        self.assertEqual(result['news']['status'], 'UNAVAILABLE')
        self.assertEqual(result['actions']['status'], 'UNAVAILABLE')
        self.assertEqual(result['filings']['board_meetings']['status'], 'UNAVAILABLE')

    def test_news_one_page_and_instrument_identity(self):
        class API:
            def get(self, path, params, **kwargs):
                self.keys = params['instrument_keys']
                return {'data': {sbi.INSTRUMENT: [
                    {'heading': 'SBI headline at cutoff',
                     'published_time': int(CUTOFF.timestamp()*1000),
                     'article_link': 'https://upstox.com/news/fixture/'}]},
                    'metadata': {'page': {'page_number': 1, 'page_size': 100,
                                          'total_pages': 1, 'total_records': 1}}}
        api = API()
        result = sbi.news(api, CUTOFF, observed_at=CUTOFF)
        self.assertEqual(api.keys, 'NSE_EQ|INE062A01020')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['articles'][0]['title'], 'SBI headline at cutoff')
