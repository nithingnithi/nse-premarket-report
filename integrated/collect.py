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
import urllib.parse
from integrated.adapters import flows, global_data, news, calendar, archive
from nse_report.calculations import OptionChain, OptionRow, compare_options, option_metrics, score_summary
from integrated.brief_v3 import futures_point, option_points, vix_flag, select_news, select_events
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
    if len(lots)!=1:raise ValueError('Multiple lot sizes in selected option expiry')
    if identities[0]!=identities[1]:
        current=option_metrics(chains[1],expected_strikes=[r.strike for r in chains[1].rows])
        old_keys,new_keys=set(identities[0]),set(identities[1])
        changed=sum(identities[0][k]!=identities[1][k] for k in old_keys & new_keys)
        reason=(f'Contract universe changed: {len(new_keys-old_keys)} added, '
                f'{len(old_keys-new_keys)} removed, {changed} changed IDs; '
                'PCR direction and OI change withheld')
        return clean({'status':'PARTIAL','reason':reason,'expiry':expiry,
                      'strikes':len(chains[1].rows),'unit':'UNVERIFIED_RAW',
                      'pcr_previous':None,'pcr_current':current['pcr'],
                      'pcr_direction':None,'call_walls':current['call_walls'],
                      'put_walls':current['put_walls'],
                      'max_pain':current['max_pain_strikes'],
                      'call_oi_change':None,'put_oi_change':None})
    x=compare_options(chains[1],chains[0],expected_strikes=[r.strike for r in chains[0].rows],latest_session=new['date'],previous_session=old['date'])
    return clean({'status':'PROVISIONAL','expiry':expiry,'strikes':len(chains[0].rows),'unit':'UNVERIFIED_RAW','pcr_previous':x['previous']['pcr'],'pcr_current':x['current']['pcr'],'pcr_direction':x['pcr_direction'],'call_walls':x['current']['call_walls'],'put_walls':x['current']['put_walls'],'max_pain':x['current']['max_pain_strikes'],'call_oi_change':x['call_oi_change'],'put_oi_change':x['put_oi_change']})

def global_row(name, result, cutoff):
    """Keep useful prior-session observations, never post-cutoff quotes."""
    row={'name':name,'value':None,'asof':None,'status':'UNAVAILABLE',
         'reason':'No validated provider observation'}
    if result.get('status')!='PASS':
        row['reason']=result.get('reason') or 'Provider schema or timestamp check incomplete'
        return row
    price=result.get('last_price',result.get('last_closed_minute_price'))
    stamp=result.get('last_trade_IST',result.get('bar_start_IST'))
    if not global_data.number(price,positive=True) or not isinstance(stamp,str):
        row['reason']='Price or observation time missing'
        return row
    try:
        observed=dt.datetime.fromisoformat(stamp)
        if observed.tzinfo is None:raise ValueError('no timezone')
    except ValueError:
        row['reason']='Observation time has no valid timezone'
        return row
    if 'bar_start_IST' in result and observed+dt.timedelta(minutes=1)>cutoff:
        row.update(status='AFTER CUTOFF',reason='One-minute bar was unfinished at 07:45 IST')
        return row
    if observed>cutoff:
        row.update(status='AFTER CUTOFF',reason='Last trade was after 07:45 IST')
        return row
    age=cutoff-observed
    if age>dt.timedelta(hours=96):
        row.update(status='STALE',reason='Last trade was more than four days before cutoff')
        return row
    row.update(value=price,asof=stamp,status='PROVISIONAL' if age<=dt.timedelta(hours=18) else 'PRIOR QUOTE',
               reason='Last observed quote; market-session completeness not verified')
    try:
        # Upstox documents net_change as LTP minus the previous session close.
        # Its OHLC close can equal the latest price, so it is not this baseline.
        current=Decimal(str(price))
        raw_change=result.get('provider_net_change_raw')
        raw_previous=result.get('previous_close_raw')
        previous=(current-Decimal(str(raw_change)) if raw_change is not None
                  else Decimal(str(raw_previous)))
        change=current-previous
        if current.is_finite() and change.is_finite() and previous.is_finite() and previous>0:
            row['previous_close']=str(previous)
            row['change_pct']=str(change*100/previous)
    except (InvalidOperation,TypeError,ValueError):
        row['change_reason']=result.get('previous_close_reason') or 'No validated previous daily close'
    return row

def index_daily(api, key, sessions, cutoff, exchange='NSE'):
    """Two exact completed exchange sessions; daily bar starts are not quote times."""
    if len(sessions)<2 or not sessions[1]<sessions[0]<cutoff.date().isoformat():
        raise flows.CheckFailure('Two completed '+exchange+' sessions are required')
    path=('/historical-candle/'+urllib.parse.quote(key,safe='')+'/days/1/'
          +sessions[0]+'/'+sessions[1])
    bars=flows.daily_bars(api.get(path,version='v3'),cutoff)
    if any(day not in bars for day in sessions[:2]):
        raise flows.CheckFailure('Daily close missing for a required '+exchange+' session')
    current=Decimal(bars[sessions[0]]['close']);previous=Decimal(bars[sessions[1]]['close'])
    return clean({'status':'PASS','latest_date':sessions[0],'previous_date':sessions[1],
                  'close':current,'previous_close':previous,'change':current-previous,
                  'change_pct':(current-previous)*100/previous,'unit':'index points'})

def index_result(api,key,sessions,cutoff,exchange='NSE'):
    if getattr(api,'auth_failed',False):
        return {'status':'UNAVAILABLE','reason':'Earlier Upstox access was rejected'}
    try:return index_daily(api,key,sessions,cutoff,exchange)
    except flows.CheckFailure as exc:return {'status':'UNAVAILABLE','reason':str(exc)[:160]}
    except Exception:return {'status':'UNAVAILABLE','reason':'Daily index request or schema failed'}

_OPTION_FAILURES={'Expiry changed','Duplicate','Unpaired',
                  'Multiple lot sizes in selected option expiry',
                  'Unexpected option baseline sessions','Mixed option underlying, expiry, units or providers',
                  'Unexpected option strikes','Incomplete option universe','Duplicate option strike'}

def option_result(old,new,symbol):
    try:return option_summary(old,new,symbol)
    except ValueError as exc:
        reason=str(exc)
        return {'status':'UNAVAILABLE','reason':reason if reason in _OPTION_FAILURES else 'Option validation failed'}
    except Exception:return {'status':'UNAVAILABLE','reason':'Option request or schema failed'}

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
    if now<cutoff:raise SystemExit('Not yet at report cutoff; no previous-day substitution')
    day=now.date();target=Path('handoff')/(str(day)+'.json')
    if target.exists():
        print('Snapshot already exists; no repeat provider requests');return
    compact={'schema_version':1,'report_date':str(day),'cutoff_IST':cutoff.isoformat(),'collected_at_IST':now.isoformat(),'mode':'MORNING_BRIEF','source_run':os.environ.get('GITHUB_RUN_ID'),'options':{},'global':[],'calendar':[],'news':[],'vix_flag':'UNKNOWN','score':clean(score_summary({})),'limitations':['Cash: ₹ cr per user assumption; no rescaling. Futures and option OI use raw provider counts.','PCR and walls are correlated; no DII-offset bonus.','Provider redistribution rights remain unverified.']}
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
                compact['score']=clean(score_summary(cash_signals(results,cal['completed_sessions']['NSE'])))
                sessions=cal['completed_sessions']['NSE']
                compact['spot']={name:index_result(api,flows.INDICES[source],sessions,cutoff) for name,source in
                                 (('NIFTY','Nifty'),('BANKNIFTY','Bank Nifty'),
                                  ('MIDCAP100','Midcap 100'),('SMALLCAP100','Smallcap 100'))}
                compact['spot']['SENSEX']=index_result(api,flows.INDICES['Sensex'],
                    cal['completed_sessions'].get('BSE',[]),cutoff,'BSE')
                compact['sectors']={name:index_result(api,flows.INDICES[name],sessions,cutoff) for name in
                                    ('PSU Bank','Realty','Auto','FMCG','Energy','IT')}
                compact['vix_daily']=index_result(api,flows.INDICES['India VIX'],sessions,cutoff)
                compact['vix_flag']=vix_flag(compact['vix_daily'])
                dates=cal['completed_sessions']['NFO']
                if len(dates)==2 and all(d<str(day) for d in dates):
                    for d in dates:full[d]=attempt(lambda d=d:get_archive(dt.date.fromisoformat(d),day))
                    for symbol in ('NIFTY','BANKNIFTY'):
                        compact['options'][symbol]=option_result(full[dates[1]],full[dates[0]],symbol)
                    compact['archive_sources']=[full[d].get('source') for d in dates]
                    fii=next((r for r in results if r.get('check')=='FII index-futures positions' and r.get('status')=='PASS'),None)
                    if fii and fii['latest_date']==dates[0]:
                        net=fii['observations'][0]['net_contracts'];compact['score']=clean(score_summary({**compact['score']['signals'],'fii_futures':(net>0)-(net<0)}))
                    signals=compact['score']['signals']
                    signals['futures_build_up']=futures_point(results,dates)
                    signals['pcr_direction'],signals['strike_walls']=option_points(
                        compact['options'].get('NIFTY',{}),compact['spot'].get('NIFTY',{}))
                    compact['score']=clean(score_summary(signals))
            quotes=attempt(lambda:api.get('/market-quote/quotes',{'instrument_key':flows.INDICES['India VIX']}))
            compact['vix']=attempt(lambda:flows.quote(quotes,flows.INDICES['India VIX'],now))
            try:
                vt=dt.datetime.fromisoformat(compact['vix']['last_trade_time_IST'])
                if vt.tzinfo is None or vt>cutoff or vt.date().isoformat()!=compact.get('completed_sessions',{}).get('NSE',[None])[0]:
                    compact['vix']={'status':'UNAVAILABLE','reason':'Not a confirmed previous-session observation'}
            except (KeyError,ValueError,TypeError,IndexError):
                compact['vix']={'status':'UNAVAILABLE'}
            gapi=attempt(lambda:global_data.API(os.environ.get('UPSTOX_ANALYTICS_TOKEN','')))
            if not isinstance(gapi,dict):
                instruments=attempt(lambda:global_data.instruments(global_data.global_file()))
                if isinstance(instruments,dict) and 'status' not in instruments:
                    for name,item in instruments.items():
                        r=attempt(lambda item=item:global_data.indicator_check(gapi,item,cutoff) if item['segment']=='GLOBAL_INDICATOR' else global_data.global_quote_check(gapi,item,now))
                        full.setdefault('global',[]).append(r)
                        compact['global'].append(global_row(name,r,cutoff))
            news.MAX_PAGES=4
            n=attempt(lambda:news.run_checks(news.API(os.environ.get('MARKETAUX_API_TOKEN',''),max_requests=12),now));full['news']=n
            compact['news_status']=n.get('status','UNAVAILABLE')
            compact['news_requests_used']=n.get('http_attempts',0)
            selected=select_news(n.get('articles',[]))
            compact['news']=[{k:r.get(k) for k in ('title','url','source','published_IST')} for r in selected]
            failure=next((row.get('reason') for row in n.get('queries',[]) if row.get('status')=='FAIL'),None)
            compact['news_note']=(('News unavailable: '+str(n.get('reason') or failure)[:100])
                if not selected and (n.get('reason') or failure) else
                f'{len(selected)} shown of {n.get("unique_articles",0)} matched in the window; max 12 requests. Selected queries, not exhaustive.')
            c=attempt(lambda:calendar.run(now));full['calendar']=c
            us_events,india_events=select_events(c.get('events',[]),str(day),
                [(name,row.get('expiry')) for name,row in compact['options'].items()])
            fields=('title','agency','date_IST','scheduled_IST','source')
            compact['calendar']=[{k:r.get(k) for k in fields} for r in us_events[:6]]
            compact['today_india']=[{k:r.get(k) for k in fields} for r in india_events[:4]]
            compact['india_corporate_events']='N/A: official results, ex-date and IPO feed not validated'
            compact['calendar_note']=(next((row.get('reason') for row in c.get('checks',[]) if row.get('status') in ('FAIL','BLOCKED')),None)
                                      or 'No whitelisted release in the next seven days')
            compact['calendar_status']='PARTIAL'
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
