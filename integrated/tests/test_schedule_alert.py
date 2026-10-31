import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integrated.schedule_gate import resolve
from integrated.delivery_alert import decision, send_private

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class ScheduleGateTests(unittest.TestCase):
    def test_preflight_then_collect_same_ist_day(self):
        day = '2026-10-29'
        early = dt.datetime(2026, 10, 29, 7, 35, tzinfo=IST)
        cutoff = early.replace(minute=45)
        self.assertEqual(resolve(early, 'workflow_dispatch', 'preflight', day),
                         {'day': day, 'mode': 'preflight', 'collect': False})
        self.assertTrue(resolve(cutoff, 'workflow_dispatch', 'collect', day)['collect'])
        self.assertFalse(resolve(early, 'schedule')['collect'])

    def test_external_mode_and_date_are_bounded(self):
        now = dt.datetime(2026, 10, 29, 7, 45, tzinfo=IST)
        self.assertTrue(resolve(now, 'repository_dispatch', payload_mode='collect',
                                payload_date='2026-10-29')['collect'])
        for mode, day in [('send', '2026-10-29'), ('collect', '2026-10-28'),
                          ('collect', '$(date)')]:
            with self.subTest(mode=mode, day=day), self.assertRaises(ValueError):
                resolve(now, 'repository_dispatch', payload_mode=mode, payload_date=day)

    def test_late_collection_is_skipped(self):
        now = dt.datetime(2026, 10, 29, 8, 11, tzinfo=IST)
        self.assertFalse(resolve(now, 'schedule')['collect'])
        late = dt.datetime(2026, 10, 30, 14, 7, tzinfo=IST)
        self.assertFalse(resolve(late, 'schedule')['collect'])


class PrivateAlertTests(unittest.TestCase):
    def test_only_missing_verified_delivery_alerts(self):
        now = dt.datetime(2026, 10, 29, 8, 20, tzinfo=IST)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(decision(root, now.replace(minute=19)), 'TOO_EARLY')
            self.assertEqual(decision(root, now), 'ALERT')
            ledger = root / 'delivery_ledger' / '2026-10-29.json'
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({'report_date': '2026-10-29', 'status': 'RESERVED_UNCERTAIN_UNTIL_VERIFIED'}))
            self.assertEqual(decision(root, now), 'ALERT')
            ledger.write_text(json.dumps({'report_date': '2026-10-29', 'status': 'SENT'}))
            self.assertEqual(decision(root, now), 'ALERT')
            ledger.write_text(json.dumps({'report_date': '2026-10-28', 'status': 'SENT',
                                          'pdf_sha256': 'a' * 64}))
            self.assertEqual(decision(root, now), 'ALERT')
            ledger.write_text(json.dumps({'report_date': '2026-10-29', 'status': 'SENT',
                                          'pdf_sha256': 'a' * 64}))
            self.assertEqual(decision(root, now), 'DELIVERED')
            ledger.unlink()
            handoff = root / 'handoff' / '2026-10-29.json'
            handoff.parent.mkdir()
            handoff.write_text(json.dumps({'report_date': '2026-10-29', 'trading_day': 'CLOSED'}))
            self.assertEqual(decision(root, now), 'CLOSED')

    def test_private_alert_is_mocked_and_uses_private_chat(self):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return io.BytesIO(self.body)
            def __exit__(self, *args): return False
        class Opener:
            def __init__(self): self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                if request.full_url.endswith('/getChat'):
                    return Response(b'{"ok":true,"result":{"id":123456,"type":"private"}}')
                return Response(b'{"ok":true,"result":{}}')
        opener = Opener()
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': '123:fixture-token',
                                      'TELEGRAM_CHAT_ID': '123456'}, clear=False):
            send_private('2026-10-29', opener)
        self.assertEqual(len(opener.requests), 2)
        body = json.loads(opener.requests[1].data)
        self.assertEqual(body['chat_id'], '123456')
        self.assertIn('08:20 IST', body['text'])

    def test_non_private_destination_never_receives_message(self):
        class Response:
            def __enter__(self): return io.BytesIO(b'{"ok":true,"result":{"id":123456,"type":"group"}}')
            def __exit__(self, *args): return False
        class Opener:
            def __init__(self): self.calls = 0
            def open(self, request, timeout):
                self.calls += 1
                return Response()
        opener = Opener()
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': '123:fixture-token',
                                      'TELEGRAM_CHAT_ID': '123456'}, clear=False):
            with self.assertRaises(RuntimeError): send_private('2026-10-29', opener)
        self.assertEqual(opener.calls, 1)


if __name__ == '__main__': unittest.main()
