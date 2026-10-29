"""Two-page rules-based briefing. Rendering never changes the official score."""
import datetime as dt
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

NAVY='#102C3C'; TEAL='#007F7B'; INK='#173343'; MUTED='#536C78'; PAPER='#F2F5F5'; AMBER='#9A6200'
IST=dt.timezone(dt.timedelta(hours=5,minutes=30))

def val(x):
    if x is None or x=='' or x==[]: return 'N/A'
    if isinstance(x,(list,tuple)): return ', '.join(val(y) for y in x)
    return str(x)

def num(x,places=2,sign=False):
    try:
        if x is None: return 'N/A'
        d=Decimal(str(x))
        if not d.is_finite(): return 'N/A'
        result=f'{d:,.{places}f}'
        if places: result=result.rstrip('0').rstrip('.')
        return ('+' if sign and d>0 else '')+result
    except (InvalidOperation,ValueError,TypeError): return 'N/A'

def brief(x,limit=90):
    s=val(x).replace('\n',' ').strip()
    return s if len(s)<=limit else s[:limit-1].rstrip()+'…'

def stamp(x):
    try:
        d=dt.datetime.fromisoformat(x)
        return d.astimezone(IST).strftime('%d %b %H:%M IST') if d.tzinfo else 'N/A'
    except (ValueError,TypeError): return 'N/A'

def distance(level,spot):
    try:
        if isinstance(level,(tuple,list)):
            if len(level)!=1: return 'N/A (tied level)'
            level=level[0]
        if level is None or spot is None: return 'N/A (spot or level missing)'
        d=Decimal(str(level))-Decimal(str(spot))
        if not d.is_finite(): raise ValueError
        return num(d,0,True)+' pts'
    except (InvalidOperation,ValueError,TypeError): return 'N/A (spot or level missing)'

def level_text(level):
    if isinstance(level,(tuple,list)):
        return num(level[0],0) if len(level)==1 else 'N/A (tied level)' if level else 'N/A (missing level)'
    return num(level,0)

def render(s,r,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/System/Library/Fonts/Supplemental/Georgia.ttf'):
        if Path(candidate).exists():
            font=TTFont('CashCurrency',candidate)
            if 0x20B9 in font.face.charToGlyph:
                pdfmetrics.registerFont(font); break
    else: raise ValueError('Rupee font unavailable')
    c=canvas.Canvas(str(path),pagesize=(595,842)); c.setTitle('NSE Morning Brief | '+s['report_date'])
    def rect(x,y,w,h,color):
        c.setFillColor(HexColor(color)); c.roundRect(x,y-h,w,h,5,stroke=0,fill=1)
    def p(x,y,w,content,size=8,color=INK,bold=False,maxh=None):
        safe=escape(val(content)).replace('₹','<font name="CashCurrency">₹</font>')
        style=ParagraphStyle('body',fontName='Helvetica-Bold' if bold else 'Helvetica',fontSize=size,leading=size*1.22,textColor=HexColor(color))
        obj=Paragraph(safe,style); _,h=obj.wrap(w,842)
        if maxh and h>maxh: raise ValueError('PDF section overflow')
        obj.drawOn(c,x,y-h); return h
    def section(n,title,y):
        rect(28,y,20,18,TEAL); p(33,y-3,13,n,8,'#FFFFFF',True)
        p(57,y-1,505,title,11,INK,True)
    def base(page,title):
        rect(0,842,595,842,PAPER); rect(0,842,595,112,NAVY)
        rect(28,814,4,49,'#36D2BA')
        p(43,814,450,'NSE / MORNING BRIEF',10,'#76DCCD',True)
        p(42,792,510,title,25,'#FFFFFF',True)
        p(43,754,510,dt.date.fromisoformat(s['report_date']).strftime('%d %B %Y')+'  |  07:45 IST cutoff',8.5,'#BDD1D9')
        c.setStrokeColor(HexColor('#D5E1E3')); c.line(28,29,567,29)
        p(28,21,460,'Rules-based report  •  Missing data shown as N/A',6.5,MUTED)
        p(525,21,42,f'{page:02d} / 02',6.5,MUTED,True)
    def option_card(x,name,opt,spot):
        rect(x,355,264,84,'#FFFFFF')
        status='OK' if opt.get('status')=='PROVISIONAL' else 'N/A'
        p(x+10,344,245,name+'  •  '+status,9,INK,True)
        p(x+10,329,245,'Expiry '+val(opt.get('expiry'))+'  |  PCR '+num(opt.get('pcr_current'),3),7.5)
        for i,(title,key) in enumerate((('Call wall','call_walls'),('Put wall','put_walls'),('Max pain','max_pain'))):
            level=opt.get(key)
            p(x+10,315-i*13,245,title+': '+level_text(level)+'  •  '+distance(level,spot),7.2,maxh=11)
        if status!='OK': p(x+10,276,245,brief(opt.get('reason','Same-expiry option baseline unavailable'),55),6.5,MUTED,maxh=9)
    def linked_headline(item,y):
        outlet=item.get('source') or urlsplit(item.get('url') or '').hostname or 'Unknown outlet'
        p(28,y,539,brief(outlet,36)+'  •  '+stamp(item.get('published_IST')),6.5,MUTED)
        p(28,y-10,539,brief(item.get('title'),124),7.3,TEAL,maxh=18)
        url=item.get('url') or ''; parsed=urlsplit(url)
        if parsed.scheme=='https' and parsed.netloc: c.linkURL(url,(28,y-28,567,y),relative=0)
    score=s['score']; rows={x.get('check'):x for x in s.get('flows',[]) if isinstance(x,dict)}
    base(1,'The morning view')
    rect(28,713,539,94,'#FFFFFF')
    p(42,701,510,'OFFICIAL SIX-SIGNAL SCORE',7,TEAL,True)
    bias=score['bias']
    p(42,684,510,'Insufficient data for final bias' if bias=='INSUFFICIENT DATA TO ASSIGN FINAL BIAS' else bias.title(),18,INK,True,maxh=23)
    p(42,655,510,'Score '+num(score['score'],0,True)+'  |  Coverage '+str(score['available'])+'/6  |  Possible range '+val(score['score_range']),9,TEAL,True)
    missing=', '.join(k.replace('_',' ') for k in score['missing']) or 'none'
    p(42,639,510,'Missing: '+brief(missing,113),7.4,MUTED,maxh=12)
    vix=s.get('vix') or {}
    p(42,627,510,'India VIX '+num(vix.get('level'))+'  |  1-day '+num(vix.get('change_1d'),2,True)+'  |  Caution '+val(s.get('vix_flag')),7.4,AMBER,maxh=10)
    section('01','Three factual alerts',606)
    for i,a in enumerate((r.get('alerts') or [])[:3]):
        x=28+i*183; rect(x,580,173,47,'#FFFFFF')
        p(x+9,570,155,brief(a,100),7.2,maxh=32)
    section('02','Index close and futures positioning',521)
    for i,(name,key) in enumerate((('Nifty','NIFTY'),('Bank Nifty','BANKNIFTY'))):
        x=28+i*275; rect(x,495,264,100,'#FFFFFF')
        spot=(s.get('indices') or {}).get(name) or {}
        f=rows.get(key+' futures') or {}; bars=f.get('daily_observations') or []
        latest=bars[0] if bars else {}
        context=(s.get('futures_context') or {}).get(key) or {}
        p(x+10,483,245,name,11,INK,True)
        p(x+10,466,245,'Spot '+num(spot.get('last_price'))+'  ('+num(spot.get('change'),2,True)+')',8.4,TEAL,True)
        if spot.get('last_price') is None:
            p(x+10,453,245,brief(spot.get('reason','Completed-session quote unavailable'),58),6.5,MUTED)
        p(x+10,440,245,'Future '+('OK ' if latest.get('close') is not None else 'N/A ')+num(latest.get('close'))+'  ('+num(f.get('delta_close'),2,True)+')',8)
        p(x+10,425,245,'OI '+num(latest.get('oi_raw'),0)+' provider counts  ('+num(f.get('delta_oi_raw'),0,True)+')',7.2)
        build_status='OK' if context.get('value') is not None else 'WITHHELD'
        p(x+10,411,245,'Build-up '+build_status+': '+brief(context.get('reason','No qualified observation'),49),7,MUTED,maxh=18)
    section('03','Option levels and distance from spot',381)
    for i,(name,key) in enumerate((('Nifty','NIFTY'),('Bank Nifty','BANKNIFTY'))):
        option_card(28+i*275,name,(s.get('options') or {}).get(key) or {},((s.get('indices') or {}).get(name) or {}).get('last_price'))
    section('04','Shadow signals, not counted',257)
    for i,(key,title) in enumerate((('futures_build_up','Futures'),('pcr_direction','PCR direction'),('strike_walls','Strike walls'))):
        a=(s.get('shadow_signals') or {}).get(key) or {}; top=232-i*21
        rect(28,top+1,539,20,'#FFFFFF')
        p(36,top-4,100,title,7.4,INK,True)
        p(138,top-4,160,'shadow, not counted: '+(num(a['value'],0,True) if a.get('value') is not None else 'N/A'),7,TEAL,True)
        signal_status='OK' if a.get('value') is not None else 'WITHHELD'
        p(302,top-4,255,signal_status+' — '+brief(a.get('reason','No qualified baseline'),54),6.9,MUTED,maxh=10)
    section('05','Market headlines / last 12 hours',162)
    headlines=s.get('news') or []
    for i,item in enumerate(headlines[:3]): linked_headline(item,137-i*30)
    if not headlines: p(28,137,539,'N/A — No eligible market headline returned for this window.',8,MUTED)
    c.showPage()

    base(2,'The numbers and dates')
    section('06','Markets and foreign exchange',712)
    for title,x,w in (('MARKET',35,114),('VALUE',151,80),('PREV CLOSE',236,80),('CHANGE %',320,80),('AS OF / REASON',404,156)):
        p(x,686,w,title,7,TEAL,True)
    markets=s.get('global') or [{'name':'Market data','reason':'No provider observation'}]
    for i,a in enumerate(markets[:9]):
        top=669-i*18
        if i%2==0: rect(28,top+2,539,17,'#FFFFFF')
        p(35,top,114,brief(a.get('name'),22),7.3)
        p(151,top,80,num(a.get('value')),7.3,INK,True)
        p(236,top,80,num(a.get('previous_close')),7.3)
        change=num(a.get('change_pct'),2,True)+'%' if a.get('change_pct') is not None else 'N/A'
        p(320,top,80,change,7.3)
        detail='OK • '+stamp(a.get('asof')) if a.get('value') is not None else 'N/A • '+brief(a.get('reason','No timely quote'),28)
        p(404,top,156,detail,6.6,MUTED,maxh=16)
    p(28,499,539,'N/A previous close or change: the provider did not supply a usable baseline.',6.4,MUTED)
    section('07','Institutional positioning and cash flows',481)
    fii=rows.get('FII index-futures positions') or {}; obs=fii.get('observations') or []
    for i in range(2):
        a=obs[i] if i<len(obs) else {}; top=456-i*17
        p(36,top,165,'FII index futures '+val(a.get('date')),7.4,INK,True)
        p(202,top,353,'Long '+num(a.get('long_contracts'),0)+'  Short '+num(a.get('short_contracts'),0)+'  Net '+num(a.get('net_contracts'),0)+'  L/S '+num(a.get('long_divided_by_short'),2),7.1,maxh=14)
    if not obs: p(36,424,520,'N/A — '+brief(fii.get('reason','FII futures dates unavailable'),75),6.8,MUTED)
    p(36,407,520,'CASH NET (₹ cr)  |  Last five completed sessions',7,TEAL,True)
    fi=rows.get('FII cash') or {}; di=rows.get('DII cash') or {}
    fo=fi.get('observations') or []; do=di.get('observations') or []
    for i in range(5):
        a=fo[i] if i<len(fo) else {}; b=do[i] if i<len(do) else {}; top=391-i*16
        p(36,top,130,val(a.get('date') or b.get('date')),7.3)
        p(175,top,170,'FII '+num(a.get('net_raw'),2,True),7.3)
        p(360,top,190,'DII '+num(b.get('net_raw'),2,True),7.3)
    if not fo or not do:
        p(36,306,520,'N/A: '+brief(fi.get('reason') or di.get('reason') or 'Five-session cash series incomplete',100),6.5,MUTED)
    section('08','More market headlines',288)
    for i,item in enumerate(headlines[3:6]): linked_headline(item,261-i*28)
    if len(headlines)<=3: p(28,261,539,'N/A — No additional eligible headline returned.',7.3,MUTED)
    p(28,171,539,'News scope: '+brief(s.get('news_note','Selected market queries; coverage may be partial'),108),6.2,MUTED)
    section('09','Calendar / dates in IST',154)
    options=s.get('options') or {}; expiries=sorted({a.get('expiry') for a in options.values() if isinstance(a,dict) and a.get('expiry')})
    events=s.get('calendar') or []
    def event_date(term,agency):
        match=next((a for a in events if a.get('agency')==agency and term in (a.get('title') or '').casefold()),None)
        if not match:return 'N/A — no dated '+term.upper()+' item supplied'
        return stamp(match.get('scheduled_IST')) if match.get('scheduled_IST') else val(match.get('date_IST'))+' (time N/A)'
    cal=[('Nifty / Bank Nifty expiry',', '.join(expiries) if expiries else 'N/A — expiry unavailable'),
         ('RBI',event_date('monetary policy','RBI')),('India CPI',event_date('consumer price','MoSPI'))]
    high_impact=('employment situation','consumer price','gross domestic product','personal income','fomc')
    us=[a for a in events if a.get('agency') in ('BLS','BEA','Federal Reserve') and
        any(term in (a.get('title') or '').casefold() for term in high_impact)]
    for a in us[:2]:
        cal.append((brief(a.get('title'),34),stamp(a.get('scheduled_IST')) if a.get('scheduled_IST') else val(a.get('date_IST'))+' (time N/A)'))
    if not us:cal.append(('US high-impact releases','N/A — no dated item supplied'))
    for i,(title,when) in enumerate(cal[:5]):
        top=129-i*17
        p(35,top,260,title,7.1,INK,True)
        p(300,top,260,brief(when,52),7.1,MUTED)
    c.save()
