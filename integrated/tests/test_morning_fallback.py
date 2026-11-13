import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from integrated.morning_fallback import decision, run
from integrated.review import IST


class MorningFallbackTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 16, 8, 6, tzinfo=IST)

    def test_missing_handoff_sends_honest_status_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sent = []
            commits = []
            def sender(message):
                sent.append(message)
                return {'status': 'SENT', 'text_sha256': 'a' * 64, 'message_id': 1}
            result = run(root, self.now, dry_run=False,
                         commit=lambda path: commits.append(path.read_text()),
                         sender=sender, clock=lambda: self.now)
            self.assertEqual(result, 'SENT')
            self.assertEqual(len(sent), 1)
            self.assertIn('Market data: N/A', sent[0])
            self.assertIn('trading session unverified', sent[0])
            self.assertEqual(json.loads(commits[0])['status'], 'RESERVED_UNCERTAIN_UNTIL_VERIFIED')
            self.assertEqual(json.loads(commits[1])['status'], 'SENT')
            self.assertEqual(run(root, self.now, dry_run=False, sender=sender), 'SKIPPED')
            self.assertEqual(len(sent), 1)

    def test_closed_session_and_weekend_do_not_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'handoff').mkdir()
            (root / 'handoff/2026-11-16.json').write_text(json.dumps({
                'report_date': '2026-11-16', 'trading_day': 'CLOSED'}))
            self.assertIsNone(decision(root, self.now))
            self.assertIsNone(decision(root, self.now - dt.timedelta(days=1)))

    def test_late_run_never_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                run(root, self.now + dt.timedelta(minutes=5), dry_run=False)
            self.assertFalse((root / 'delivery_ledger').exists())

    def test_reservation_survives_uncertain_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def uncertain(_message):
                raise SystemExit('synthetic uncertainty')
            with self.assertRaises(SystemExit):
                run(root, self.now, dry_run=False, commit=lambda _path: None,
                    sender=uncertain, clock=lambda: self.now)
            ledger = json.loads((root / 'delivery_ledger/2026-11-16.json').read_text())
            self.assertEqual(ledger['status'], 'RESERVED_UNCERTAIN_UNTIL_VERIFIED')
            self.assertIsNone(decision(root, self.now))


if __name__ == '__main__':
    unittest.main()
