"""Cloud fallback review from a validated compact snapshot; no model/API call."""
import datetime as dt
import json
import os
from pathlib import Path
from integrated.collect import digest
from integrated.review import IST,validate


def make_review(snapshot):
    score=snapshot['score']
    n=score['available']
    missing=score['missing']
    bias=score['bias']
    shadows=snapshot.get('shadow_signals',{})
    shadow_note=' Shadow signals are displayed separately and are not counted.' if shadows else ''
    summary=(
        f"At the 07:45 IST report cutoff, the deterministic score is {score['score']:+d} "
        f"from {n}/6 available signals. The theoretical range is "
        f"[{score['score_range'][0]:+d}, {score['score_range'][1]:+d}]. "
        f"The computed bias is {bias}. "
        f"Missing signals: {', '.join(missing) if missing else 'none'}. "
        "Missing values remain N/A. Cash figures are labelled ₹ cr. "
        "The volatility caution is separate from the score. "
        "No DII-offset bonus is applied."+shadow_note
    )
    vix=snapshot.get('vix') or {}
    future=shadows.get('futures_build_up',{})
    readable_bias='final bias unavailable' if bias=='INSUFFICIENT DATA TO ASSIGN FINAL BIAS' else bias.lower()
    alerts=[f"Score {score['score']:+d} from {n}/6 signals; {readable_bias}.",
            (f"Futures build-up withheld: {future.get('reason','data unavailable')}." if future.get('value') is None
             else f"Futures build-up is {future.get('reason','classified')}; shadow, not counted."),
            (f"India VIX {vix.get('level')}; caution {snapshot.get('vix_flag','UNKNOWN')}." if vix.get('level') is not None
             else f"India VIX N/A: {vix.get('reason','previous-session quote unavailable')}.")]
    alerts=[a[:179] for a in alerts]
    return {'schema_version':1,'report_date':snapshot['report_date'],
            'snapshot_sha256':digest(snapshot),'summary':summary,
            'alerts':alerts,'mcp_context':[]}


def run(root,now):
    day=now.astimezone(IST).date().isoformat()
    if now.astimezone(IST).time()<dt.time(7,55):return False
    pointer=json.loads((root/'handoff/latest.json').read_text())
    if pointer.get('report_date')!=day or pointer.get('path')!=f'handoff/{day}.json':
        raise ValueError('No current dated handoff; collection may be late')
    snapshot=json.loads((root/pointer['path']).read_text())
    if snapshot.get('report_date')!=day or pointer.get('snapshot_sha256')!=digest(snapshot):
        raise ValueError('Handoff hash/date mismatch')
    if snapshot.get('trading_day')=='CLOSED':return False
    if snapshot.get('trading_day')!='OPEN':raise ValueError('Trading calendar is unverified')
    cutoff=dt.datetime.fromisoformat(snapshot['cutoff_IST'])
    if now<cutoff+dt.timedelta(minutes=10):return False
    if now>cutoff+dt.timedelta(minutes=25):
        raise ValueError('Cloud review started after 08:10 IST')
    if (root/f'delivery_ledger/{day}.json').exists():return False
    target=root/f'review_requests/{day}.json'
    if target.exists():return False
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
