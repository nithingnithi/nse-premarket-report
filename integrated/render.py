"""Two-page editorial briefing. Visual formatting only; no scoring changes."""
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from decimal import Decimal,InvalidOperation
import datetime as dt
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
NAVY='#102C3C';TEAL='#007F7B';INK='#173343';MUTED='#536C78';PAPER='#F2F5F5';LINE='#D5E1E3';AMBER='#9A6200'
def text(v):
    if v is None or v==[] or v=='':return 'N/A'
    if isinstance(v,(tuple,list)):return ', '.join(text(x) for x in v)
    return escape(str(v))
def number(v,places=2):
    if v is None:return 'N/A'
    if isinstance(v,(list,tuple)):return ', '.join(number(x,places) for x in v)
    try:
        d=Decimal(str(v))
        if not d.is_finite():return 'N/A'
        return f'{d:,.{places}f}'.rstrip('0').rstrip('.') if places else f'{d:,.0f}'
    except (InvalidOperation,ValueError):return text(v)
def stamp(v):
    if not v:return 'N/A'
    try:
        d=dt.datetime.fromisoformat(v);return d.strftime('%d %b %H:%M')+' IST'
    except (ValueError,TypeError):return text(v)
def signed(v,places=2):
    if v is None:return 'N/A'
    try:
        d=Decimal(str(v))
        if not d.is_finite():return 'N/A'
        return ('+' if d>0 else '')+number(d,places)
    except (InvalidOperation,ValueError):return 'N/A'
def reason(row):
    if row.get('status')=='AFTER CUTOFF':return 'Quote after 07:45 cutoff'
    if row.get('status')=='STALE':return 'Quote older than four days'
    return str(row.get('reason') or 'No validated observation')[:42]
def render(s,r,path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    for font_path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/System/Library/Fonts/Supplemental/Georgia.ttf'):
        if Path(font_path).exists():
            font=TTFont('CashCurrency',font_path)
            if 0x20B9 in font.face.charToGlyph:
                pdfmetrics.registerFont(font);break
    else:raise ValueError('A font supporting the rupee symbol is required')
    c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('NSE Morning Brief | '+s['report_date'])
    def rect(x,top,w,h,fill,radius=0):
        c.setFillColor(HexColor(fill));c.setStrokeColor(HexColor(fill))
        c.roundRect(x,top-h,w,h,radius,fill=1,stroke=0)
    def p(value,x,top,w,size=9,color=INK,bold=False,maxh=None):
        style=ParagraphStyle('p',fontName='Helvetica-Bold' if bold else 'Helvetica',fontSize=size,leading=size*1.3,textColor=HexColor(color))
        value=value.replace('₹','<font name="CashCurrency">₹</font>')
        para=Paragraph(value,style);_,h=para.wrap(w,800)
        if maxh and h>maxh:
            # Never silently crop or shrink text to an unreadable size.
            raise ValueError('Report text exceeds its reserved layout; shorten the review')
        para.drawOn(c,x,top-h);return h
    def label(value,x,top,w=530):p(value.upper(),x,top,w,8,TEAL,True)
    def section(n,title,top):
        p(n+'  /  '+title.upper(),28,top,539,8,TEAL,True)
        c.setStrokeColor(HexColor(LINE));c.line(28,top-18,567,top-18)
    def base(page,title,kicker):
        rect(0,842,595,842,'#FFFFFF')
        p(title,35,805,485,25,'#111111',True)
        p('NSE MORNING BRIEF',454,802,107,8,INK,True)
        p(kicker,36,769,520,9,MUTED)
        c.setStrokeColor(HexColor(LINE));c.line(35,751,560,751)
        c.line(35,42,560,42)
        p('NSE MORNING BRIEF  |  SAVED SOURCE TIMES',35,31,405,7,MUTED)
        p(f'{page:02d} / 03',523,31,38,7,MUTED,True)
    day=dt.date.fromisoformat(s['report_date']).strftime('%d %B %Y')
    # A snapshot-style first page uses only observations present by the report cutoff.
    cutoff=dt.datetime.fromisoformat(s['cutoff_IST'])
    markets={row.get('name'):row for row in s.get('global',[])}
    def observed(name):
        row=markets.get(name,{})
        try:
            when=dt.datetime.fromisoformat(row['asof'])
            value=Decimal(str(row['value']))
            if (row.get('status') not in ('PASS','PROVISIONAL') or when.tzinfo is None
                    or when>cutoff or not value.is_finite() or value<=0):
                return None,row
            return row,row
        except (KeyError,TypeError,ValueError,InvalidOperation):
            return None,row
    def change_color(value):
        try:return '#139F53' if Decimal(str(value))>=0 else '#D52735'
        except (InvalidOperation,TypeError,ValueError):return MUTED
    def line(x,top,w):
        c.setStrokeColor(HexColor(LINE));c.line(x,top,x+w,top)
    rect(0,842,595,842,'#FFFFFF')
    p('Pre-Market Snapshot',35,805,485,25,'#111111',True)
    p('NSE MORNING BRIEF',454,802,107,8,INK,True)
    p(day+'  |  07:45 IST cutoff',36,769,470,9,MUTED)
    line(35,751,525)
    label('Prior close / previous session',35,733,235)
    label('Sectors',306,733,250)
    line(35,717,237);line(306,717,254)
    spot=s.get('spot',{})
    vd=s.get('vix_daily',{})
    close_rows=[('Nifty 50',spot.get('NIFTY',{})),('Sensex',spot.get('SENSEX',{})),
                ('Bank Nifty',spot.get('BANKNIFTY',{})),('Midcap 100',spot.get('MIDCAP100',{})),
                ('Smallcap 100',spot.get('SMALLCAP100',{})),('India VIX',vd)]
    def valid_close(name,row):
        exchange='BSE' if name=='Sensex' else 'NSE'
        return (row.get('status')=='PASS' and
                row.get('latest_date') in s.get('completed_sessions',{}).get(exchange,[])[:1])
    for i,(name,row) in enumerate(close_rows):
        y=703-i*22
        valid=valid_close(name,row)
        p(name,36,y,112,9,INK)
        p(number(row.get('close')) if valid else 'N/A',150,y,69,9,INK,True)
        change=row.get('change_pct') if valid else None
        p((signed(change)+'%') if change is not None else 'N/A',222,y,52,8,change_color(change))
    sector_names=('PSU Bank','Realty','Auto','FMCG','Energy','IT')
    sector_rows=s.get('sectors',{})
    def sector_change(row):
        try:
            change=Decimal(str(row['change_pct']))
            if (row.get('status')=='PASS' and change.is_finite() and
                    row.get('latest_date') in s.get('completed_sessions',{}).get('NSE',[])[:1]):
                return change
        except (KeyError,InvalidOperation,TypeError,ValueError):pass
        return None
    for i,name in enumerate(sector_names):
        y=703-i*22
        p(name,307,y,80,9,INK)
        rect(388,y-2,107,4,'#E8ECEC',2)
        row=sector_rows.get(name,{})
        change=sector_change(row)
        if change is not None:
            rect(388,y-2,float(min(abs(change),Decimal('2')))*51,4,change_color(change),2)
            p(signed(change)+'%',504,y,53,8,change_color(change))
        else:p('N/A',504,y,53,8,MUTED)
    p('Previous NSE close; bars capped at 2%.' if all(sector_change(sector_rows.get(n,{})) is not None for n in sector_names)
      else 'Missing sector rows: daily close not validated.',307,568,249,7,MUTED)
    line(35,552,525)
    label('Gift Nifty and opening indication',35,536)
    gift,_=observed('GIFT NIFTY')
    nifty=spot.get('NIFTY',{})
    gap=None
    if gift and nifty.get('status')=='PASS':
        try:
            prior=Decimal(str(nifty['close']))
            if prior>0:gap=Decimal(str(gift['value']))-prior
        except (KeyError,InvalidOperation,TypeError,ValueError):pass
    for i,(heading,value,detail) in enumerate((
        ('GIFT NIFTY',number(gift['value']) if gift else 'N/A',stamp(gift.get('asof')) if gift else reason(markets.get('GIFT NIFTY',{}))),
        ('GAP VS NIFTY CLOSE',signed(gap,0)+' pts' if gap is not None else 'N/A','Reference: prior NSE close'),
        ('OPENING INDICATION','Gap-up' if gap is not None and gap>0 else 'Gap-down' if gap is not None and gap<0 else 'Flat' if gap is not None else 'N/A','Indicative, not an opening price'),
        ('SIX-SIGNAL BIAS',text(s['score']['bias']).replace('_',' ').title(),f"Score {s['score']['score']:+d} | {s['score']['available']}/6 signals"))):
        x=35+i*132
        if i:
            c.setStrokeColor(HexColor(LINE));c.line(x-8,511,x-8,457)
        p(heading,x,510,122,6.5,MUTED,True)
        p(value,x,490,122,13 if i!=3 else 10,change_color(gap) if i==1 else INK,True,maxh=27)
        p(text(detail),x,463,122,6.5,MUTED,maxh=19)
    line(35,438,525)
    label('Global / US and Asia',35,421,245)
    label('ADRs vs NSE close',306,421,250)
    line(35,405,237);line(306,405,254)
    for i,(label_name,key) in enumerate((('Dow','DOW JONES'),('S&P 500','S&P'),
                                           ('US Tech 100','US Tech 100'),('Nikkei','NIKKEI 225'),
                                           ('Kospi','KOSPI'),('Hang Seng','HANG SENG'))):
        y=391-i*22;row,raw=observed(key)
        p(text(label_name),36,y,91,8.7,INK)
        p(number(row['value']) if row else 'N/A',127,y,88,8.7,INK,True)
        pct=row.get('change_pct') if row else None
        p(signed(pct)+'%' if pct is not None else 'N/A',218,y,56,8,change_color(pct))
    for i,name in enumerate(('Infosys','HDFC Bank','ICICI Bank','Wipro')):
        y=391-i*22;p(name,307,y,122,8.7,INK);p('N/A',507,y,52,8,MUTED)
    p('ADR comparison feed not connected',307,292,249,7,MUTED)
    line(35,256,525)
    label('Rates, commodities and currency',35,240)
    for i,(heading,key) in enumerate((('US 10Y',None),('BRENT','Oil (Brent)'),
                                      ('GOLD',None),('SILVER',None),('USD/INR','USD INR'))):
        x=35+i*105;row,_=observed(key) if key else (None,{})
        p(heading,x,219,99,7,MUTED,True)
        p(number(row['value']) if row else 'N/A',x,196,99,13,INK,True)
        pct=row.get('change_pct') if row else None
        p(signed(pct)+'%' if pct is not None else 'Change N/A',x,176,99,7,change_color(pct))
    line(35,145,525)
    missing_global=[name+': '+reason(markets.get(name,{})) for name in ('NIKKEI 225','GIFT NIFTY')
                    if observed(name)[0] is None and name in markets]
    missing_indices=[name for name,row in close_rows if not valid_close(name,row)]
    missing_sectors=[name for name in sector_names if sector_change(sector_rows.get(name,{})) is None]
    p('Index N/A: '+(', '.join(missing_indices) or 'none')+'.',35,132,525,7,MUTED,maxh=10)
    p('Sector N/A: '+(', '.join(missing_sectors) or 'none')+'.',35,120,525,7,MUTED,maxh=10)
    p('Other feeds not connected: ADRs, US yield, gold, silver and Kospi.',35,108,525,7,MUTED)
    p(text('; '.join(missing_global[:2])) if missing_global else 'Opening indication is not a forecast and does not alter the model score.',35,96,525,7,MUTED,maxh=18)
    line(35,42,525);p('NSE MORNING BRIEF  |  SAVED SOURCE TIMES',35,31,405,7,MUTED)
    p('01 / 03',523,31,38,7,MUTED,True)
    c.showPage()
    base(2,'Pre-Market Brief',day+'  |  07:45 IST cutoff  |  Selected data, explicit gaps')
    q=s['score'];rect(28,714,539,78,PAPER,8);label('Model bias',42,702)
    bias=q['bias'];headline='Insufficient data for final bias' if bias=='INSUFFICIENT DATA TO ASSIGN FINAL BIAS' else bias.title()
    p(text(headline),42,685,510,19,INK,True)
    p('Available signals are incomplete. Read the score together with its possible range.' if q['available']<6 else 'All six signals are available. The VIX caution remains a separate check.',42,654,505,8.5,MUTED)
    vd=s.get('vix_daily',{})
    v=s.get('vix',{})
    if vd.get('status')=='PASS':
        vix_note='D '+number(vd.get('close'))+' | change '+signed(vd.get('change_pct'))+'%'
    elif v.get('status')=='PASS':
        vix_note='Last '+number(v.get('last_price'))+' | change N/A'
    else:vix_note='N/A: '+reason(vd if vd else v)
    for i,(tag,value,note) in enumerate([
        ('RAW SCORE',str(q['score']),'Possible range ['+text(q['score_range'])+']'),
        ('COVERAGE',f'{q["available"]} / 6','Valid signals; missing is not zero'),
        ('VIX CAUTION',text(s.get('vix_flag','UNKNOWN')),vix_note)]):
        x=28+i*183;rect(x,624,173,79,PAPER,7);label(tag,x+12,613,149)
        color=TEAL if i==1 else change_color(q['score']) if i==0 else AMBER if s.get('vix_flag')=='CAUTION' else INK
        p(value,x+12,594,149,25 if i<2 else 16,color,True)
        p(note,x+12,560,150,7.5,MUTED)
    names=[('futures_build_up','Futures'),('pcr_direction','PCR'),('strike_walls','OI walls'),('fii_futures','FII futures'),('fii_cash','FII cash'),('dii_cash','DII cash')]
    label('Signal ledger',28,533)
    for i,(key,name) in enumerate(names):
        x=28+i*91;v=q['signals'][key]
        rect(x,518,84,39,PAPER if v is None or v==0 else '#E8F5EF' if v>0 else '#FCEDEE',5)
        p(name,x+7,511,72,8,INK,True)
        p('MISSING' if v is None else f'{v:+d}',x+7,497,72,7.5,MUTED if v is None else change_color(v))
    section('01','Why it matters today',465)
    flow_rows={row.get('check'):row for row in s.get('flows',[])}
    fii=flow_rows.get('FII cash',{});dii=flow_rows.get('DII cash',{})
    fii_obs=(fii.get('observations') or [{}])[0];dii_obs=(dii.get('observations') or [{}])[0]
    cash_fact=(f"{fii_obs.get('date')}: FII {signed(fii_obs.get('net_raw'))} / "
               f"DII {signed(dii_obs.get('net_raw'))} ₹ cr") if (
                   fii.get('status')=='PASS' and dii.get('status')=='PASS' and
                   fii_obs.get('date') and fii_obs.get('date')==dii_obs.get('date')) else 'FII/DII daily cash: N/A'
    option=s.get('options',{}).get('NIFTY',{})
    levels_fact=('Nifty put wall '+number(option.get('put_walls'),0)+'; call wall '+number(option.get('call_walls'),0)
                 if option.get('status') in ('PASS','PROVISIONAL') and option.get('put_walls') and option.get('call_walls')
                 else 'Nifty option levels: N/A / '+reason(option))
    opening_fact=('GIFT Nifty '+signed(gap,0)+' points versus previous Nifty close'
                  if gap is not None else 'GIFT Nifty opening indication: N/A / '+reason(markets.get('GIFT NIFTY',{})))
    for i,a in enumerate((opening_fact,cash_fact,levels_fact)):
        x=28+i*183;rect(x,437,173,82,PAPER,6);p(f'0{i+1}',x+10,427,25,11,AMBER,True)
        p(text(a),x+10,406,153,8.5,maxh=48)
    section('02','Opening picture',342)
    markets={row.get('name'):row for row in s.get('global',[])}
    nifty=s.get('spot',{}).get('NIFTY',{})
    gift=markets.get('GIFT NIFTY',{})
    try:
        if gift.get('status')!='PROVISIONAL' or not str(gift.get('asof','')).startswith(s['report_date']) or nifty.get('status')!='PASS':
            raise ValueError('No current pre-open indication')
        gap=Decimal(str(gift['value']))-Decimal(str(nifty['close']))
        gap_pct=gap*100/Decimal(str(nifty['close']))
        opening='GIFT Nifty vs Nifty close: '+signed(gap)+' points ('+signed(gap_pct)+'%)'
    except (KeyError,TypeError,ValueError,InvalidOperation,ZeroDivisionError):
        source=gift if gift.get('value') is None else nifty
        opening='GIFT Nifty vs Nifty close: N/A ('+reason(source)[:31]+')'
    p(opening,28,314,539,9,INK,True,maxh=13)
    def market_line(name):
        row=markets.get(name,{})
        return text(name)+' '+number(row.get('value'))+' ('+signed(row.get('change_pct'))+'%)'
    p('Global: '+market_line('DOW JONES')+' | '+market_line('S&P')+' | '+market_line('NIKKEI 225'),28,296,539,8,maxh=13)
    p('Forex & oil: '+market_line('USD INR')+' | '+market_line('Oil (Brent)'),28,280,539,8,maxh=13)
    opt=s.get('options',{}).get('NIFTY',{})
    try:
        spot_level=Decimal(str(nifty['close']))
        put_distance=signed(Decimal(str(opt['put_walls'][0]))-spot_level) if len(opt.get('put_walls',[]))==1 else 'N/A'
        call_distance=signed(Decimal(str(opt['call_walls'][0]))-spot_level) if len(opt.get('call_walls',[]))==1 else 'N/A'
    except (KeyError,TypeError,ValueError,InvalidOperation):put_distance=call_distance='N/A'
    try:countdown=str((dt.date.fromisoformat(opt['expiry'])-dt.date.fromisoformat(s['report_date'])).days)+'d'
    except (KeyError,TypeError,ValueError):countdown='N/A'
    p('Nifty walls vs spot: put '+put_distance+' | call '+call_distance+' pts | expiry in '+countdown,28,264,539,8,maxh=13)
    flows={row.get('check'):row for row in s.get('flows',[])}
    def daily(name):return ((flows.get(name,{}).get('observations') or [{}])[0].get('net_raw')
                            if flows.get(name,{}).get('status')=='PASS' else None)
    p('Previous session cash: FII '+signed(daily('FII cash'))+' / DII '+signed(daily('DII cash'))+' ₹ cr',28,248,539,8,maxh=13)
    section('03','Key news / last 12 hours',225)
    news=s.get('news',[])[:8]
    if news:
        p(text(s.get('news_note') or f'{len(news)} selected from the saved 12-hour window.'),28,207,539,6.3,MUTED,maxh=9)
    if not news:p('News N/A: '+text(s.get('news_note') or 'No relevant stories in the cutoff window.'),28,197,539,8,MUTED,maxh=20)
    for i,a in enumerate(news):
        x=28+(i%2)*275;top=197-(i//2)*40
        url=a.get('url') or '';parsed=urlsplit(url)
        raw_title=str(a.get('title') or 'N/A')
        title=text(raw_title[:102]+'...' if len(raw_title)>105 else raw_title)
        if parsed.scheme in ('https','http') and parsed.netloc:title=f'<link href="{escape(url,quote=True)}" color="{TEAL}">{title}</link>'
        outlet=a.get('source') or parsed.hostname or 'Source N/A'
        p(text(outlet)+' | '+stamp(a.get('published_IST')),x,top,261,6.5,MUTED,maxh=9)
        p(title,x,top-10,261,7,maxh=30)
    if len(news)<=2:
        rect(28,155,539,97,'#FFFFFF',6)
        label('Why some fields are missing',39,145)
        missing_markets=[a for a in s.get('global',[]) if a.get('value') is None]
        market_gap=(', '.join(str(a.get('name'))+': '+reason(a) for a in missing_markets[:2])
                    or 'No market quote withheld')
        p(text(market_gap),39,128,517,7.5,maxh=16)
        missing_changes=[a for a in s.get('global',[]) if a.get('value') is not None and a.get('change_pct') is None]
        change_gap='; '.join(str(a.get('name'))+': '+str(a.get('change_reason') or 'previous close unavailable')
                             for a in missing_changes[:2])
        p('Change % N/A: '+text(change_gap) if missing_changes
          else 'Global change percentages use saved previous closes where available.',39,108,517,7.5,maxh=16)
        p('News: '+text(s.get('news_note') or 'No validated relevant stories in the saved window.'),39,88,517,7.2,maxh=25)
    c.showPage();base(3,'The numbers behind the view.',day+'  |  Source observations  |  N/A means unavailable')
    section('04','Across markets',712)
    # A true table with aligned values and timestamps; no fabricated sparklines.
    for i,(name,x,w) in enumerate([('MARKET',38,150),('VALUE',198,100),('AS OF',311,140),('STATUS',466,90)]):label(name,x,683,w)
    rows=[]
    for name in ('NIFTY','BANKNIFTY'):
        spot=s.get('spot',{}).get(name,{})
        if spot.get('status')=='PASS':
            value=number(spot.get('close'))+' ('+signed(spot.get('change_pct'))+'%)'
            asof=text(spot.get('latest_date'))+' close'
        else:value='N/A';asof=reason(spot)
        rows.append({'name':name+' spot','display_value':value,'display_asof':asof,
                     'status':'D CLOSE' if spot.get('status')=='PASS' else 'UNAVAILABLE'})
    for a in s.get('global',[])[:9]:
        rows.append({'name':a['name'],'display_value':number(a.get('value')),
                     'display_asof':stamp(a.get('asof')) if a.get('value') is not None else reason(a),
                     'status':a.get('status','UNAVAILABLE')})
    for i,a in enumerate(rows):
        top=666-i*13
        if i%2==0:rect(28,top+2,539,13,PAPER)
        p(text(a['name']),38,top,152,7.6)
        p(a['display_value'],198,top,105,7.2,INK,True)
        p(a['display_asof'],311,top,146,7,MUTED)
        p(text(a['status']),466,top,93,6.7,TEAL if a['display_value']!='N/A' else MUTED)
    section('05','Options / provisional archive levels',510)
    for i,name in enumerate(('NIFTY','BANKNIFTY')):
        a=s.get('options',{}).get(name,{});x=28+i*275;rect(x,482,264,122,PAPER,7)
        p(name,x+12,471,130,12,INK,True);p('EXP '+text(a.get('expiry')),x+135,469,118,7.5,MUTED)
        p('PCR '+number(a.get('pcr_current'),3),x+12,449,118,14,TEAL,True)
        p('Max pain '+number(a.get('max_pain')),x+132,446,120,8.2,INK,True)
        p('Previous '+number(a.get('pcr_previous'),3)+' | direction '+text(a.get('pcr_direction') or 'N/A'),x+12,425,239,6.7,MUTED,maxh=18)
        p('Call wall '+number(a.get('call_walls'))+' | Put wall '+number(a.get('put_walls')),x+12,408,239,8,maxh=20)
        detail=('OI change / C '+number(a.get('call_oi_change'),0)+' | P '+number(a.get('put_oi_change'),0)
                if a.get('status')!='UNAVAILABLE' else 'N/A: '+reason(a))
        p(detail,x+12,386,239,7.2,MUTED,maxh=19)
    section('06','Positioning & flows',350)
    f=s.get('flows',[])
    for i,a in enumerate(f[:5]):
        top=322-i*22
        if i%2==0:rect(28,top+3,539,22,PAPER)
        p(text(a['check']),36,top,151,8,INK,True)
        obs=a.get('daily_observations',[]) if a['check'] in ('NIFTY futures','BANKNIFTY futures') else a.get('observations',[])
        v=obs[0] if obs else {}
        if a['check'] in ('NIFTY futures','BANKNIFTY futures'):
            current=obs[0] if len(obs)>0 else {};previous=obs[1] if len(obs)>1 else {}
            try:
                price_delta=Decimal(str(current['close']))-Decimal(str(previous['close']))
                oi_delta=int(current['oi_raw'])-int(previous['oi_raw'])
                detail='Close '+number(current['close'])+' ('+signed(price_delta)+') | OI '+number(current['oi_raw'],0)+' ('+signed(oi_delta,0)+')'
            except (KeyError,ValueError,TypeError,InvalidOperation):detail='Price / OI change N/A'
            sub='Raw provider OI | '+text(a.get('expiry'))+' expiry'
            status='OBSERVED' if len(obs)>1 else 'N/A'
        elif 'index-futures' in a['check']:
            detail='L '+number(v.get('long_contracts'),0)+' / S '+number(v.get('short_contracts'),0)+' / net '+signed(v.get('net_contracts'),0)+' / L:S '+number(v.get('long_divided_by_short'),3)
            sub='Previous net '+signed(obs[1].get('net_contracts'),0) if len(obs)>1 else 'Previous net N/A'
            status='OK' if a.get('status')=='PASS' else 'N/A'
        elif 'cash' in a['check']:
            detail='3D (₹ cr) '+signed(a.get('net_sum_last_3_raw'))+' / 5D (₹ cr) '+signed(a.get('net_sum_last_5_raw'))
            sub=' '.join(text(row.get('date','')[-5:])+':'+signed(row.get('net_raw')) for row in obs[:5]) or 'Daily values N/A'
            status='OK' if a.get('status')=='PASS' else 'N/A'
        else:detail='N/A';sub=text(a.get('reason'));status=a.get('status','N/A')
        p(text(status),190,top,53,6.8,MUTED)
        p(detail,247,top,312,7.1,maxh=10)
        p(sub if a.get('status')=='PASS' else reason(a),247,top-10,312,6.2,MUTED,maxh=9)
    if not f:p('N/A / Flow observations unavailable.',36,322,520,8.5,MUTED)
    section('07','On the calendar / selected events',200)
    for i,a in enumerate(s.get('calendar',[])[:4]):
        top=172-i*14;p(stamp(a.get('scheduled_IST')) if a.get('scheduled_IST') else text(a.get('date_IST')),28,top,140,7,MUTED)
        p(text(a.get('title')),171,top,396,8,maxh=14)
    if not s.get('calendar'):p('Calendar N/A: '+text(s.get('calendar_note') or 'No whitelisted release was validated.'),28,172,539,8,MUTED,maxh=19)
    rect(28,112,539,44,'#E0EEEA',6);label('Data notes',39,104)
    bank=s.get('options',{}).get('BANKNIFTY',{})
    note='Bank Nifty: '+text(bank.get('reason','No comparison restriction recorded'))
    p(note,39,90,517,7,maxh=20)
    india=s.get('today_india',[])
    india_text='; '.join(text(x.get('title'))[:55] for x in india[:2]) or 'N/A'
    if len(india)>2:india_text+='; +'+str(len(india)-2)+' more'
    p('Today in India, 09:15-15:30: '+india_text+'. Corporate dates: '+text(s.get('india_corporate_events') or 'N/A: official source unavailable')+'.',28,61,539,7,AMBER,maxh=18)
    c.save()


def render_status(day, message, path):
    """A clearly labelled PDF when a validated market report is unavailable."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setTitle('NSE Morning Report | ' + day + ' | Data unavailable')
    c.setFillColor(HexColor(PAPER)); c.rect(0, 0, 595, 842, fill=1, stroke=0)
    c.setFillColor(HexColor(NAVY)); c.rect(0, 700, 595, 142, fill=1, stroke=0)
    c.setFillColor(HexColor('#FFFFFF')); c.setFont('Helvetica-Bold', 21)
    c.drawString(35, 770, 'NSE Morning Report')
    c.setFont('Helvetica', 11); c.drawString(35, 739, day + ' | 07:45 IST cutoff')
    style = ParagraphStyle('status', fontName='Helvetica', fontSize=12, leading=20, textColor=HexColor(INK))
    top = 660
    for line in message.splitlines():
        paragraph = Paragraph(escape(line), style)
        _, height = paragraph.wrap(525, 500)
        if top - height < 80:
            raise ValueError('Status report exceeds one page')
        paragraph.drawOn(c, 35, top - height)
        top -= height + 14
    c.setFont('Helvetica', 9); c.setFillColor(HexColor(MUTED))
    c.drawString(35, 35, 'Data unavailable; no market direction is assigned.')
    c.save()
