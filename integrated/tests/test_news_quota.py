import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from pypdf import PdfReader

from integrated.adapters import news
from integrated.collect import collect_news
from integrated.cloud_review import make_review
from integrated.render import render
from integrated.review import validate

IST=dt.timezone(dt.timedelta(hours=5,minutes=30))

class NewsQuotaTests(unittest.TestCase):
    def test_three_filtered_queries_one_page_each(self):
        class FixtureAPI:
            requests=0;stopped=False;max_requests=6;rate_limit_per_60_seconds=None
            def __init__(self):self.params=[]
            def get(self,params):
                self.requests+=1;self.params.append(params)
                return {'meta':{'found':0,'returned':0,'limit':3,'page':1},'data':{}}
        api=FixtureAPI();now=dt.datetime(2026,10,29,7,55,tzinfo=IST)
        report=news.run_checks(api,now)
        self.assertEqual(news.MAX_REQUESTS,6)
        self.assertEqual(api.requests,3)
        self.assertEqual([p['page'] for p in api.params],[1,1,1])
        self.assertEqual([p['limit'] for p in api.params],[3,3,3])
        self.assertEqual(api.params[0]['published_after'],'2026-10-28T14:15:00')
        self.assertEqual(api.params[0]['published_before'],'2026-10-29T02:15:01')
        self.assertIn('India',api.params[0]['search'])
        self.assertIn('Federal Reserve',api.params[1]['search'])
        self.assertIn('crude oil',api.params[2]['search'])
        self.assertEqual(report['http_attempts'],3)

    def test_http_429_stops_without_retry(self):
        api=news.API('fixture-token-123456',max_requests=6)
        class Reject:
            def open(self,*args,**kwargs):
                raise urllib.error.HTTPError('https://example.invalid',429,'rate limit',{},io.BytesIO(b'{}'))
        api.opener=Reject()
        with self.assertRaisesRegex(news.CheckFailure,'HTTP 429'):
            api.get({'search':'India','limit':3,'page':1})
        self.assertEqual(api.requests,1)
        self.assertTrue(api.stopped)

    def test_quota_exhaustion_is_timed_and_hides_partial_headlines(self):
        class QuotaAPI:
            requests=0;stopped=False;max_requests=6;rate_limit_per_60_seconds=None
            def get(self,params):
                self.requests+=1;self.stopped=True
                raise news.CheckFailure('HTTP 429: rolling 60-second rate limit reached')
        result=news.run_checks(QuotaAPI(),dt.datetime(2026,10,29,7,55,tzinfo=IST))
        self.assertEqual(result['status'],'QUOTA')
        self.assertEqual(result['http_attempts'],1)
        self.assertEqual(result['articles'],[])
        self.assertIsNotNone(dt.datetime.fromisoformat(result['quota_at_IST']).tzinfo)

    def test_dated_cache_reuse_spends_zero_requests(self):
        now=dt.datetime(2026,10,29,7,55,tzinfo=IST)
        cutoff=now.replace(minute=45)
        calls=[]
        def fetch():
            calls.append(1)
            return {'status':'PARTIAL','articles':[],'http_attempts':3}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'news-2026-10-29.json'
            first,state,used=collect_news(now.date(),cutoff,now,path,fetch)
            second,state2,used2=collect_news(now.date(),cutoff,now,path,fetch)
            self.assertEqual((state,used,state2,used2),('MISS',3,'HIT',0))
            self.assertEqual(len(calls),1)
            self.assertEqual(first,second)
            self.assertNotIn('api_token',path.read_text())

    def test_invalid_cache_does_not_spend_quota(self):
        now=dt.datetime(2026,10,29,7,55,tzinfo=IST)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'news-2026-10-29.json'
            path.write_text('{"schema_version":1,"report_date":"2026-10-28"}')
            result,state,used=collect_news(now.date(),now.replace(minute=45),now,path,
                lambda: self.fail('Cache corruption must not trigger another provider call'))
            self.assertEqual((result['status'],state,used),('UNAVAILABLE','INVALID',0))

    def test_quota_notice_in_two_page_pdf(self):
        snapshot=json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text())
        snapshot.update(news=[],news_status='QUOTA',news_quota_at_IST='2026-10-29T07:51:00+05:30')
        review=make_review(snapshot)
        validate(snapshot,review,dt.datetime(2026,10,28,8,0,tzinfo=IST),live=False)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'quota.pdf';render(snapshot,review,output)
            pdf=PdfReader(output)
            self.assertEqual(len(pdf.pages),2)
            self.assertIn('News unavailable (quota)',pdf.pages[0].extract_text())
            self.assertIn('07:51 IST',pdf.pages[0].extract_text())

if __name__=='__main__':unittest.main()
