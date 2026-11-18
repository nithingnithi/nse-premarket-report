"""Read-only NSE CM MCP fallback for dated cash-index closes.

The documented streamable-HTTP endpoint is used only after Upstox misses an
NSE index. A Codex plugin connection is not shared with GitHub Actions.
"""
import datetime as dt
import http.cookiejar
import json
import math
import time
import urllib.request
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
URL = "https://mcp.nseindia.in/cmmkt/mcp"
MAX_BODY = 2_000_000
TARGETS = {
    "NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK",
    "MIDCAP100": "NIFTY MIDCAP 100", "SMALLCAP100": "NIFTY SMLCAP 100",
    "PSU Bank": "NIFTY PSU BANK", "Realty": "NIFTY REALTY",
    "Auto": "NIFTY AUTO", "FMCG": "NIFTY FMCG",
    "Energy": "NIFTY ENERGY", "IT": "NIFTY IT",
}


class CheckFailure(Exception):
    """Fixed diagnostics safe to retain in the compact snapshot."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _reply(response, request_id):
    content_type = response.headers.get_content_type()
    if content_type == "application/json":
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise CheckFailure("NSE MCP response exceeded size limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CheckFailure("NSE MCP response was not JSON") from None
    elif content_type == "text/event-stream":
        fields, size, deadline = [], 0, time.monotonic() + 20
        while time.monotonic() < deadline:
            raw = response.readline(MAX_BODY + 1)
            size += len(raw)
            if size > MAX_BODY:
                raise CheckFailure("NSE MCP response exceeded size limit")
            if not raw:
                break
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line and fields:
                    value = json.loads("\n".join(fields))
                    fields = []
                    if isinstance(value, dict) and value.get("id") == request_id:
                        break
                elif line.startswith("data:"):
                    fields.append(line[5:].removeprefix(" "))
            except (ValueError, UnicodeError):
                raise CheckFailure("NSE MCP event stream was malformed") from None
        else:
            raise CheckFailure("NSE MCP event stream timed out")
        if not raw:
            raise CheckFailure("NSE MCP event stream ended without a response")
    else:
        raise CheckFailure("NSE MCP response content type changed")
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
            or value.get("id") != request_id or "error" in value
            or not isinstance(value.get("result"), dict)):
        raise CheckFailure("NSE MCP returned an invalid JSON-RPC result")
    return value["result"]


class Client:
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
        self.session = None
        self.version = None
        self.request_id = 0

    def send(self, method, params=None, notification=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.request_id += 1
            message["id"] = self.request_id
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": "NSEMorningReport/0.1 (read-only personal report)"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        request = urllib.request.Request(URL, data=json.dumps(message).encode(),
                                         headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=15) as response:
                if method == "initialize":
                    self.session = response.headers.get("Mcp-Session-Id")
                if notification:
                    if response.status != 202:
                        raise CheckFailure("NSE MCP initialization was not accepted")
                    return None
                return _reply(response, self.request_id)
        except CheckFailure:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(code, int):
                raise CheckFailure("NSE MCP HTTP " + str(code)) from None
            raise CheckFailure("NSE MCP connection or TLS request failed") from None

    def indices(self):
        initialized = self.send("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "NSEMorningReport", "version": "0.1"},
        })
        self.version = initialized.get("protocolVersion")
        if self.version not in ("2025-03-26", "2025-06-18", "2025-11-25"):
            raise CheckFailure("NSE MCP protocol version is unsupported")
        self.send("notifications/initialized", notification=True)
        result = self.send("tools/call", {"name": "cm_get_live_indices",
                                          "arguments": {"group": "all", "nameFilter": ""}})
        if result.get("isError"):
            raise CheckFailure("NSE MCP index tool returned an error")
        data = result.get("structuredContent")
        if not isinstance(data, dict):
            blocks = result.get("content")
            texts = [x.get("text") for x in blocks if isinstance(x, dict)
                     and x.get("type") == "text"] if isinstance(blocks, list) else []
            if len(texts) != 1 or not isinstance(texts[0], str):
                raise CheckFailure("NSE MCP index payload was missing")
            try:
                data = json.loads(texts[0])
            except (ValueError, UnicodeError):
                raise CheckFailure("NSE MCP index payload was not JSON") from None
        return data

    def close(self):
        if not self.session:
            return
        request = urllib.request.Request(URL, method="DELETE", headers={
            "Mcp-Session-Id": self.session,
            "MCP-Protocol-Version": self.version or "2025-03-26",
        })
        try:
            with self.opener.open(request, timeout=5):
                pass
        except Exception:
            pass  # Session cleanup cannot change the data result.


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise CheckFailure("NSE MCP index number was missing or invalid")
    return Decimal(str(value))


def validate_indices(data, sessions, cutoff, session_close):
    if (not isinstance(sessions, list) or len(sessions) < 2 or
            sessions[0] <= sessions[1] or sessions[0] >= cutoff.date().isoformat()):
        raise CheckFailure("Two completed NSE sessions are required for MCP fallback")
    try:
        market_close = dt.datetime.fromisoformat(session_close)
    except (TypeError, ValueError):
        raise CheckFailure("NSE session close time was missing") from None
    if (market_close.tzinfo is None or market_close.utcoffset() != dt.timedelta(hours=5, minutes=30)
            or market_close.date().isoformat() != sessions[0] or market_close > cutoff):
        raise CheckFailure("NSE session close time was inconsistent")
    if not isinstance(data, dict) or data.get("error") or data.get("warning") or data.get("warnings"):
        raise CheckFailure("NSE MCP index payload reported an error or warning")
    try:
        stamp = dt.datetime.strptime(data["nseTimestamp"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except (KeyError, TypeError, ValueError):
        raise CheckFailure("NSE MCP index timestamp was missing or invalid") from None
    if stamp.date().isoformat() != sessions[0] or stamp < market_close or stamp > cutoff:
        raise CheckFailure("NSE MCP index snapshot was not the previous completed session")
    groups = data.get("indices")
    if not isinstance(groups, dict):
        raise CheckFailure("NSE MCP index groups were missing")
    if (type(data.get("returned")) is not int or
            data["returned"] != sum(len(group) for group in groups.values() if isinstance(group, list))):
        raise CheckFailure("NSE MCP index count or group schema changed")
    wanted = set(TARGETS.values())
    found = {}
    for group in groups.values():
        if not isinstance(group, list):
            raise CheckFailure("NSE MCP index group schema changed")
        for row in group:
            if not isinstance(row, dict):
                raise CheckFailure("NSE MCP index row schema changed")
            name = row.get("indexName")
            if name in wanted:
                found.setdefault(name, []).append(row)
    output = {}
    for key, name in TARGETS.items():
        rows = found.get(name, [])
        if len(rows) != 1:
            output[key] = {"status": "UNAVAILABLE", "reason": "NSE MCP index missing or duplicated"}
            continue
        row = rows[0]
        try:
            row_time = dt.datetime.strptime(row["timeVal"], "%d-%b-%Y %H:%M").replace(tzinfo=IST)
            if row_time.date() != stamp.date() or row_time < market_close or row_time > cutoff:
                raise CheckFailure("NSE MCP index row was stale or after cutoff")
            close = _number(row.get("last")); previous = _number(row.get("previousClose"))
            change = _number(row.get("change")); percentage = _number(row.get("percChange"))
            if close <= 0 or previous <= 0 or abs(close - previous - change) > Decimal("0.02"):
                raise CheckFailure("NSE MCP index close/change was inconsistent")
            calculated = (close - previous) * 100 / previous
            if abs(calculated - percentage) > Decimal("0.02"):
                raise CheckFailure("NSE MCP index percentage was inconsistent")
            output[key] = {"status": "PASS", "source": "NSE CM Market MCP",
                           "source_asof_IST": stamp.isoformat(), "latest_date": sessions[0],
                           "close": str(close), "previous_close": str(previous),
                           "change": str(close - previous), "change_pct": str(calculated),
                           "unit": "index points", "previous_close_date": "N/A: not supplied by MCP"}
        except (KeyError, TypeError, ValueError, CheckFailure) as exc:
            output[key] = {"status": "UNAVAILABLE", "reason": (
                str(exc) if isinstance(exc, CheckFailure) else "NSE MCP index row schema changed")}
    return output


def fetch_indices(sessions, cutoff, session_close):
    client = Client()
    try:
        return validate_indices(client.indices(), sessions, cutoff, session_close)
    finally:
        client.close()
