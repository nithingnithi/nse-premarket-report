"""Manual Upstox futures/flow data probe. Credentials and raw responses stay hidden.

Documentation read: https://upstox.com/developer/api-documentation/
analytics-token/, instrument-search/, get-market-timings/, v3/get-historical-candle-data/,
v3/get-intra-day-candle-data/, get-fii-data/, get-dii-data/
This is an access/schema test, not the report's expiry policy or scoring model.
"""
import datetime as dt
from decimal import Decimal
import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
INDICES = {"Nifty": "NSE_INDEX|Nifty 50", "Bank Nifty": "NSE_INDEX|Nifty Bank",
           "India VIX": "NSE_INDEX|India VIX"}
PATHS = {"/market-quote/quotes", "/instruments/search", "/market/fii", "/market/dii"}
CLIENT_IDENTITY = "NSEMorningReport/0.1 (personal read-only market-data report)"


class CheckFailure(Exception):
    """Only fixed, credential-free messages may be raised here."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def number(value, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def http_error_diagnostic(error):
    """Expose only categorical markers and tightly validated Upstox codes.

    Never return response messages, URLs, headers, identifiers or raw body text.
    """
    try:
        raw = error.read(16_385)
        truncated = len(raw) > 16_384
        raw = raw[:16_384]
        text = raw.decode("utf-8", errors="replace")
        lower = text.lower()
        codes = set()
        kind = "HTML" if re.search(r"<(?:!doctype\s+html|html|head|body)\b", lower) else "OTHER"
        try:
            data = json.loads(text)
            kind = "JSON"
            if isinstance(data, dict):
                entries = [data]
                if isinstance(data.get("errors"), list):
                    entries.extend(data["errors"][:20])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    for field in ("errorCode", "error_code"):
                        code = entry.get(field)
                        if isinstance(code, str) and re.fullmatch(r"UDAPI[0-9]{1,8}", code):
                            codes.add(code)
        except (ValueError, TypeError):
            pass
        cloudflare = "cloudflare" in lower
        return ("body=" + kind + "; provider_codes=" + (",".join(sorted(codes)[:5]) or "none")
                + "; cloudflare_marker=" + ("yes" if cloudflare else "no")
                + "; error_1010_marker=" + ("yes" if cloudflare and re.search(r"\b1010\b", lower) else "no")
                + "; truncated=" + ("yes" if truncated else "no"))
    except Exception:
        return "body=UNREADABLE; provider_codes=none"


class API:
    def __init__(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 8192 or not re.fullmatch(r"[!-~]+", token):
            raise CheckFailure("UPSTOX_ANALYTICS_TOKEN is missing or malformed; save only the token value.")
        self.token = token
        self.auth_failed = False
        self.deadline = time.monotonic() + 360
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, path, params=None, version="v2", envelope=False):
        allowed = (version == "v2" and (path in PATHS or re.fullmatch(r"/market/timings/[0-9]{4}-[0-9]{2}-[0-9]{2}", path)))
        if version == "v3":
            allowed = bool(re.fullmatch(r"/historical-candle/NSE_FO%7C[0-9]+/days/1/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}", path)
                           or re.fullmatch(r"/historical-candle/intraday/NSE_FO%7C[0-9]+/days/1", path))
        if not allowed:
            raise CheckFailure("Request path is outside the read-only test allowlist.")
        request = urllib.request.Request(
            "https://api.upstox.com/" + version + path + ("?" + urllib.parse.urlencode(params) if params else ""),
            headers={"Accept": "application/json", "Authorization": "Bearer " + self.token,
                     "User-Agent": CLIENT_IDENTITY},
            method="GET",
        )
        for attempt in range(2):
            try:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise CheckFailure("Probe time budget exhausted.")
                with self.opener.open(request, timeout=min(15, remaining)) as response:
                    raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise CheckFailure("Response exceeded the size limit.")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get("status") != "success" or "data" not in payload:
                    raise CheckFailure("API returned an error or unexpected response envelope.")
                return payload if envelope else payload["data"]
            except urllib.error.HTTPError as exc:
                code = exc.code
                try:
                    diagnostic = http_error_diagnostic(exc)
                finally:
                    exc.close()
                if code in (401, 403):
                    self.auth_failed = True
                    raise CheckFailure("HTTP " + str(code) + ": request rejected; " + diagnostic) from None
                if not attempt and (code == 429 or 500 <= code <= 599):
                    time.sleep(2)
                    continue
                raise CheckFailure("HTTP " + str(code) + ": request failed; " + diagnostic) from None
            except (urllib.error.URLError, TimeoutError):
                if not attempt:
                    time.sleep(2)
                    continue
                raise CheckFailure("Network/TLS request failed; verification was not bypassed.") from None
            except (ValueError, UnicodeError):
                raise CheckFailure("Response was not valid JSON; details suppressed.") from None


def timestamp(value, now):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str) and re.fullmatch(r"[0-9]{13}", value):
            result = dt.datetime.fromtimestamp(int(value) / 1000, dt.timezone.utc)
        elif type(value) is int and 1_000_000_000_000 <= value < 10_000_000_000_000:
            result = dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc)
        elif isinstance(value, str):
            result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if result.tzinfo is None:
                return None  # Do not invent a timezone.
        else:
            return None
        if result > now + dt.timedelta(minutes=5):
            raise CheckFailure("Provider timestamp is in the future.")
        return result.astimezone(IST).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        return None


def quote(data, key, now):
    if not isinstance(data, dict):
        raise CheckFailure("Quote data is not an object.")
    matches = [row for row in data.values() if isinstance(row, dict)
               and row.get("instrument_token") == key]
    if len(matches) != 1 or not number(matches[0].get("last_price"), positive=True):
        raise CheckFailure("Quote identity, uniqueness or price validation failed.")
    row = matches[0]
    stamp = timestamp(row.get("timestamp"), now)
    return {"status": "PASS" if stamp else "PARTIAL", "last_price": row["last_price"],
            "quote_time_IST": stamp or "N/A",
            "last_trade_time_IST": timestamp(row.get("last_trade_time"), now) or "N/A"}


def decimal_text(value):
    return format(Decimal(str(value)), "f")


def require_number(value, positive=False):
    if not number(value, positive):
        raise CheckFailure("Required numeric data is missing, negative or nonfinite.")
    return Decimal(str(value))


def require_count(value):
    number_value = require_number(value)
    if number_value != number_value.to_integral_value():
        raise CheckFailure("A contract/OI count is fractional.")
    return int(number_value)


def epoch(value):
    if type(value) is not int or not 1_000_000_000_000 <= value < 10_000_000_000_000:
        raise CheckFailure("A provider epoch timestamp is missing or is not milliseconds.")
    try:
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).astimezone(IST)
    except (ValueError, OverflowError, OSError):
        raise CheckFailure("Provider timestamp is outside the supported range.") from None


def calendar_day(data, date):
    if not isinstance(data, list):
        raise CheckFailure("Market timings did not return an array.")
    sessions = {}
    for row in data:
        if not isinstance(row, dict):
            raise CheckFailure("Invalid market-timing row.")
        exchange = row.get("exchange")
        if exchange not in ("NSE", "NFO"):
            continue
        if exchange in sessions:
            raise CheckFailure("Ambiguous duplicate market-timing rows.")
        start, end = epoch(row.get("start_time")), epoch(row.get("end_time"))
        if start.date() != date or end.date() != date or start >= end:
            raise CheckFailure("Market session dates or start/end ordering are inconsistent.")
        sessions[exchange] = end
    return sessions


def completed_sessions(api, now):
    found = {"NSE": [], "NFO": []}
    closes = {}
    checked = []
    # Includes weekends: the provider can publish special trading sessions.
    for offset in range(15):
        day = now.date() - dt.timedelta(days=offset)
        checked.append(day.isoformat())
        sessions = calendar_day(api.get("/market/timings/" + day.isoformat()), day)
        for exchange, end in sessions.items():
            if end <= now:
                found[exchange].append(day.isoformat())
                closes[(exchange, day.isoformat())] = end.isoformat(timespec="seconds")
        if len(found["NSE"]) >= 5 and len(found["NFO"]) >= 2:
            return {"NSE": found["NSE"][:5], "NFO": found["NFO"][:2]}, closes, checked
    raise CheckFailure("Not enough completed cash/derivatives sessions within the bounded calendar search.")


def choose_future(rows, underlying, today):
    eligible, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise CheckFailure("Instrument search returned an invalid row.")
        if row.get("underlying_key") != underlying:
            continue  # Text search may return other index names; identity must match exactly.
        key = row.get("instrument_key")
        if (row.get("instrument_type") != "FUT" or row.get("segment") != "NSE_FO"
                or row.get("exchange") != "NSE" or row.get("underlying_type") != "INDEX"
                or not isinstance(key, str) or not re.fullmatch(r"NSE_FO\|[0-9]+", key)
                or key in seen):
            raise CheckFailure("Futures identity, market segment, type or duplicate validation failed.")
        seen.add(key)
        try:
            expiry = dt.date.fromisoformat(row["expiry"])
        except (KeyError, ValueError, TypeError):
            raise CheckFailure("Invalid futures expiry.") from None
        lot = require_count(row.get("lot_size"))
        if lot <= 0:
            raise CheckFailure("Futures lot size is not positive.")
        if expiry > today:
            eligible.append((expiry, key, lot))
    if not eligible:
        raise CheckFailure("No exact-index futures contract with an expiry after today was returned.")
    first = min(item[0] for item in eligible)
    matches = [item for item in eligible if item[0] == first]
    if len(matches) != 1:
        raise CheckFailure("The nearest futures expiry is ambiguous.")
    expiry, key, lot = matches[0]
    return {"instrument_key": key, "expiry": expiry.isoformat(), "lot_size": lot}


def search_future(api, name, underlying, today):
    rows = []
    for page in range(1, 4):
        payload = api.get("/instruments/search", {"query": name, "exchanges": "NSE", "segments": "FUT",
                          "page_number": page, "records": 30}, envelope=True)
        data = payload.get("data")
        meta = payload.get("meta_data", {}).get("page", {})
        total = meta.get("total_pages")
        if not isinstance(data, list) or type(total) is not int or not 1 <= total <= 3:
            raise CheckFailure("Instrument-search results are missing or exceed the pagination bound.")
        if meta.get("page_number") != page:
            raise CheckFailure("Instrument-search pagination is inconsistent.")
        rows.extend(data)
        if page == total:
            return choose_future(rows, underlying, today)
    raise CheckFailure("Instrument search did not terminate within the page limit.")


def daily_bars(data, now):
    if not isinstance(data, dict) or not isinstance(data.get("candles"), list):
        raise CheckFailure("Daily candle data is missing.")
    bars = {}
    for row in data["candles"]:
        if not isinstance(row, list) or len(row) < 7:
            raise CheckFailure("A daily candle is missing OHLC, volume or OI.")
        try:
            stamp = dt.datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError()
            stamp = stamp.astimezone(IST)
        except (ValueError, TypeError, AttributeError):
            raise CheckFailure("Daily candle timestamp lacks a valid timezone.") from None
        date = stamp.date().isoformat()
        if stamp.date() > now.date() or date in bars:
            raise CheckFailure("Future-dated or duplicate daily candles.")
        open_, high, low, close = [require_number(value, positive=True) for value in row[1:5]]
        if not low <= min(open_, close) <= max(open_, close) <= high:
            raise CheckFailure("Daily candle OHLC ordering is inconsistent.")
        bars[date] = {"date": date, "bar_start_IST": stamp.isoformat(timespec="seconds"),
                      "close": decimal_text(close), "volume": require_count(row[5]),
                      "oi_raw": require_count(row[6])}
    return bars


def futures_check(api, name, underlying, now, dates, closes):
    contract = search_future(api, name, underlying, now.date())
    key = contract["instrument_key"]
    key_path = urllib.parse.quote(key, safe="")
    start = (dt.date.fromisoformat(dates[-1]) - dt.timedelta(days=7)).isoformat()
    path = "/historical-candle/" + key_path + "/days/1/" + dates[0] + "/" + start
    bars = daily_bars(api.get(path, version="v3"), now)
    used_intraday = False
    if dates[0] == now.date().isoformat() and dates[0] not in bars:
        # The calendar has already established that this session has closed.
        path = "/historical-candle/intraday/" + key_path + "/days/1"
        current = daily_bars(api.get(path, version="v3"), now)
        if set(current) != {dates[0]}:
            raise CheckFailure("Intraday fallback did not return exactly the closed current session.")
        bars.update(current)
        used_intraday = True
    if any(date not in bars for date in dates):
        raise CheckFailure("Daily price/OI observations do not cover both latest completed NFO sessions.")
    quote_data = api.get("/market-quote/quotes", {"instrument_key": key})
    checked_quote = quote(quote_data, key, now)
    if checked_quote["status"] != "PASS":
        raise CheckFailure("Futures quote timestamp is unavailable.")
    row = next(row for row in quote_data.values() if isinstance(row, dict) and row.get("instrument_token") == key)
    quote_oi = require_count(row.get("oi"))
    latest, previous = bars[dates[0]], bars[dates[1]]
    trade = checked_quote["last_trade_time_IST"]
    comparable = trade != "N/A" and dt.datetime.fromisoformat(trade).date().isoformat() == dates[0]
    ratio = (decimal_text(Decimal(quote_oi) / Decimal(latest["oi_raw"]))
             if comparable and latest["oi_raw"] else None)
    return {"status": "PASS", **contract, "latest_date": dates[0], "previous_date": dates[1],
            "daily_observations": [latest, previous], "intraday_closed_session_fallback": used_intraday,
            "latest_session_close_IST": closes[("NFO", dates[0])], "quote": checked_quote,
            "quote_oi_raw": quote_oi, "quote_to_daily_oi_ratio_when_comparable": ratio,
            "delta_close": decimal_text(Decimal(latest["close"]) - Decimal(previous["close"])),
            "delta_oi_raw": latest["oi_raw"] - previous["oi_raw"],
            "units": "Price in index points; OI raw provider counts (docs say contracts); independent unit reconciliation pending."}


def dated_records(data, segment, now):
    if not isinstance(data, dict) or not isinstance(data.get(segment), list) or not data[segment]:
        raise CheckFailure("Requested institutional-data segment is missing or empty.")
    records = {}
    for row in data[segment]:
        if not isinstance(row, dict):
            raise CheckFailure("Invalid institutional-data record.")
        stamp = epoch(row.get("time_stamp"))
        date = stamp.date().isoformat()
        if stamp.date() > now.date() or date in records:
            raise CheckFailure("Future-dated or duplicate institutional-data records.")
        records[date] = row
    return records


def position_check(records, dates):
    if any(date not in records for date in dates):
        raise CheckFailure("FII positions do not cover both latest completed NFO sessions.")
    observations = []
    for date in dates:
        row = records[date]
        long_, short = require_count(row.get("total_long_contracts")), require_count(row.get("total_short_contracts"))
        observations.append({"date": date, "provider_time_stamp_ms": row["time_stamp"],
                             "long_contracts": long_, "short_contracts": short, "net_contracts": long_ - short,
                             "long_divided_by_short": decimal_text(Decimal(long_) / short) if short else None,
                             "ratio_note": "N/A: short contracts are zero" if not short else "long / short"})
    return {"status": "PASS", "latest_date": dates[0], "previous_date": dates[1],
            "scope": "Aggregate NSE index futures; not Nifty-only or Bank-Nifty-only.", "observations": observations}


def cash_check(records, dates):
    if len(dates) != 5 or any(date not in records for date in dates):
        raise CheckFailure("Cash data does not cover all five latest completed NSE sessions.")
    observations, nets = [], []
    for date in dates:
        row = records[date]
        buy, sell = require_number(row.get("buy_amount")), require_number(row.get("sell_amount"))
        net = buy - sell
        nets.append(net)
        observations.append({"date": date, "provider_time_stamp_ms": row["time_stamp"],
                             "buy_raw": decimal_text(buy), "sell_raw": decimal_text(sell),
                             "net_raw": decimal_text(net)})
    return {"status": "PASS", "latest_date": dates[0], "oldest_date": dates[-1],
            "observations": observations, "net_sum_last_3_raw": decimal_text(sum(nets[:3])),
            "net_sum_last_5_raw": decimal_text(sum(nets)),
            "units": "Raw provider amounts. Docs label INR; no crore conversion or scoring until independently reconciled."}


def flow_coverage(records, dates):
    """Expose validated dates/timestamps only, including when coverage fails."""
    available = sorted(records, reverse=True)
    return {"required_dates": dates, "available_dates_IST": available,
            "missing_dates": [date for date in dates if date not in records],
            "record_count": len(records),
            "latest_record_date": available[0] if available else None,
            "timestamp_samples": [{"date_IST": date,
                                   "provider_time_stamp_ms": records[date]["time_stamp"],
                                   "provider_time_IST": epoch(records[date]["time_stamp"]).isoformat()}
                                  for date in available[:5]]}


def flow_check(api, path, segment, dates, now, validate):
    """Try bounded, documented query forms; never merge response snapshots.

    `from` is optional. The official examples omit it and request individual
    segments. Explicit oldest/latest required dates are additional diagnostic
    anchors, not an assumption about undocumented date-range semantics.
    """
    methods = [("single_segment_default_range", None),
               ("single_segment_from_oldest_required", min(dates)),
               ("single_segment_from_latest_required", max(dates))]
    attempts, prior = [], []
    fields = (("total_long_contracts", "total_short_contracts")
              if segment == "NSE_FO|INDEX_FUTURES" else ("buy_amount", "sell_amount"))
    for method, start in methods:
        if api.auth_failed:
            break
        evidence = {"method": method, "segment": segment, "interval": "1D"}
        if start is not None:
            evidence["from"] = start
        params = {"data_type": segment, "interval": "1D"}
        if start is not None:
            params["from"] = start
        try:
            records = dated_records(api.get(path, params), segment, now)
            evidence.update(flow_coverage(records, dates))
            # Validate comparable values, rather than silently preferring a
            # complete response that contradicts an earlier partial snapshot.
            current = {date: tuple(require_number(records[date].get(field)) for field in fields)
                       for date in dates if date in records}
            if any(old[date] != current[date] for old in prior for date in old.keys() & current.keys()):
                evidence["status"] = "CONFLICT"
                attempts.append(evidence)
                return {"status": "FAIL", "reason": "Institutional responses disagree on required-session values; no snapshots were merged.",
                        "method_attempts": attempts}
            prior.append(current)
            result = validate(records, dates)
            evidence["status"] = "PASS"
            attempts.append(evidence)
            return {**result, "selected_method": method, "method_attempts": attempts,
                    "timestamp_scope": "Provider record timestamp converted to IST; independent exchange-session reconciliation remains pending."}
        except CheckFailure as exc:
            evidence.update({"status": "FAIL", "reason": str(exc)})
            attempts.append(evidence)
    return {"status": "FAIL", "reason": "No documented query form returned valid data for every required completed session.",
            "required_dates": dates, "method_attempts": attempts}


def attempt(results, label, run):
    try:
        result = run()
        results.append({"check": label, **result})
    except CheckFailure as exc:
        results.append({"check": label, "status": "FAIL", "reason": str(exc)})
    except Exception:
        results.append({"check": label, "status": "FAIL", "reason": "Unexpected response/schema; sensitive details suppressed."})


def run_checks(api, now):
    results = []
    try:
        dates, closes, checked = completed_sessions(api, now)
        results.append({"check": "Provider session calendar", "status": "PASS", "completed_sessions": dates,
                        "calendar_dates_checked": checked,
                        "scope": "Provider timings only; independent NSE-calendar reconciliation remains pending."})
    except CheckFailure as exc:
        return [{"check": "Provider session calendar", "status": "FAIL", "reason": str(exc)}]
    for name, underlying in (("NIFTY", INDICES["Nifty"]), ("BANKNIFTY", INDICES["Bank Nifty"])):
        if api.auth_failed:
            results.append({"check": name + " futures", "status": "SKIPPED", "reason": "Earlier request was rejected."})
            continue
        attempt(results, name + " futures", lambda: futures_check(api, name, underlying, now, dates["NFO"], closes))
    if api.auth_failed:
        results.append({"check": "Institutional flows", "status": "SKIPPED", "reason": "Earlier request was rejected."})
        return results
    for label, path, segment, required, validate in (
        ("FII index-futures positions", "/market/fii", "NSE_FO|INDEX_FUTURES", dates["NFO"], position_check),
        ("FII cash", "/market/fii", "NSE_EQ|CASH", dates["NSE"], cash_check),
        ("DII cash", "/market/dii", "NSE_EQ|CASH", dates["NSE"], cash_check),
    ):
        if api.auth_failed:
            results.append({"check": label, "status": "SKIPPED", "reason": "Earlier request was rejected."})
            continue
        attempt(results, label, lambda: flow_check(api, path, segment, required, now, validate))
    return results


def summary(results, now):
    lines = ["## Upstox futures and flows test", "", "Checked at: " + now.isoformat(), "",
             "| Check | Access/schema/date coverage | Latest date | Previous/oldest date |",
             "| --- | --- | --- | --- |"]
    for result in results:
        fields = [result["check"], result["status"], result.get("latest_date", "N/A"),
                  result.get("previous_date", result.get("oldest_date", "N/A"))]
        lines.append("| " + " | ".join(html.escape(str(value)).replace("|", "&#124;") for value in fields) + " |")
    lines.extend(["", "Validated fields and fixed diagnostics (credentials and raw responses are hidden):", ""])
    lines.extend("- " + html.escape(json.dumps(result, ensure_ascii=True)) for result in results)
    lines.extend(["", "PASS means the requested fields, provider dates and internal checks passed. It does not establish independent source/units verification or production readiness.",
                  "Probe futures policy: nearest returned exact-index FUT expiry strictly after today's date; the report rollover policy is not set.",
                  "Current-day daily candles are used only after the provider's published session end. Candle timestamps mark bar starts, not quote freshness.",
                  "OI counts and cash amounts are preserved in provider units. No inferred lot conversion, crore conversion, signal score, bias or DII-offset rule is applied.",
                  "If a required completed session is absent, the check fails rather than substituting zero or an older day.",
                  "Flow requests try single segments with the default date range, then explicit oldest/latest required start dates. Each attempt reports returned and missing dates; one complete response must pass on its own. No timestamp shifts or cross-response row merging are applied.",
                  "Provider documentation: https://upstox.com/developer/api-documentation/", ""])
    return "\n".join(lines)


def main():
    now = dt.datetime.now(IST)
    try:
        results = run_checks(API(os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")), now)
    except CheckFailure as exc:
        results = [{"check": "Configuration", "status": "FAIL", "reason": str(exc)}]
    except Exception:
        results = [{"check": "Probe", "status": "FAIL", "reason": "Unexpected response/schema; sensitive details suppressed."}]
    for result in results:
        print(json.dumps(result, ensure_ascii=True))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(summary(results, now))
    return 0 if len(results) == 6 and all(result["status"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
