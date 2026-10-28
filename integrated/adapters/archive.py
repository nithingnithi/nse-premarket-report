"""Manual archive probe. Raw OI units and full contract coverage unverified."""
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.error
import zipfile
from decimal import Decimal
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
REQUIRED = {'TradDt', 'TckrSymb', 'FinInstrmTp', 'XpryDt', 'StrkPric', 'OptnTp', 'OpnIntrst'}
MAX_ZIP = 20 * 1024 * 1024
MAX_CSV = 100 * 1024 * 1024

def date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Date must be YYYY-MM-DD')
    return dt.date.fromisoformat(value)

def number(value):
    try:
        n = Decimal(value)
    except Exception:
        raise ValueError('Invalid numeric field') from None
    if not n.is_finite() or n < 0:
        raise ValueError('Missing, negative or nonfinite numeric field')
    return n

def parse_archive(payload, day):
    if len(payload) > MAX_ZIP:
        raise ValueError('ZIP exceeds size limit')
    expected = f'BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv'
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != expected:
            raise ValueError('Unexpected ZIP members')
        if members[0].file_size > MAX_CSV or members[0].flag_bits & 1:
            raise ValueError('CSV too large or encrypted')
        with archive.open(members[0]) as member:
            raw = member.read(MAX_CSV + 1)
        if len(raw) > MAX_CSV:
            raise ValueError('CSV exceeds size limit')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    headers = reader.fieldnames or []
    if REQUIRED - set(headers) or len(headers) != len(set(headers)):
        raise ValueError('Missing or duplicate CSV columns')
    rows = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Malformed CSV row')
        if date(row['TradDt']) != day:
            raise ValueError('Internal trading date mismatch')
        if row['TckrSymb'] in ('NIFTY', 'BANKNIFTY') and row['FinInstrmTp'] in ('IDO', 'IDF'):
            rows.append(row)
    if not rows:
        raise ValueError('No target contracts')
    return rows

def snapshot(rows, symbol, day, report_day=None):
    report_day = report_day or day + dt.timedelta(days=1)
    selected = [r for r in rows if r['TckrSymb'] == symbol]
    if not selected:
        raise ValueError('Symbol absent')
    seen, groups, futures = set(), {}, []
    for r in selected:
        expiry = date(r['XpryDt'])
        if expiry < day:
            raise ValueError('Expired contract in session file')
        oi = number(r['OpnIntrst'])
        if oi != oi.to_integral_value():
            raise ValueError('Nonintegral OI')
        kind = r['FinInstrmTp']
        strike = number(r['StrkPric']) if kind == 'IDO' else None
        side = r['OptnTp'] if kind == 'IDO' else None
        if kind == 'IDO' and (side not in ('CE', 'PE') or strike <= 0):
            raise ValueError('Invalid option side or strike')
        key = (kind, expiry, strike, side)
        if key in seen:
            raise ValueError('Duplicate contract')
        seen.add(key)
        if kind == 'IDF':
            futures.append({'expiry': expiry.isoformat(), 'oi_raw': int(oi)})
        else:
            groups.setdefault(expiry.isoformat(), {'CE': {}, 'PE': {}})[side][strike] = int(oi)
    summaries = []
    for expiry, sides in sorted(groups.items()):
        complete = bool(sides['CE']) and sides['CE'].keys() == sides['PE'].keys()
        totals = {s: sum(v.values()) for s, v in sides.items()}
        walls = {s: [str(k) for k, v in sorted(values.items()) if v == max(values.values())]
                 if values and max(values.values()) > 0 else [] for s, values in sides.items()}
        summaries.append({'expiry': expiry, 'paired_strikes': complete,
            'call_strike_count': len(sides['CE']), 'put_strike_count': len(sides['PE']),
            'call_only_strikes': [str(x) for x in sorted(sides['CE'].keys() - sides['PE'].keys())],
            'put_only_strikes': [str(x) for x in sorted(sides['PE'].keys() - sides['CE'].keys())],
            'call_oi_raw': totals['CE'], 'put_oi_raw': totals['PE'],
            'pcr_raw_oi': str(Decimal(totals['PE']) / Decimal(totals['CE'])) if complete and totals['CE'] else None,
            'max_call_oi_strikes': walls['CE'], 'max_put_oi_strikes': walls['PE']})
    eligible = [x for x in summaries if date(x['expiry']) >= report_day]
    selected_option = eligible[0] if eligible else None
    eligible_futures = sorted((x for x in futures if date(x['expiry']) >= report_day), key=lambda x: x['expiry'])
    selected_future = eligible_futures[0] if eligible_futures else None
    ready = selected_option is not None and selected_option['paired_strikes'] and selected_future is not None
    reasons = []
    if selected_option is None:
        reasons.append('No option expiry on or after report date')
    elif not selected_option['paired_strikes']:
        reasons.append('Selected option expiry has unmatched call/put strikes')
    if selected_future is None:
        reasons.append('No futures expiry on or after report date')
    return {'symbol': symbol, 'status': 'COLLECTED' if ready else 'PARTIAL',
            'reasons': reasons, 'report_date': report_day.isoformat(),
            'selection_policy': 'Probe only: earliest returned expiry on or after report date, independently for options and futures; no weekly label inferred',
            'selected_option_expiry': selected_option['expiry'] if selected_option else None,
            'selected_futures_expiry': selected_future['expiry'] if selected_future else None,
            'unmatched_strike_expiries': [x['expiry'] for x in summaries if not x['paired_strikes']],
            'oi_unit': 'UNVERIFIED_RAW', 'options_by_expiry': summaries,
            'futures_by_expiry': futures, 'source_rows': selected}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def main():
    out = {'status': 'UNAVAILABLE', 'started_at': dt.datetime.now(IST).isoformat(),
           'scope': 'Manual EOD archive probe; no score, trading-calendar validation or Telegram delivery. PCR uses raw OI; units and full contract coverage unverified.',
           'data': []}
    try:
        day = date(os.environ.get('DATA_DATE', ''))
        report_day = date(os.environ.get('REPORT_DATE', ''))
        if report_day <= day:
            raise ValueError('Report date must be later than data date')
        out['report_date'] = report_day.isoformat()
        if day >= dt.datetime.now(IST).date():
            raise ValueError('Choose a completed session before today')
        out['data_date'] = day.isoformat()
        out['source'] = 'https://nsearchives.nseindia.com/content/fo/' + f'BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip'
        request = urllib.request.Request(out['source'], headers={'User-Agent': 'NSEMorningReport/0.1 (read-only archive probe)'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            payload = response.read(MAX_ZIP + 1)
        out['fetched_at'] = dt.datetime.now(IST).isoformat()
        rows = parse_archive(payload, day)
        out['archive_sha256'] = hashlib.sha256(payload).hexdigest()
        for symbol in ('NIFTY', 'BANKNIFTY'):
            try:
                out['data'].append(snapshot(rows, symbol, day, report_day))
            except ValueError as exc:
                out['data'].append({'symbol': symbol, 'status': 'UNAVAILABLE', 'error': str(exc)})
        out['status'] = 'COLLECTED' if all(r['status'] == 'COLLECTED' for r in out['data']) else 'PARTIAL'
    except urllib.error.HTTPError as exc:
        out['error'] = f'HTTP {exc.code}; no bypass or older-date substitution attempted'
    except ValueError as exc:
        out['error'] = str(exc)
    except Exception:
        out['error'] = 'Network, ZIP or decoding failure; raw response suppressed'
    Path('out').mkdir(exist_ok=True)
    Path('out/snapshot.json').write_text(json.dumps(out, indent=2, allow_nan=False))
    summary = '## NSE F&O archive probe\n\nStatus: ' + out['status'] + '\n\n' + out['scope'] + '\n'
    for item in out['data']:
        summary += '\n- ' + item['symbol'] + ': ' + item['status']
        if 'selected_option_expiry' in item:
            summary += '; selected option expiry: ' + str(item['selected_option_expiry'])
            summary += '; selected futures expiry: ' + str(item['selected_futures_expiry'])
            summary += '; unmatched strike expiries: ' + ', '.join(item['unmatched_strike_expiries'])
            for reason in item['reasons']:
                summary += '\n  - ' + reason
    if 'error' in out:
        summary += '\n\n' + out['error']
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(summary)
    print('ARCHIVE_RESULT: ' + out['status'])
    return 0 if out['status'] == 'COLLECTED' else 1

if __name__ == '__main__':
    raise SystemExit(main())
