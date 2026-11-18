"""Explicit rules for the six existing score slots and separate VIX flag."""
from decimal import Decimal, InvalidOperation
import re
from nse_report.calculations import FutureBar, futures_build_up

VIX_LEVEL_CAUTION = Decimal('20')
VIX_CHANGE_CAUTION_PCT = Decimal('8')

def finite_positive(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None

def futures_point(rows, sessions):
    """Nifty's nearest selected future, same instrument/expiry on D and D-1."""
    matches = [r for r in rows if r.get('check') == 'NIFTY futures']
    if len(matches) != 1 or matches[0].get('status') != 'PASS' or len(sessions) != 2:
        return None
    row = matches[0]
    obs = row.get('daily_observations', [])
    if len(obs) != 2 or [x.get('date') for x in obs] != sessions:
        return None
    try:
        bars = [FutureBar(row['instrument_key'], row['expiry'], x['date'], x['close'],
                          x['oi_raw'], 'raw provider OI', 'Upstox') for x in obs]
        kind = futures_build_up(*bars, latest_session=sessions[0], previous_session=sessions[1])['classification']
    except (KeyError, TypeError, ValueError):
        return None
    return 1 if kind in ('LONG_BUILD_UP', 'SHORT_COVERING') else -1 if kind in (
        'SHORT_BUILD_UP', 'LONG_UNWINDING') else 0

def option_points(option, spot):
    if option.get('status') != 'PROVISIONAL' or finite_positive(option.get('pcr_current')) is None or finite_positive(option.get('pcr_previous')) is None:
        return None, None
    pcr = {'UP': 1, 'DOWN': -1, 'UNCHANGED': 0}.get(option.get('pcr_direction'))
    calls, puts = option.get('call_walls'), option.get('put_walls')
    level = finite_positive(spot.get('close')) if spot.get('status') == 'PASS' else None
    if level is None or not isinstance(calls, list) or not isinstance(puts, list) or len(calls) != 1 or len(puts) != 1:
        return pcr, None
    call, put = finite_positive(calls[0]), finite_positive(puts[0])
    if call is None or put is None or not put < level < call:
        return pcr, None
    # Closer support is +1; closer resistance is -1; a tie is unavailable.
    support, resistance = level - put, call - level
    return pcr, (1 if support < resistance else -1 if resistance < support else None)

def vix_flag(daily):
    if daily.get('status') != 'PASS':
        return 'UNKNOWN'
    level = finite_positive(daily.get('close'))
    try:
        change = Decimal(str(daily.get('change_pct')))
    except (InvalidOperation, TypeError, ValueError):
        return 'UNKNOWN'
    if level is None or not change.is_finite():
        return 'UNKNOWN'
    return 'CAUTION' if level >= VIX_LEVEL_CAUTION or change >= VIX_CHANGE_CAUTION_PCT else 'NORMAL'

INDIA_TERMS = ('nifty', 'sensex', 'rbi', 'rupee', 'fii', 'reliance', 'hdfc',
               'icici', 'infosys', 'tcs', 'adani', 'bajaj finance')
GLOBAL_TERMS = ('fed', 'fomc', 'treasury', 'us yield', 'crude', 'brent', 'opec', 'oil', 'tariff', 'geopolit')
UNRELATED_TERMS = ('personal finance', 'credit card', 'mortgage', 'lottery', 'celebrity',
                   'real estate tips', 'oil indicators', 'reservoir discovery', 'drilling site')

def select_news(articles, limit=8):
    """Rank dated, deduplicated provider articles; quotas are targets, not invented news."""
    ranked=[]
    for row in articles:
        title=str(row.get('title') or '').casefold()
        if not title or not row.get('url') or not row.get('published_IST'):
            continue
        india=sum(term in title for term in INDIA_TERMS)
        global_=sum(term in title for term in GLOBAL_TERMS)
        penalty=sum(term in title for term in UNRELATED_TERMS)
        score=3*india+2*global_-8*penalty
        if score<=0:continue
        ranked.append((score, row['published_IST'], 'india' if india>=global_ else 'global', row))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=[];used=set()
    for group,count in (('india',3),('global',2)):
        for _,_,kind,row in ranked:
            identity=re.sub(r'\W+',' ',row['title'].casefold()).strip()
            if kind==group and identity not in used and len([x for x in chosen if x[0]==group])<count:
                chosen.append((kind,row));used.add(identity)
    for _,_,kind,row in ranked:
        identity=re.sub(r'\W+',' ',row['title'].casefold()).strip()
        if len(chosen)>=limit:break
        if identity not in used:chosen.append((kind,row));used.add(identity)
    return [row for _,row in chosen]

US_RELEASES = ('consumer price', 'cpi', 'producer price', 'ppi', 'employment situation',
               'job openings', 'jolts', 'gross domestic product', 'gdp',
               'personal consumption expenditures', 'pce', 'retail sales', 'fomc')

def select_events(events, day, option_expiries=()):
    us=[row for row in events if row.get('agency') not in ('MoSPI','RBI') and
        any(term in str(row.get('title','')).casefold() for term in US_RELEASES)]
    india=[row for row in events if row.get('agency') in ('MoSPI','RBI') and row.get('date_IST')==day]
    for name,expiry in option_expiries:
        if expiry==day:
            india.append({'title':f'{name} option expiry','date_IST':day,'scheduled_IST':None,
                          'source':'NSE archive selected contract'})
    return us,india

def caption(snapshot, review):
    def fmt(value, signed=False):
        try:
            number=Decimal(str(value))
            if not number.is_finite():return 'N/A'
            return f'{number:+.2f}' if signed else f'{number:.2f}'
        except (InvalidOperation,TypeError,ValueError):return 'N/A'
    global_={row.get('name'):row for row in snapshot.get('global',[])}
    nifty=snapshot.get('spot',{}).get('NIFTY',{})
    gift=global_.get('GIFT NIFTY',{})
    gap=None
    if (gift.get('status')=='PROVISIONAL' and str(gift.get('asof','')).startswith(snapshot['report_date'])
            and nifty.get('status')=='PASS' and finite_positive(gift.get('value'))
            and finite_positive(nifty.get('close'))):
        gap=Decimal(str(gift['value']))-Decimal(str(nifty['close']))
    cash={row.get('check'):row for row in snapshot.get('flows',[])}
    daily=lambda name: ((cash.get(name,{}).get('observations') or [{}])[0].get('net_raw')
                        if cash.get(name,{}).get('status')=='PASS' else None)
    score=snapshot['score']
    lines=[
        f"{snapshot['report_date']} | NSE morning brief",
        f"{score['bias']} | score {score['score']:+d} ({score['available']}/6)",
        'GIFT vs Nifty close: '+(fmt(gap,True)+' pts' if gap is not None else 'N/A'),
        'Brent '+fmt(global_.get('Oil (Brent)',{}).get('value'))+' | USD/INR '+fmt(global_.get('USD INR',{}).get('value'))+' | US quote '+fmt(global_.get('DOW JONES',{}).get('value')),
        'FII '+fmt(daily('FII cash'),True)+' / DII '+fmt(daily('DII cash'),True)+' ₹ cr',
        'Watch: '+str((review.get('alerts') or ['N/A'])[0])[:150],
    ]
    return '\n'.join(lines)
