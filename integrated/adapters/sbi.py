"""SBI news and dated corporate events, separate from the six-signal score."""
import datetime as dt
import re
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit

from integrated.adapters import global_data

ISIN = 'INE062A01020'
INSTRUMENT = 'NSE_EQ|' + ISIN
SYMBOL = re.compile(r'\b(?:SBIN|State Bank of India)\b', re.I)
SBI_HEADLINE = re.compile(
    r'\b(?:SBIN|State Bank of India|SBI(?!\s+(?:Life|Cards?|Mutual Fund|General Insurance)\b))\b', re.I)
RSS_BASE = 'https://nsearchives.nseindia.com/content/RSS/'
FILINGS = {'announcements': ('Online_announcements.xml', 'SBI exchange announcement'),
           'board_meetings': ('Board_Meetings.xml', 'SBI board meeting'),
           'financial_results': ('Financial_Results.xml', 'SBI results filing')}
NSE_HOSTS = {'nseindia.com', 'www.nseindia.com', 'nsearchives.nseindia.com',
             'nseindia.in', 'www.nseindia.in', 'nsearchives.nseindia.in'}
MEETING_DATE = re.compile(
    r'\b(?:meeting date|scheduled (?:to be held )?on|will be held on|is to be held on)'
    r'\s*[:\-]?\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\b', re.I)


def unavailable(reason):
    return {'status': 'UNAVAILABLE', 'reason': reason}


def news(api, cutoff, *, observed_at=None):
    envelope = api.get('/news', {'category': 'instrument_keys', 'instrument_keys': INSTRUMENT,
                                 'page_number': 1, 'page_size': 100}, envelope=True)
    rows, total_pages = global_data.news_page(envelope, 1, observed_at or dt.datetime.now(global_data.IST),
                                             instrument_keys=(INSTRUMENT,))
    selected, _ = global_data.window_news(rows, cutoff)
    result = {'status': 'PARTIAL' if total_pages > 1 else 'PASS',
              'articles': [{**row, 'source': ('SBI / Upstox' if SBI_HEADLINE.search(row['title'])
                                                   else 'SBIN-tagged / Upstox')}
                           for row in selected[:3]]}
    if total_pages > 1:
        result['reason'] = 'Only the first news page was checked'
    return result


def actions(rows, report_date):
    if not isinstance(rows, list):
        raise ValueError('Invalid action list')
    upcoming, history = [], []
    incomplete = False
    end = report_date + dt.timedelta(days=7)
    for row in rows:
        try:
            day = dt.datetime.strptime(row['expiry_date'], '%d %b %Y').date()
            kind = row['name'].strip().title()
            if kind not in ('Dividend', 'Bonus', 'Split', 'Rights'):
                continue
            details = {part['name'].strip().casefold(): part['value'] for part in row['event_details']}
            event = {'title': 'SBI ' + kind.lower(), 'date': day.isoformat(), 'source': 'Upstox'}
            if kind == 'Dividend':
                amount = Decimal(str(row['amount']))
                if not amount.is_finite() or amount <= 0:
                    raise ValueError('Invalid dividend amount')
                event.update(amount=str(amount), title=f'SBI dividend ₹{amount} per share')
            if report_date <= day <= end:
                announced = dt.datetime.strptime(details['announcement date'], '%d %b %Y').date()
                if announced < report_date:
                    upcoming.append(event)
                else:
                    incomplete = True
            elif day < report_date and kind == 'Dividend':
                history.append(event)
        except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError):
            incomplete = True
    return {'status': 'PARTIAL' if incomplete else 'PASS',
            'upcoming': sorted(upcoming, key=lambda x: x['date'])[:4],
            'last_dividend': max(history, key=lambda x: x['date'], default=None)}


def exchange_time(value):
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.utcoffset() is not None:
            return stamp.astimezone(global_data.IST)
    except (TypeError, ValueError):
        pass
    # NSE RSS publishes the observed dd-Mon-yyyy HH:mm:ss exchange-local format.
    # Treat that exact format as IST, the clock used for NSE corporate dissemination.
    return dt.datetime.strptime(value, '%d-%b-%Y %H:%M:%S').replace(tzinfo=global_data.IST)


def filings(raw, kind, cutoff):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported XML declarations')
    root = ET.fromstring(raw)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise ValueError('Missing RSS channel')
    notices, upcoming = {}, {}
    rescheduled = False
    title = FILINGS[kind][1]
    incomplete = False
    start = cutoff - dt.timedelta(hours=12)
    end = cutoff.date() + dt.timedelta(days=7)
    for item in channel.findall('item'):
        if not SYMBOL.search(' '.join(item.findtext(key, '') for key in ('title', 'symbol'))):
            continue
        try:
            published = exchange_time(item.findtext('pubDate', '').strip())
            if published > cutoff:
                continue
            url = item.findtext('link', '').strip()
            link = urlsplit(url)
            if link.scheme != 'https' or link.netloc not in NSE_HOSTS or not link.path:
                raise ValueError('Invalid NSE filing link')
            row = {'title': title, 'published_IST': published.isoformat(timespec='seconds'),
                   'url': url, 'source': 'SBI / NSE'}
            if kind != 'board_meetings':
                if start < published:
                    notices[url] = row
                continue
            description = re.sub(r'<[^>]+>', ' ', unescape(item.findtext('description', '')))
            if re.search(r'\b(?:cancelled|canceled|postponed|rescheduled)\b', description, re.I):
                rescheduled = True
                continue
            match = MEETING_DATE.search(' '.join(description.split()))
            if not match:
                incomplete = True
                continue
            day = dt.datetime.strptime(match[1], '%d-%b-%Y').date()
            if cutoff.date() <= day <= end:
                upcoming[day] = {'title': title, 'date': day.isoformat(), 'source': 'NSE', 'url': url}
        except (AttributeError, TypeError, ValueError):
            incomplete = True
    if rescheduled:
        incomplete = True
        upcoming.clear()
    return {'status': 'PARTIAL' if incomplete else 'PASS',
            'notices': sorted(notices.values(), key=lambda x: x['published_IST'], reverse=True)[:2],
            'upcoming': [upcoming[day] for day in sorted(upcoming)[:2]]}


def download_rss(filename):
    request = urllib.request.Request(RSS_BASE + filename,
                                    headers={'User-Agent': global_data.CLIENT_IDENTITY})
    with urllib.request.build_opener(global_data.NoRedirect()).open(request, timeout=6) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('RSS response exceeds size limit')
    return raw


def run(api, cutoff, *, fallback=(), rss_fetch=download_rss):
    headlines = unavailable('Upstox SBI news unavailable')
    events = unavailable('Upstox SBI corporate actions unavailable')
    if api is not None:
        try:
            headlines = news(api, cutoff)
        except (global_data.CheckFailure, AttributeError, KeyError, TypeError, ValueError):
            pass
        try:
            events = actions(api.get(f'/fundamentals/{ISIN}/corporate-actions', {}), cutoff.date())
        except (global_data.CheckFailure, KeyError, TypeError, ValueError):
            pass
    if not headlines.get('articles'):
        candidates = [row for row in fallback if SYMBOL.search(row.get('title') or '')]
        selected, _ = global_data.window_news(candidates, cutoff)
        if selected:
            headlines = {'status': 'PARTIAL', 'reason': 'Using the existing Marketaux news results',
                         'articles': [{**row, 'source': 'SBI / Marketaux'} for row in selected[:3]]}
    exchange = {}
    for kind, (filename, _) in FILINGS.items():
        try:
            exchange[kind] = filings(rss_fetch(filename), kind, cutoff)
        except (OSError, ValueError, ET.ParseError):
            exchange[kind] = unavailable('NSE feed unavailable')
    return {'news': headlines, 'actions': events, 'filings': exchange}
