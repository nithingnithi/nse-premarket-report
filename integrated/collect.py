"""Bounded collection; compact, fail-closed handoff. No model/API calls."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from zoneinfo import ZoneInfo
import urllib.request
from integrated.adapters import flows, global_data, news, calendar, archive
from nse_report.calculations import OptionChain, OptionRow, compare_options, score_summary, vix_caution
from integrated.shadow_signals import config, build
IST=ZoneInfo('Asia/Kolkata')

def clean(x):
    if isinstance(x,Decimal):return str(x)
    if isinstance(x,Fraction):return str(Decimal(x.numerator)/Decimal(x.denominator))
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    return x

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def attempt(fn):
    try:return fn()
    except Exception:return {'status':'UNAVAILABLE','reason':'Provider request or validation failed; sensitive details suppressed.'}

def get_archive(day,report_day):
    url='https://nsearchives.nseindia.com/content/fo/'+f'BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip'
    request=urllib.request.Request(url,headers={'User-Agent':'NSEMorningReport/0.1 (read-only archive probe)'})
    with urllib.request.build_opener(archive.NoRedirect()).open(request,timeout=30) as response:
        body=response.read(archive.MAX_ZIP+1)
    rows=archive.parse_archive(body,day)
    return {'date':str(day),'source':url,'sha256':hashlib.sha256(body).hexdigest(),'data':[archive.snapshot(rows,s,day,report_day) for s in ('NIFTY','BANKNIFTY')]}

def option_summary(old,new,symbol):
    a=next(x for x in old['data'] if x['symbol']==symbol);b=next(x for x in new['data'] if x['symbol']==symbol)
    expiry=b['selected_option_expiry']
    if expiry!=a['selected_option_expiry'] or not expiry:raise ValueError('Expiry changed')
    chains=[];identities=[];lots=set()
    for snap,item in [(old,a),(new,b)]:
        pairs={};ids={}
        for r in item['source_rows']:
            if r['FinInstrmTp']!='IDO' or r['XpryDt']!=expiry:continue
            k=Decimal(r['StrkPric']);side=r['OptnTp']
            if side not in ('CE','PE') or side in pairs.setdefault(k,{}):raise ValueError('Duplicate')
            pairs[k][side]=r['OpnIntrst'];ids[(k,side)]=r['FinInstrmId'];lots.add(r['NewBrdLotQty'])
        if not pairs or any(set(p)!={'CE','PE'} for p in pairs.values()):raise ValueError('Unpaired')
        identities.append(ids)
        chains.append(OptionChain(symbol,expiry,snap['date'],'UNVERIFIED_RAW','NSE_ARCHIVE',tuple(OptionRow(k,p['CE'],p['PE']) for k,p in pairs.items())))
    if identities[0]!=identities[1] or len(lots)!=1:raise ValueError('Contract universe changed')
    x=compare_options(chains[1],chains[0],expected_strikes=[r.strike for r in chains[0].rows],latest_session=new['date'],previous_session=old['date'])
    return clean({'status':'PROVISIONAL','expiry':expiry,'strikes':len(chains[0].rows),'unit':'UNVERIFIED_RAW','pcr_previous':x['previous']['pcr'],'pcr_current':x['current']['pcr'],'pcr_direction':x['pcr_direction'],'call_walls_previous':x['previous']['call_walls'],'put_walls_previous':x['previous']['put_walls'],'call_walls':x['current']['call_walls'],'put_walls':x['current']['put_walls'],'max_pain':x['current']['max_pain_strikes'],'call_oi_change':x['call_oi_change'],'put_oi_change':x['put_oi_change']})

def cash_signal(row, sessions):
    """User-approved rule: sign of five completed-session net; no DII offset."""
    try:
        if row.get('status')!='PASS' or len(sessions)!=5 or len(set(sessions))!=5:
            return None
        if sessions!=sorted(sessions,reverse=True):return None
        observations=row['observations']
        if [x['date'] for x in observations]!=sessions:return None
        nets=[]
        for x in observations:
            buy,sell,net=(Decimal(str(x[k])) for k in ('buy_raw','sell_raw','net_raw'))
            if not all(v.is_finite() for v in (buy,sell,net)) or min(buy,sell)<0 or buy-sell!=net:return None
            nets.append(net)
        total=sum(nets)
        if Decimal(str(row['net_sum_last_5_raw']))!=total:return None
        return (total>0)-(total<0)
    except (KeyError,TypeError,ValueError,InvalidOperation):return None

def cash_signals(results,sessions):
    signals={}
    for label,key in [('FII cash','fii_cash'),('DII cash','dii_cash')]:
        matches=[r for r in results if r.get('check')==label]
        signals[key]=cash_signal(matches[0],sessions) if len(matches)==1 else None
    return signals

def compact_flows(results):
    output=[]
    for r in results if isinstance(results,list) else []:
        if r.get('check')=='Provider session calendar':continue
        keys=['check','status','reason','scope','instrument_key','expiry','daily_observations','intraday_closed_session_fallback','observations','net_sum_last_3_raw','net_sum_last_5_raw','units']
        item={k:r[k] for k in keys if k in r}
        if r.get('check') in ('FII cash','DII cash'):
            item['units']='₹ cr'
            item['unit_basis']='User-specified assumption; no rescaling; independent reconciliation pending'
        output.append(item)
    return output

def redact(x):
    # Defence in depth before either artifact or compact handoff is written.
    for name in ('UPSTOX_ANALYTICS_TOKEN','MARKETAUX_API_TOKEN','GITHUB_TOKEN'):
        token=os.environ.get(name,'')
        if token:x=news.redact(x,token)
    return x

def main():
    now=dt.datetime.now(IST);cutoff=now.replace(hour=7,minute=45,second=0,microsecond=0)
    policy=config()
    thresholds={'bullish_threshold':policy['bullish_threshold'],'bearish_threshold':policy['bearish_threshold']}
    if now<cutoff:raise SystemExit('Not yet at report cutoff; no previous-day substitution')
    day=now.date();target=Path('handoff')/(str(day)+'.json')
    if target.exists():
        print('Snapshot already exists; no repeat provider requests');return
    compact={'schema_version':1,'report_date':str(day),'cutoff_IST':cutoff.isoformat(),'collected_at_IST':now.isoformat(),'mode':'PARTIAL_TRIAL','source_run':os.environ.get('GITHUB_RUN_ID'),'options':{},'global':[],'calendar':[],'news':[],'vix_flag':'UNKNOWN','shadow_signals':{},'score':clean(score_summary({},**thresholds)),'limitations':['OI units/calendar pending. Cash: ₹ cr per user assumption; no rescaling; unit reconciliation pending.','Draft trial mapping retained; no added MCP/VIX points.','PCR and walls are correlated; no DII-offset bonus.','Provider redistribution rights remain unverified.']}
    full={}
    api=attempt(lambda:flows.API(os.environ.get('UPSTOX_ANALYTICS_TOKEN','')))
    if isinstance(api,dict):
        compact['collection_status']='BLOCKED';compact['trading_day']='UNVERIFIED'
    else:
        session=attempt(lambda:flows.calendar_day(api.get('/market/timings/'+str(day)),day))
        if isinstance(session,dict) and 'status' not in session:
            compact['trading_day']='OPEN' if 'NSE' in session and 'NFO' in session else 'CLOSED'
        else:compact['trading_day']='UNVERIFIED'
        if compact['trading_day']=='OPEN':
            results=attempt(lambda:flows.run_checks(api,cutoff,observed_now=now));full['flows']=results
            compact['flows']=compact_flows(results)
            cal=next((r for r in results if r.get('check')=='Provider session calendar' and r.get('status')=='PASS'),None) if isinstance(results,list) else None
            if cal:
                compact['completed_sessions']=cal['completed_sessions']
                compact['score']=clean(score_summary(cash_signals(results,cal['completed_sessions']['NSE']),**thresholds))
                dates=cal['completed_sessions']['NFO']
                if len(dates)==2 and all(d<str(day) for d in dates):
                    for d in dates:full[d]=attempt(lambda d=d:get_archive(dt.date.fromisoformat(d),day))
                    for symbol in ('NIFTY','BANKNIFTY'):
                        compact['options'][symbol]=attempt(lambda symbol=symbol:option_summary(full[dates[1]],full[dates[0]],symbol))
                    compact['archive_sources']=[full[d].get('source') for d in dates]
                    fii=next((r for r in results if r.get('check')=='FII index-futures positions' and r.get('status')=='PASS'),None)
                    if fii and fii['latest_date']==dates[0]:
                        net=fii['observations'][0]['net_contracts'];compact['score']=clean(score_summary({**compact['score']['signals'],'fii_futures':(net>0)-(net<0)},**thresholds))
                    # Withhold futures until source consistency is established. Keep observations for audit.
                    compact['futures_validation']='WITHHELD: archive/provider OI and close semantics require reconciliation'
            quotes=attempt(lambda:api.get('/market-quote/quotes',{'instrument_key':flows.INDICES['India VIX']}))
            compact['vix']=attempt(lambda:flows.quote(quotes,flows.INDICES['India VIX'],now))
            try:
                vt=dt.datetime.fromisoformat(compact['vix']['last_trade_time_IST'])
                if vt.tzinfo is None or vt>cutoff or vt.date().isoformat()!=compact.get('completed_sessions',{}).get('NSE',[None])[0]:
                    compact['vix']={'status':'UNAVAILABLE','reason':'Not a confirmed previous-session observation'}
            except (KeyError,ValueError,TypeError,IndexError):
                compact['vix']={'status':'UNAVAILABLE'}
            if compact['vix'].get('status')=='PASS':
                compact['vix']['level']=compact['vix'].get('last_price')
                compact['vix_flag']=vix_caution(compact['vix']['level'],threshold=policy['vix_caution_threshold'])
                try:
                    matches=[r for r in quotes.values() if isinstance(r,dict) and r.get('instrument_token')==flows.INDICES['India VIX']]
                    previous=Decimal(str(matches[0].get('cp'))) if len(matches)==1 else None
                    current=Decimal(str(compact['vix']['level']))
                    if previous is not None and previous.is_finite() and previous>0 and current.is_finite():
                        compact['vix']['change_1d']=str(current-previous)
                        compact['vix']['previous_close']=str(previous)
                    else:compact['vix']['change_1d']=None
                except (InvalidOperation,TypeError,ValueError):compact['vix']['change_1d']=None
                compact['vix']['change_reason']=None if compact['vix']['change_1d'] is not None else 'Previous close unavailable'
            gapi=attempt(lambda:global_data.API(os.environ.get('UPSTOX_ANALYTICS_TOKEN','')))
            if not isinstance(gapi,dict):
                instruments=attempt(lambda:global_data.instruments(global_data.global_file()))
                if isinstance(instruments,dict) and 'status' not in instruments:
                    for name,item in instruments.items():
                        r=attempt(lambda item=item:global_data.indicator_check(gapi,item,cutoff) if item['segment']=='GLOBAL_INDICATOR' else global_data.global_quote_check(gapi,item,now))
                        full.setdefault('global',[]).append(r)
                        stamp=r.get('last_trade_IST',r.get('bar_start_IST'))
                        eligible=False
                        try:
                            t=dt.datetime.fromisoformat(stamp);eligible=t.tzinfo is not None and cutoff-dt.timedelta(hours=18)<=t<=cutoff
                            if 'bar_start_IST' in r:eligible=eligible and t+dt.timedelta(minutes=1)<=cutoff
                        except (ValueError,TypeError):pass
                        compact['global'].append({'name':name,'value':r.get('last_price',r.get('last_closed_minute_price')) if eligible else None,'asof':stamp if eligible else None,'status':'PROVISIONAL' if eligible else 'UNAVAILABLE','note':'Benchmark, units and market-session freshness unverified'})
            news.MAX_PAGES=2
            n=attempt(lambda:news.run_checks(news.API(os.environ.get('MARKETAUX_API_TOKEN',''),max_requests=6),now));full['news']=n
            compact['news_status']=n.get('status','UNAVAILABLE')
            compact['news']=[{k:r.get(k) for k in ('title','url','published_IST')} for r in n.get('articles',[])[:6]]
            compact['news_note']='Selected-query sample: max 6 HTTP attempts / 6 displayed articles; not exhaustive. Paraphrased syndication may remain.'
            c=attempt(lambda:calendar.run(now));full['calendar']=c
            compact['calendar']= [{k:r.get(k) for k in ('title','agency','date_IST','scheduled_IST','source')} for r in c.get('events',[])[:6]]
            compact['calendar_status']='PARTIAL'
    compact['shadow_signals']=build(full.get('flows'),compact['options'].get('NIFTY'),compact.get('completed_sessions',{}).get('NFO',[]),str(day),policy['shadow_signals_enabled'])
    compact['collection_status']=compact.get('collection_status','PARTIAL' if compact['trading_day']=='OPEN' else compact['trading_day'])
    compact['timing']='ON_TIME_COLLECTION' if now<=cutoff+dt.timedelta(minutes=10) else 'LATE_COLLECTION'
    compact=redact(compact);full=redact(full)
    # Do not hide source failure in an overall verified/success claim.
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(compact,indent=2,allow_nan=False))
    Path('out').mkdir(exist_ok=True);Path('out/raw-snapshot.json').write_text(json.dumps(clean(full),allow_nan=False))
    Path('handoff/latest.json').write_text(json.dumps({'report_date':str(day),'path':str(target),'snapshot_sha256':digest(compact),'status':compact['collection_status'],'trading_day':compact['trading_day']},indent=2))
    print('HANDOFF_READY',compact['collection_status'],'compact_bytes',target.stat().st_size)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('## Collection completed\n\nData status: '+compact['collection_status']+'\n\nCompact handoff saved; missing fields remain unavailable. No report sent.\n')
if __name__=='__main__':main()
