"""Live-data branch dry run: PDF and diagnostics only; no delivery imports."""
import datetime as dt
import html
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from integrated.cloud_review import make_review
from integrated.render import render
from integrated.review import validate

IST=ZoneInfo('Asia/Kolkata')

def unavailable(snapshot):
    items=[]
    def add(label,record,field,default):
        if not isinstance(record,dict):record={}
        if record.get(field) is None:
            items.append((label,record.get('reason') or record.get('change_reason') or default))
    for name in ('Nifty','Bank Nifty'):
        add(name+' spot',snapshot.get('indices',{}).get(name),'last_price','Completed-session quote unavailable')
    flows={row.get('check'):row for row in snapshot.get('flows',[]) if isinstance(row,dict)}
    for name in ('NIFTY futures','BANKNIFTY futures','FII index-futures positions','FII cash','DII cash'):
        row=flows.get(name) or {}
        if row.get('status')!='PASS':items.append((name,row.get('reason','Provider did not return required dates or fields')))
    for name in ('NIFTY','BANKNIFTY'):
        add(name+' options',snapshot.get('options',{}).get(name),'pcr_current','Same-expiry option baseline unavailable')
    add('India VIX',snapshot.get('vix'),'level','Previous-session volatility quote unavailable')
    for row in snapshot.get('global',[]):
        add(row.get('name','Market'),row,'value','No timely quote')
        add(row.get('name','Market')+' previous close',row,'previous_close','Previous close unavailable')
    if not snapshot.get('news'):items.append(('News',snapshot.get('news_reason') or 'No eligible item in selected 12-hour queries'))
    if not snapshot.get('calendar'):items.append(('Calendar',snapshot.get('calendar_reason') or 'No dated item returned'))
    for name,row in snapshot.get('shadow_signals',{}).items():
        add('Shadow '+name.replace('_',' '),row,'value','No qualifying baseline')
    return items

def main():
    now=dt.datetime.now(IST)
    day=os.environ.get('REPORT_DATE') or now.date().isoformat()
    snapshot=json.loads((Path('handoff')/(day+'.json')).read_text())
    review=make_review(snapshot)
    validate(snapshot,review,now,live=False)
    output=Path('out')/('report-v2-live-dry-run-'+day+'.pdf')
    render(snapshot,review,output)
    lines=['## Report v2 live-data dry run','',
           'Report date: '+html.escape(day)+'; session: '+html.escape(snapshot.get('trading_day','UNVERIFIED'))+'.',
           'Official score: '+str(snapshot['score']['score'])+'; available: '+str(snapshot['score']['available'])+'/6; bias: '+html.escape(snapshot['score']['bias'])+'.',
           'PDF and shadow CSV are artifacts. No Telegram or Drive delivery was attempted.','',
           '### N/A fields and reasons','']
    missing=unavailable(snapshot)
    lines.extend('- '+html.escape(label)+': '+html.escape(str(reason)) for label,reason in missing)
    if not missing:lines.append('- None in the checked fields.')
    summary='\n'.join(lines)+'\n'
    Path('out/live-dry-run-summary.md').write_text(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:stream.write(summary)
    print('LIVE_DATA_DRY_RUN_PDF_READY',output,'N_A_FIELDS',len(missing))
    print(summary)

if __name__=='__main__':main()
