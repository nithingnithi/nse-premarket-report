"""Strict review handoff; the reviewer cannot modify the deterministic score."""
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from integrated.collect import digest, clean
from nse_report.calculations import score_summary
IST=ZoneInfo('Asia/Kolkata')

def validate(snapshot,review,now,live=False):
    if review.get('schema_version')!=1 or review.get('report_date')!=snapshot.get('report_date'):
        raise ValueError('Review date/schema mismatch')
    if review.get('snapshot_sha256')!=digest(snapshot):raise ValueError('Snapshot changed after review')
    if set(review)-{'schema_version','report_date','snapshot_sha256','summary','alerts','mcp_context'}:
        raise ValueError('Unexpected review fields; score overrides prohibited')
    for field,limit in [('summary',1200)]:
        if not isinstance(review.get(field),str) or not 1<=len(review[field])<=limit:raise ValueError('Review text bounds')
    alerts=review.get('alerts')
    if not isinstance(alerts,list) or len(alerts)!=3 or any(not isinstance(a,str) or not 1<=len(a)<=180 for a in alerts):raise ValueError('Exactly three short alerts required')
    context=review.get('mcp_context',[])
    if not isinstance(context,list) or len(context)>2:raise ValueError('Context bounds')
    expected=snapshot.get('completed_sessions',{}).get('NSE',[None])[0]
    for row in context:
        if set(row)!={'source','data_date','text'} or row['source'] not in ('nse-bhavcopy','cm-market') or row['data_date']!=expected:
            raise ValueError('MCP source/date mismatch')
        if not isinstance(row['text'],str) or len(row['text'])>350:raise ValueError('Context text bounds')
    score=clean(score_summary(snapshot['score']['signals']))
    if score!=snapshot['score']:raise ValueError('Inconsistent score')
    if live:
        cutoff=dt.datetime.fromisoformat(snapshot['cutoff_IST'])
        if cutoff.tzinfo is None or now.astimezone(IST).date().isoformat()!=snapshot['report_date']:
            raise ValueError('Stale report')
        if not cutoff<=now<=cutoff+dt.timedelta(minutes=30):raise ValueError('Outside 07:45-08:15 delivery window')
        if snapshot.get('trading_day')!='OPEN':raise ValueError('Trading session not confirmed')
    return score

def load(day):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('Invalid date')
    return json.loads(Path(f'handoff/{day}.json').read_text()),json.loads(Path(f'review_requests/{day}.json').read_text())
