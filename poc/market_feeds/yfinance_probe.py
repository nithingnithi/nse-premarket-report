"""Read-only experimental yfinance probe; never fetch without --live."""
import argparse, datetime as dt, json, math, sys
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
SYMBOLS={'S&P 500':'^GSPC','Nasdaq':'^IXIC','Dow Jones':'^DJI','Nikkei 225':'^N225','Hang Seng':'^HSI','Brent crude':'BZ=F','Gold futures':'GC=F','USD/INR':'INR=X','Dollar index':'DX-Y.NYB','US 10Y yield':'^TNX'}

def normalize(name,symbol,frame,cutoff,max_age_hours=120):
    if frame is None or getattr(frame,'empty',True):
        return {'name':name,'symbol':symbol,'status':'UNAVAILABLE','reason':'No daily bars'}
    closes=[]
    for idx,value in zip(frame.index,frame['Close']):
        try:
            val=float(value)
            stamp=idx.to_pydatetime() if hasattr(idx,'to_pydatetime') else idx
            if stamp.tzinfo is None:
                return {'name':name,'symbol':symbol,'status':'UNAVAILABLE','reason':'Unzoned source timestamp'}
            stamp=stamp.astimezone(IST)
            if math.isfinite(val) and val>0 and stamp<=cutoff: closes.append((stamp,val))
        except (TypeError,ValueError,OverflowError,AttributeError):
            continue
    if not closes:
        return {'name':name,'symbol':symbol,'status':'UNAVAILABLE','reason':'No valid timestamped close at cutoff'}
    closes.sort()
    stamp,last=closes[-1]
    if (cutoff-stamp).total_seconds()>max_age_hours*3600:
        return {'name':name,'symbol':symbol,'status':'STALE','reason':'Daily bar older than limit','asof_ist':stamp.isoformat()}
    prev=closes[-2][1] if len(closes)>=2 else None
    return {'name':name,'symbol':symbol,'status':'OBSERVED','source':'yfinance (unofficial)','interval':'1d',
            'asof_ist':stamp.isoformat(),'close':round(last,5),'previous_close':round(prev,5) if prev else None,
            'change_pct':round(100*(last/prev-1),3) if prev else None,
            'caveat':'Daily bar stamp may represent session start, not an official closing time'}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true')
    p.add_argument('--cutoff-ist',help='Timezone-aware ISO timestamp')
    args=p.parse_args(argv)
    cutoff=dt.datetime.fromisoformat(args.cutoff_ist).astimezone(IST) if args.cutoff_ist else dt.datetime.now(IST)
    if not args.live:
        print(json.dumps({'status':'DISABLED','reason':'Pass --live for network requests','data':[],'cutoff_ist':cutoff.isoformat()}))
        return 0
    try: import yfinance as yf
    except ImportError:
        print('Install yfinance for --live',file=sys.stderr); return 2
    rows=[]
    for name,symbol in SYMBOLS.items():
        try: rows.append(normalize(name,symbol,yf.Ticker(symbol).history(period='10d',interval='1d',timeout=12,auto_adjust=False),cutoff))
        except Exception: rows.append({'name':name,'symbol':symbol,'status':'UNAVAILABLE','reason':'Provider request failed (details withheld)'})
    print(json.dumps({'status':'PROBE_ONLY','cutoff_ist':cutoff.isoformat(),'data':rows,'production_scoring_enabled':False},indent=2,allow_nan=False))
    return 0
if __name__=='__main__': sys.exit(main())
