"""Cloud fallback review from a validated compact snapshot; no model/API call."""
import datetime as dt
import json
import os
import re
from pathlib import Path
from integrated.collect import digest
from integrated.brief_v3 import caption
from integrated.review import IST,validate


def make_review(snapshot):
    score=snapshot['score']
    n=score['available']
    missing=score['missing']
    bias=score['bias']
    names={'futures_build_up':'futures build-up','pcr_direction':'PCR direction',
           'strike_walls':'strike walls','fii_futures':'FII futures',
           'fii_cash':'FII cash','dii_cash':'DII cash'}
    summary=(f"At 07:45 IST the score is {score['score']:+d} from {n}/6 available signals. "
             f"Possible range: {score['score_range'][0]:+d} to {score['score_range'][1]:+d}. "
             f"Bias: {bias}. Missing: {', '.join(names[x] for x in missing) if missing else 'none'}. "
             "India VIX caution is separate from the score. Prices retain their source times; unavailable fields are N/A.")
    first=caption(snapshot,{'alerts':['N/A']}).splitlines()[2]
    option=snapshot.get('options',{}).get('NIFTY',{})
    def wall(key):return ', '.join(str(x) for x in option.get(key,[])) or 'N/A'
    levels=f"Nifty put wall {wall('put_walls')}; call wall {wall('call_walls')}."
    alerts=[first,levels,f"India VIX: {snapshot.get('vix_flag','UNKNOWN')}; {n}/6 score signals available."]
    return {'schema_version':1,'report_date':snapshot['report_date'],
            'snapshot_sha256':digest(snapshot),'summary':summary,
            'alerts':alerts,'mcp_context':[]}


def run(root,now):
    local=now.astimezone(IST)
    day=local.date().isoformat()
    # A delayed GitHub cron must not turn yesterday's handoff into a failed job.
    if not dt.time(7,45)<=local.time()<=dt.time(8,10):return False
    pointer=json.loads((root/'handoff/latest.json').read_text())
    if pointer.get('report_date')!=day or pointer.get('path')!=f'handoff/{day}.json':
        raise ValueError('No current dated handoff; collection may be late')
    snapshot=json.loads((root/pointer['path']).read_text())
    if snapshot.get('report_date')!=day or pointer.get('snapshot_sha256')!=digest(snapshot):
        raise ValueError('Handoff hash/date mismatch')
    if snapshot.get('trading_day')=='CLOSED':return False
    if snapshot.get('trading_day')!='OPEN':raise ValueError('Trading calendar is unverified')
    cutoff=dt.datetime.fromisoformat(snapshot['cutoff_IST'])
    if now<cutoff:return False
    if now>cutoff+dt.timedelta(minutes=25):
        raise ValueError('Cloud review started after 08:10 IST')
    ledger=root/f'delivery_ledger/{day}.json'
    if ledger.exists():
        try:
            delivery=json.loads(ledger.read_text())
        except (OSError,ValueError):
            raise ValueError('Delivery ledger is malformed or uncertain')
        hashes=[delivery.get(key) for key in ('pdf_sha256','text_sha256')]
        confirmed_hash=any(isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value)
                           for value in hashes)
        if (delivery.get('report_date')==day and delivery.get('status')=='SENT'
                and confirmed_hash
                and type(delivery.get('message_id')) is int and delivery['message_id']>0):
            return False
        raise ValueError('Delivery is reserved or unconfirmed; no automatic retry')
    target=root/f'review_requests/{day}.json'
    if target.exists():raise ValueError('Review already exists without confirmed delivery')
    review=make_review(snapshot)
    validate(snapshot,review,now,live=True)
    target.parent.mkdir(exist_ok=True)
    with target.open('x',encoding='utf-8') as out:
        json.dump(review,out,ensure_ascii=False,indent=2)
    return True


def main():
    try:
        ready=run(Path('.'),dt.datetime.now(IST))
    except Exception:
        raise SystemExit('Cloud review failed safely. Check current handoff, trading date and cutoff; no report sent.')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:
            out.write('ready='+('true' if ready else 'false')+'\n')
    print('CLOUD_REVIEW_CREATED' if ready else 'CLOUD_REVIEW_SKIPPED')
if __name__=='__main__':main()
