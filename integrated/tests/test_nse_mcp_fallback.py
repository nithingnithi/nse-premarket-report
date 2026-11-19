"""Offline fixtures for the dated NSE cash-index MCP fallback."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pypdf import PdfReader
from integrated.adapters import nse_mcp
from integrated.collect import supplement_nse_indices
from integrated.deliver import with_breadth
from integrated.render import render

IST = ZoneInfo("Asia/Kolkata")
CUTOFF = dt.datetime(2026, 11, 18, 7, 45, tzinfo=IST)
SESSIONS = ["2026-11-17", "2026-11-16"]
SESSION_CLOSE = "2026-11-17T15:30:00+05:30"


def payload():
    return {"nseTimestamp": "17-Nov-2026 15:30:00", "returned": 1, "indices": {"broad": [
        {"indexName": "NIFTY MIDCAP 100", "timeVal": "17-Nov-2026 15:40",
         "last": 110, "previousClose": 100, "change": 10, "percChange": 10},
    ]}}


class MCPFallbackTests(unittest.TestCase):
    def test_breadth_calls_the_documented_tool_and_rejects_fallback_date(self):
        data={'date':SESSIONS[0],'advances':10,'declines':20,'unchanged':1,'total_stocks':31}
        with patch.object(nse_mcp,'Client') as client:
            instance=client.return_value
            instance.call_tool.return_value=data
            self.assertEqual(nse_mcp.fetch_breadth(SESSIONS[0],CUTOFF),{'status':'PASS',**data})
            client.assert_called_once_with(url=nse_mcp.BHAVCOPY_URL,timeout=3)
            instance.call_tool.assert_called_once_with('get_market_breadth',{'date':SESSIONS[0]})
            instance.close.assert_called_once()
        for bad,reason in (({'date':SESSIONS[1]},'different trading session'),
                           ({'total_stocks':32},'counts missing or inconsistent'),
                           ({'advances':True},'counts missing or inconsistent')):
            with self.assertRaisesRegex(nse_mcp.CheckFailure,reason):
                nse_mcp.validate_breadth({**data,**bad},SESSIONS[0])

    def test_breadth_is_opt_in_and_leaves_the_saved_snapshot_alone(self):
        snapshot={'completed_sessions':{'NSE':SESSIONS},'cutoff_IST':CUTOFF.isoformat()}
        with patch.object(nse_mcp,'fetch_breadth',side_effect=nse_mcp.CheckFailure('Provider unavailable')) as fetch:
            self.assertIs(with_breadth(snapshot,enabled=True,dry=True),snapshot)
            self.assertIs(with_breadth(snapshot,enabled=False,dry=False),snapshot)
            fetch.assert_not_called()
            report=with_breadth(snapshot,enabled=True,dry=False)
            fetch.assert_called_once_with(SESSIONS[0],CUTOFF)
            self.assertEqual(report['breadth'],{'status':'UNAVAILABLE','reason':'Provider unavailable'})
            self.assertNotIn('breadth',snapshot)

    def test_only_exact_previous_session_is_used(self):
        rows = nse_mcp.validate_indices(payload(), SESSIONS, CUTOFF, SESSION_CLOSE)
        self.assertEqual(rows["MIDCAP100"]["close"], "110")
        self.assertEqual(rows["MIDCAP100"]["source"], "NSE CM Market MCP")
        self.assertEqual(rows["NIFTY"]["status"], "UNAVAILABLE")
        for stamp in ("16-Nov-2026 15:30:00", "18-Nov-2026 09:15:00"):
            bad = payload(); bad["nseTimestamp"] = stamp
            with self.assertRaisesRegex(nse_mcp.CheckFailure, "not the previous completed session"):
                nse_mcp.validate_indices(bad, SESSIONS, CUTOFF, SESSION_CLOSE)
        with self.assertRaisesRegex(nse_mcp.CheckFailure, "not the previous completed session"):
            nse_mcp.validate_indices(payload(), SESSIONS, CUTOFF,
                                     "2026-11-17T15:31:00+05:30")

    def test_invalid_rows_and_duplicates_do_not_become_zero(self):
        for update in ({"last": None}, {"previousClose": 0}, {"change": 9},
                       {"percChange": 9}, {"timeVal": "18-Nov-2026 07:45"}):
            bad = payload(); bad["indices"]["broad"][0].update(update)
            row = nse_mcp.validate_indices(bad, SESSIONS, CUTOFF, SESSION_CLOSE)["MIDCAP100"]
            self.assertEqual(row["status"], "UNAVAILABLE")
            self.assertNotIn("close", row)
        duplicate = payload()
        duplicate["indices"]["sectoral"] = [dict(duplicate["indices"]["broad"][0])]
        duplicate["returned"] = 2
        self.assertEqual(nse_mcp.validate_indices(duplicate, SESSIONS, CUTOFF, SESSION_CLOSE)["MIDCAP100"]["status"], "UNAVAILABLE")

    def test_warning_or_missing_timestamp_withholds_all_rows(self):
        for update in ({"warning": "stale"}, {"nseTimestamp": None}):
            bad = payload(); bad.update(update)
            with self.assertRaises(nse_mcp.CheckFailure):
                nse_mcp.validate_indices(bad, SESSIONS, CUTOFF, SESSION_CLOSE)

    def test_fallback_preserves_upstox_and_never_uses_mcp_for_vix_or_sensex(self):
        spot = {"NIFTY": {"status": "PASS", "close": "101"},
                "MIDCAP100": {"status": "UNAVAILABLE", "reason": "Upstox no candle"},
                "SENSEX": {"status": "UNAVAILABLE", "reason": "BSE no candle"}}
        sectors = {"IT": {"status": "UNAVAILABLE", "reason": "Upstox no candle"}}
        supplied = {"MIDCAP100": nse_mcp.validate_indices(payload(), SESSIONS, CUTOFF, SESSION_CLOSE)["MIDCAP100"]}
        status = supplement_nse_indices(spot, sectors, SESSIONS, CUTOFF, SESSION_CLOSE, lambda *_: supplied)
        self.assertEqual(spot["NIFTY"]["close"], "101")
        self.assertEqual(spot["MIDCAP100"]["close"], "110")
        self.assertEqual(spot["MIDCAP100"]["upstox_reason"], "Upstox no candle")
        self.assertEqual(spot["SENSEX"]["status"], "UNAVAILABLE")
        self.assertEqual(status["used"], ["MIDCAP100"])
        self.assertEqual(sectors["IT"]["status"], "UNAVAILABLE")

    def test_failed_mcp_keeps_missing_rows_and_reason(self):
        spot = {"MIDCAP100": {"status": "UNAVAILABLE", "reason": "Upstox no candle"}}
        def fail(*_):
            raise nse_mcp.CheckFailure("NSE MCP HTTP 404")
        status = supplement_nse_indices(spot, {}, SESSIONS, CUTOFF, SESSION_CLOSE, fail)
        self.assertEqual(status["status"], "UNAVAILABLE")
        self.assertEqual(spot["MIDCAP100"]["mcp_fallback_reason"], "NSE MCP HTTP 404")
        self.assertEqual(spot["MIDCAP100"]["status"], "UNAVAILABLE")
        status=supplement_nse_indices(spot,{},SESSIONS,CUTOFF,SESSION_CLOSE,
                                      lambda *_: (_ for _ in ()).throw(ValueError('sensitive detail')))
        self.assertEqual(status['reason'],'NSE MCP request or validation failed')

    def test_all_upstox_rows_skip_mcp_entirely(self):
        spot={name:{'status':'PASS'} for name in ('NIFTY','BANKNIFTY','MIDCAP100','SMALLCAP100')}
        sectors={name:{'status':'PASS'} for name in ('PSU Bank','Realty','Auto','FMCG','Energy','IT')}
        result=supplement_nse_indices(spot,sectors,SESSIONS,CUTOFF,SESSION_CLOSE,
                                      lambda *_: self.fail('MCP should not be called'))
        self.assertEqual(result['status'],'NOT_NEEDED')

    def test_pdf_names_the_mcp_fallback_and_its_source_time(self):
        snapshot=json.loads(Path('integrated/tests/fixtures/snapshot.json').read_text())
        review=json.loads(Path('integrated/tests/fixtures/review.json').read_text())
        snapshot['completed_sessions']={'NSE':['2026-11-17']}
        snapshot['spot']={'MIDCAP100':nse_mcp.validate_indices(payload(),SESSIONS,CUTOFF,SESSION_CLOSE)['MIDCAP100']}
        snapshot['cm_market_fallback']={'status':'PASS','used':['MIDCAP100']}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.pdf';render(snapshot,review,path)
            self.assertIn('NSE MCP supplied 1 dated closes at 17 Nov 15:30 IST.',
                          PdfReader(path).pages[0].extract_text())

    def test_client_uses_documented_endpoint_and_session(self):
        class Headers:
            def __init__(self, session=None):self.session=session
            def get(self, key):return self.session if key == "Mcp-Session-Id" else None
            def get_content_type(self):return "application/json"
        class Response:
            status=202
            def __init__(self, body, session=None):self.body=io.BytesIO(json.dumps(body).encode());self.headers=Headers(session)
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self, limit):return self.body.read(limit)
        class Opener:
            def __init__(self):self.calls=[]
            def open(self, request, timeout):
                self.calls.append((request.full_url, json.loads(request.data), request.headers))
                method=self.calls[-1][1]["method"]
                if method=="initialize":
                    return Response({"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}},"fixture-session")
                if method=="notifications/initialized":return Response({})
                return Response({"jsonrpc":"2.0","id":2,"result":{"content":[
                    {"type":"text","text":json.dumps(payload())}]}})
        opener=Opener();data=nse_mcp.Client(opener).indices()
        self.assertEqual(data,payload())
        self.assertEqual([x[1]["method"] for x in opener.calls],
                         ["initialize","notifications/initialized","tools/call"])
        self.assertTrue(all(x[0]==nse_mcp.URL for x in opener.calls))
        self.assertEqual(opener.calls[2][1]["params"]["name"],"cm_get_live_indices")
        self.assertEqual(opener.calls[2][2]["Mcp-session-id"],"fixture-session")
        self.assertTrue(all("Authorization" not in x[2] for x in opener.calls))


if __name__ == "__main__":
    unittest.main()
