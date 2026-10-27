"""Captured-data replay checks; no network or Telegram calls."""

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader
from nse_report.calculations import DataError, MissingData
from nse_report.dry_run import analyze, render

SNAPSHOT = Path(__file__).resolve().parents[1] / "data/dry-run/2026-10-27.json"


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(SNAPSHOT.read_text(), parse_float=Decimal)

    def test_saved_calculations_and_missing_signal_reasons(self):
        result = analyze(self.data)
        self.assertEqual([r["classification"] for r in result["futures"]], ["SHORT_COVERING"] * 2)
        self.assertEqual(result["futures"][0]["price_change"], Decimal("198.2"))
        self.assertEqual(result["futures"][0]["oi_change"], -101140)
        self.assertEqual(result["fii"]["net"], -277105)
        self.assertEqual(result["cash"]["FII"]["net_5_sessions"], Decimal("-4159.86"))
        self.assertEqual(result["cash"]["DII"]["net_5_sessions"], Decimal("13551.76"))
        self.assertEqual((result["score"]["score"], result["score"]["available"], result["score"]["score_range"]), (0, 2, (-4, 4)))
        self.assertEqual(result["score"]["bias"], "INSUFFICIENT DATA TO ASSIGN FINAL BIAS")

    def test_dry_run_only(self):
        self.data["mode"] = "LIVE"
        with self.assertRaises(ValueError):
            analyze(self.data)

    def test_wrong_cutoff_timezone_or_date_fails(self):
        for cutoff in ("2026-10-27T08:00:00+05:30", "2026-10-27T07:45:00+00:00", "2026-10-26T07:45:00+05:30"):
            value = copy.deepcopy(self.data)
            value["cutoff_IST"] = cutoff
            with self.assertRaises(ValueError):
                analyze(value)

    def test_current_session_leakage_fails(self):
        self.data["provider_completed_sessions"]["NFO"][0] = "2026-10-27"
        with self.assertRaises(ValueError):
            analyze(self.data)

    def test_missing_future_oi_never_zero_fills(self):
        self.data["futures"][0]["daily_observations"][0]["oi_raw"] = None
        with self.assertRaises(MissingData):
            analyze(self.data)

    def test_duplicate_cash_session_fails(self):
        self.data["cash"][0]["observations"].append(self.data["cash"][0]["observations"][0])
        with self.assertRaises(DataError):
            analyze(self.data)

    def test_stale_fii_date_fails(self):
        self.data["fii_positions"][0]["date"] = "2026-10-22"
        with self.assertRaises(ValueError):
            analyze(self.data)

    def test_render_two_pages_bias_text_and_source_links(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "test.pdf"
            render(self.data, analyze(self.data), target)
            pdf = PdfReader(target)
            self.assertEqual(len(pdf.pages), 2)
            first, second = [p.extract_text() for p in pdf.pages]
            for token in ("DRY RUN", "INSUFFICIENT DATA TO ASSIGN FINAL BIAS", "2/6", "[-4, +4]", "UNKNOWN / unverified"):
                self.assertIn(token, first)
            for token in ("-4,159.86", "+13,551.76", "News: N/A", "no unattended AI API"):
                self.assertIn(token, second)
            links = [a.get_object().get("/A", {}).get("/URI") for p in pdf.pages for a in p.get("/Annots", [])]
            self.assertEqual(len(links), 8)
            self.assertTrue(all(str(url).startswith("https://") for url in links))

    def test_untrusted_text_is_literal(self):
        self.data["review"]["notes"][0] = "Literal <b>not markup</b> & text"
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "test.pdf"
            render(self.data, analyze(self.data), target)
            self.assertIn("<b>not markup</b> & text", PdfReader(target).pages[0].extract_text())

    def test_unsafe_source_link_is_rejected(self):
        self.data["sources"][0]["url"] = 'https://example.test/" bad'
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            render(self.data, analyze(self.data), Path(temp) / "test.pdf")


if __name__ == "__main__":
    unittest.main()
