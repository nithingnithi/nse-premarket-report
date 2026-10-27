"""Offline Telegram response simulations; no real tokens or network requests."""

import base64
from contextlib import redirect_stdout
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/dry-run-report.yml"


def load_delivery():
    code = WORKFLOW.read_text().split("          python3 - <<'PY'\n", 1)[1].rsplit("          PY\n", 1)[0]
    code = "\n".join(line[10:] for line in code.splitlines())
    namespace = {"__name__": "offline_delivery_test"}
    exec(compile(code, str(WORKFLOW), "exec"), namespace)
    return namespace


def response(result):
    return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_delivery()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.summary = Path(self.temp.name) / "summary.md"
        # Deliberately invented, syntactically plausible test-only credentials.
        self.env = {"GITHUB_RUN_ATTEMPT": "1", "TELEGRAM_BOT_TOKEN": "123:synthetic_not_a_real_token",
                    "TELEGRAM_CHAT_ID": "1", "GITHUB_STEP_SUMMARY": str(self.summary)}

    def replies(self):
        return [response({"is_bot": True, "username": "NSEMorningReportbot"}),
                response({"id": 1, "type": "private"}),
                response({"chat": {"id": 1, "type": "private"}, "document": {"file_id": "synthetic_file"}, "message_id": 1}),
                response({"file_path": "documents/synthetic.pdf"}),
                io.BytesIO(base64.b64decode(self.module["PDF_BASE64"]))]

    def run_main(self, replies):
        opener = Mock()
        self.opener = opener
        opener.open.side_effect = replies
        with patch.dict(os.environ, self.env, clear=True), patch("urllib.request.build_opener", return_value=opener), redirect_stdout(io.StringIO()):
            self.module["main"]()
        return opener

    def test_success_only_after_downloaded_hash_matches(self):
        opener = self.run_main(self.replies())
        self.assertEqual(opener.open.call_count, 5)
        summary = self.summary.read_text()
        self.assertIn("downloaded copy matches", summary)
        self.assertNotIn(self.env["TELEGRAM_BOT_TOKEN"], summary)
        self.assertIn("does not yet test fresh data collection", summary)

    def test_second_attempt_never_calls_telegram(self):
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        with patch.dict(os.environ, self.env, clear=True), patch("urllib.request.build_opener") as build:
            with self.assertRaisesRegex(SystemExit, "Repeat attempts are blocked"):
                self.module["main"]()
            build.assert_not_called()

    def test_corrupt_embedded_pdf_never_calls_telegram(self):
        self.module["PDF_SHA256"] = "0" * 64
        with patch.dict(os.environ, self.env, clear=True), patch("urllib.request.build_opener") as build:
            with self.assertRaisesRegex(SystemExit, "integrity check"):
                self.module["main"]()
            build.assert_not_called()

    def test_uncertain_upload_is_not_retried_or_reported_success(self):
        replies = self.replies()[:2] + [OSError("synthetic transport failure")]
        with self.assertRaisesRegex(SystemExit, "uncertain"):
            self.run_main(replies)
        self.assertEqual(self.opener.open.call_count, 3)
        self.assertFalse(self.summary.exists())

    def test_wrong_download_hash_is_not_reported_success(self):
        replies = self.replies()[:-1] + [io.BytesIO(b"different file")]
        with self.assertRaisesRegex(SystemExit, "did not match"):
            self.run_main(replies)
        self.assertFalse(self.summary.exists())

    def test_wrong_bot_is_not_sent_document(self):
        with self.assertRaisesRegex(SystemExit, "does not belong"):
            self.run_main([response({"is_bot": True, "username": "OTHER"})])
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertFalse(self.summary.exists())


if __name__ == "__main__":
    unittest.main()
