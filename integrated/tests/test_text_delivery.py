import datetime as dt
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from integrated.cloud_review import make_review
from integrated.telegram import send_text
from integrated.text_report import format_report


class FakeResponse:
    def __init__(self, data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return json.dumps(self.data).encode()


class FakeOpener:
    def __init__(self,message):self.message=message;self.methods=[]
    def open(self,request,timeout):
        method=request.full_url.rsplit('/',1)[-1]
        self.methods.append(method)
        data=json.loads(request.data)
        if method=='getMe':return FakeResponse({'ok':True,'result':{'id':7,'username':'NSEMorningReportbot'}})
        if method=='getChat':return FakeResponse({'ok':True,'result':{'id':-123,'type':'channel','title':'NSE Morning Report'}})
        if method=='getChatMember':
            result={'status':'administrator','can_post_messages':True} if data['user_id']==7 else {'status':'creator','user':{'id':456}}
            return FakeResponse({'ok':True,'result':result})
        if method=='sendMessage':return FakeResponse({'ok':True,'result':{'message_id':10,'chat':{'id':-123},'text':self.message}})
        raise AssertionError(method)


class TextDeliveryTests(unittest.TestCase):
    def test_recent_news_and_missing_data_are_visible(self):
        snapshot=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        snapshot['news'].append({'title':'Old story','url':'https://example.com/old','published_IST':'2026-10-26T06:30:00+05:30'})
        message=format_report(snapshot,make_review(snapshot))
        self.assertIn('1/6 signals',message)
        self.assertIn('Negative factors:',message)
        self.assertIn('Recent news (12h to 07:45 IST):',message)
        self.assertNotIn('Old story',message)
        self.assertEqual(message.count('Synthetic headline'),1)
        self.assertIn('N/A',message)
        self.assertLessEqual(len(message),4096)

    def test_verified_text_send_once(self):
        opener=FakeOpener('Morning update')
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'1','TELEGRAM_BOT_TOKEN':'123:synthetic_token','TELEGRAM_CHANNEL_ID':'-123','TELEGRAM_CHAT_ID':'456'}):
            result=send_text('Morning update',opener)
        self.assertEqual(result['status'],'SENT')
        self.assertEqual(opener.methods.count('sendMessage'),1)

    def test_rerun_cannot_send(self):
        opener=FakeOpener('Morning update')
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}),self.assertRaises(SystemExit):
            send_text('Morning update',opener)
        self.assertEqual(opener.methods,[])

    def test_unconfirmed_send_does_not_retry(self):
        class Uncertain(FakeOpener):
            def open(self,request,timeout):
                if request.full_url.endswith('/sendMessage'):
                    self.methods.append('sendMessage')
                    raise TimeoutError('synthetic timeout')
                return super().open(request,timeout)
        opener=Uncertain('Morning update')
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'1','TELEGRAM_BOT_TOKEN':'123:synthetic_token','TELEGRAM_CHANNEL_ID':'-123','TELEGRAM_CHAT_ID':'456'}),self.assertRaises(SystemExit):
            send_text('Morning update',opener)
        self.assertEqual(opener.methods.count('sendMessage'),1)

    def test_pdf_push_trigger_removed(self):
        workflow=Path('.github/workflows/integrated-deliver.yml').read_text()
        self.assertNotIn('  push:',workflow)


if __name__=='__main__':unittest.main()
