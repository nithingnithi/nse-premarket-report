"""Guarded candidate signals. Results are displayed only, never added to score."""
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
from nse_report.calculations import FutureBar, futures_build_up

SIGNALS=('futures_build_up','pcr_direction','strike_walls')

def config(path=Path(__file__).with_name('report_config.json')):
    value=json.loads(Path(path).read_text())
    if (type(value.get('bullish_threshold')) is not int or value['bullish_threshold']!=3
        or type(value.get('bearish_threshold')) is not int or value['bearish_threshold']!=-3
        or type(value.get('vix_caution_threshold')) not in (int,float)
        or value['vix_caution_threshold']<=0
        or type(value.get('shadow_signals_enabled')) is not bool):
        raise ValueError('Invalid report policy; six-signal thresholds must remain +3/-3')
    return value

def unavailable(reason):return {'value':None,'status':'WITHHELD','reason':reason}

def candidate(value,reason):return {'value':value,'status':'SHADOW','reason':reason}

def futures(row,days,report_day):
    if not isinstance(row,dict) or row.get('status')!='PASS':return unavailable('Futures data missing or invalid')
    if len(days)!=2 or len(set(days))!=2 or days!=sorted(days,reverse=True):return unavailable('Two completed NFO sessions required')
    if (row.get('latest_date'),row.get('previous_date'))!=tuple(days):return unavailable('Futures sessions do not match calendar D and D-1')
    try:
        if date.fromisoformat(row['expiry'])<date.fromisoformat(report_day):return unavailable('Selected futures expiry precedes report date')
        key=row['instrument_key'];bars=row['daily_observations']
        if not key or len(bars)!=2 or [b['date'] for b in bars]!=days:return unavailable('Same-contract D and D-1 bars required')
        current,previous=(FutureBar(key,row['expiry'],b['date'],b['close'],b['oi_raw'],'RAW_PROVIDER','UPSTOX') for b in bars)
        result=futures_build_up(current,previous,latest_session=days[0],previous_session=days[1])
        mapping={'LONG_BUILD_UP':1,'SHORT_BUILD_UP':-1,'SHORT_COVERING':1,'LONG_UNWINDING':-1}
        kind=result['classification']
        if kind not in mapping:return unavailable('Price or OI unchanged; no build-up classification')
        return candidate(mapping[kind],kind+'; same contract '+key+' on both sessions')
    except (KeyError,TypeError,ValueError):return unavailable('Invalid futures contract, price, OI or expiry')

def options(row):
    missing={'pcr_direction':unavailable('Same-expiry option baseline missing or invalid'),
             'strike_walls':unavailable('Same-expiry option baseline missing or invalid')}
    if not isinstance(row,dict) or row.get('status')!='PROVISIONAL':return missing
    try:
        if not row['expiry'] or row['strikes']<=0:return missing
        walls=[row[k] for k in ('call_walls_previous','put_walls_previous','call_walls','put_walls')]
        if any(not isinstance(w,list) or len(w)!=1 for w in walls):
            reason='Missing or tied call/put OI wall on either session'
            return {k:unavailable(reason) for k in missing}
        old_call,old_put,new_call,new_put=[Decimal(w[0]) for w in walls]
        if not all(x.is_finite() for x in (old_call,old_put,new_call,new_put)):
            return missing
        direction=row['pcr_direction']
        pcr={'UP':1,'DOWN':-1,'UNCHANGED':0}.get(direction)
        result={'pcr_direction':candidate(pcr,'Same-expiry PCR '+direction.lower()) if pcr is not None else unavailable('PCR baseline or denominator unavailable')}
        if new_call>old_call and new_put>old_put:value=1
        elif new_call<old_call and new_put<old_put:value=-1
        else:value=0
        result['strike_walls']=candidate(value,'Unique call/put walls compared across one expiry')
        return result
    except (KeyError,TypeError,InvalidOperation,ValueError):return missing

def build(results,option_row,completed_nfo,report_day,enabled):
    if not enabled:return {k:{'value':None,'status':'DISABLED','reason':'Shadow mode disabled in config'} for k in SIGNALS}
    matches=[r for r in results if r.get('check')=='NIFTY futures'] if isinstance(results,list) else []
    future=futures(matches[0],completed_nfo,report_day) if len(matches)==1 else unavailable('NIFTY futures row missing or duplicated')
    return {'futures_build_up':future,**options(option_row)}
