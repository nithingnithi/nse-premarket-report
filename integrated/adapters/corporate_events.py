"""Load a dated, reviewed selection of corporate events from official filings."""

import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit


SCHEDULE = Path(__file__).resolve().parents[1] / 'data' / 'corporate_events.json'
OFFICIAL_HOSTS = {'www.sebi.gov.in', 'www.nseindia.com', 'www.nseindia.in',
                  'nsearchives.nseindia.com', 'www.bseindia.com'}
KINDS = {'Results meeting', 'Dividend ex-date', 'IPO opens', 'IPO listing'}


def reviewed_events(report_date, path=SCHEDULE):
    day = dt.date.fromisoformat(report_date)
    try:
        schedule = json.loads(path.read_text(encoding='utf-8'))
        entries = schedule.get(report_date, [])
        if not isinstance(entries, list):
            raise ValueError('Expected an event list')
        items = []
        for row in entries:
            kind, title, note = (row[key] for key in ('kind', 'title', 'note'))
            link = urlsplit(row['url'])
            if (kind not in KINDS or not 1 <= len(title.strip()) <= 85
                    or not 1 <= len(note.strip()) <= 100 or link.scheme != 'https'
                    or link.netloc not in OFFICIAL_HOSTS or not link.path):
                raise ValueError('Invalid event or source')
            if dt.date.fromisoformat(row['announced_on']) >= day:
                continue  # A same-day filing needs a publication time to qualify for 07:45.
            items.append({'kind':kind, 'title':title, 'note':note, 'url':row['url']})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'status':'UNAVAILABLE','reason':'Reviewed corporate schedule could not be validated'}
    if not items:
        return {'status':'UNAVAILABLE','reason':'No dated corporate filings reviewed for this report'}
    return {'status':'REVIEWED', 'date_IST':report_date, 'items':items}
