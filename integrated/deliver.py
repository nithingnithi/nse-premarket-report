"""Review validation and durable at-most-once channel delivery."""
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from integrated.review import IST,load,validate
from integrated.telegram import send
from integrated.render import render

def persist(path):
    for args in (['git','add','--',str(path)],['git','commit','-m','Record report delivery state'],['git','push','origin','HEAD:main']):
        subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def reserve(path,payload,commit=persist):
    if path.exists():raise ValueError('Delivery already reserved or completed; no automatic resend')
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as out:json.dump(payload,out,indent=2)
    commit(path) # MUST succeed remotely before any sendDocument call.

def main():
    now=dt.datetime.now(IST);dry=os.environ.get('DRY_RUN','true')=='true'
    day=os.environ.get('REPORT_DATE') or now.date().isoformat()
    s,r=load(day);validate(s,r,now,live=not dry)
    output=Path('out')/f'NSE-Morning-Report-{day}.pdf'
    render(s,r,output)
    pdf=output.read_bytes()
    if not pdf.startswith(b'%PDF-') or len(pdf)<1000:
        raise ValueError('PDF render failed integrity check')
    if dry:
        print('INTEGRATION_DRY_RUN_PASS: validated PDF; no Telegram request');return
    followup=os.environ.get('PDF_FOLLOWUP')=='true'
    if followup:
        original=Path('delivery_ledger')/(day+'.json')
        prior=json.loads(original.read_text())
        if prior.get('report_date')!=day or prior.get('status')!='SENT' or not prior.get('text_sha256') or not prior.get('message_id'):
            raise ValueError('PDF follow-up requires confirmed prior text delivery')
    ledger=Path('supplemental_pdf_ledger' if followup else 'delivery_ledger')/(day+'.json')
    reserve(ledger,{'report_date':day,'status':'RESERVED_UNCERTAIN_UNTIL_VERIFIED','run_id':os.environ.get('GITHUB_RUN_ID')})
    # Recheck the live window after the remote reservation, immediately before sendDocument.
    validate(s,r,dt.datetime.now(IST),live=True)
    result=send(pdf,output.name)
    ledger.write_text(json.dumps({'report_date':day,**result},indent=2));persist(ledger)
if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Integration failed safely; inspect validation/delivery state. Sensitive details suppressed.')
