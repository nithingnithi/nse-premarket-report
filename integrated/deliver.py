"""Review validation and durable at-most-once channel delivery."""
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from integrated.review import IST,load,validate
from integrated.render import render
from integrated.telegram import send

def persist(path):
    for args in (['git','add','--',str(path)],['git','commit','-m','Record report delivery state'],['git','push','origin','HEAD:main']):
        subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def reserve(path,payload,commit=persist):
    if path.exists():raise ValueError('Delivery already reserved or completed; no automatic resend')
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as out:json.dump(payload,out,indent=2)
    commit(path) # MUST succeed remotely before any sendDocument call.

def send_if_current(snapshot,review,path,sender=send,clock=None):
    validate(snapshot,review,(clock or (lambda:dt.datetime.now(IST)))(),live=True)
    return sender(path.read_bytes(),path.name)

def main():
    now=dt.datetime.now(IST);dry=os.environ.get('DRY_RUN','true')=='true'
    day=os.environ.get('REPORT_DATE') or now.date().isoformat()
    s,r=load(day);validate(s,r,now,live=not dry)
    path=Path('out')/f'nse-report-{day}.pdf';render(s,r,path)
    if dry:
        print('INTEGRATION_DRY_RUN_PASS: validated review and rendered PDF; no Telegram request');return
    ledger=Path('delivery_ledger')/(day+'.json')
    reserve(ledger,{'report_date':day,'status':'RESERVED_UNCERTAIN_UNTIL_VERIFIED','run_id':os.environ.get('GITHUB_RUN_ID')})
    result=send_if_current(s,r,path)
    ledger.write_text(json.dumps({'report_date':day,**result},indent=2));persist(ledger)
if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Integration failed safely; inspect validation/delivery state. Sensitive details suppressed.')
