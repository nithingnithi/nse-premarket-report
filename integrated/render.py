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
        rect(28,top,22,19,TEAL,4);p(n,32,top-3,16,9,'#FFFFFF',True)
        p(title,59,top-1,508,12,INK,True)
    def base(page,title,kicker):
        rect(0,842,595,842,PAPER);rect(0,842,595,113,NAVY)
        rect(28,815,4,49,'#36D2BA')
        p('NSE / MORNING BRIEF',43,815,440,10,'#76DCCD',True)
        p(title,42,795,500,27,'#FFFFFF',True)
        p(kicker,43,754,505,9,'#BDD1D9')
        c.setStrokeColor(HexColor(LINE));c.line(28,28,567,28)
        p('PARTIAL TRIAL  /  Evidence before conviction',28,20,440,7,MUTED)
        p(f'{page:02d} / 02',525,20,45,7,MUTED,True)
    day=dt.date.fromisoformat(s['report_date']).strftime('%d %B %Y')
    base(1,'The market, in perspective.',day+'  |  07:45 IST cutoff  |  Selected data, explicit gaps')
    q=s['score'];rect(28,714,539,78,'#FFFFFF',8);label('The call',42,702)
    bias=q['bias'];headline='Insufficient data for final bias' if bias=='INSUFFICIENT DATA TO ASSIGN FINAL BIAS' else bias.title()
    p(text(headline),42,685,510,19,INK,True)
    p('Available signals are incomplete. Read the score together with its possible range.' if q['available']<6 else 'All six signals are available. The VIX caution remains a separate check.',42,654,505,8.5,MUTED)
    vd=s.get('vix_daily',{})
    v=s.get('vix',{})
    if vd.get('status')=='PASS':
        vix_note='D '+number(vd.get('close'))+' | change '+signed(vd.get('change_pct'))+'%'
    elif v.get('status')=='PASS':
        vix_note='Last '+number(v.get('last_price'))+' | change N/A'
    else:vix_note='Level N/A | change N/A'
    for i,(tag,value,note) in enumerate([
        ('RAW SCORE',str(q['score']),'Possible range ['+text(q['score_range'])+']'),
        ('COVERAGE',f'{q["available"]} / 6','Valid signals; missing is not zero'),
        ('VIX CAUTION',text(s.get('vix_flag','UNKNOWN')),vix_note)]):
        x=28+i*183;rect(x,624,173,79,'#FFFFFF',7);label(tag,x+12,613,149)
        p(value,x+12,594,149,25 if i<2 else 16,TEAL if i==1 else INK,True)
        p(note,x+12,560,150,7.5,MUTED)
    names=[('futures_build_up','Futures'),('pcr_direction','PCR'),('strike_walls','OI walls'),('fii_futures','FII futures'),('fii_cash','FII cash'),('dii_cash','DII cash')]
    label('Signal ledger',28,533)
    for i,(key,name) in enumerate(names):
        x=28+i*91;v=q['signals'][key];rect(x,518,84,39,'#E6EEEE' if v is None else '#D6EEE8',5)
        p(name,x+7,511,72,8,INK,True);p('MISSING' if v is None else f'{v:+d}',x+7,497,72,7.5,MUTED if v is None else TEAL)
    section('01','Three things to know',465)
    for i,a in enumerate(r['alerts']):
        x=28+i*183;rect(x,437,173,82,'#FFFFFF',6);p(f'0{i+1}',x+10,427,25,11,AMBER,True)
        p(text(a),x+10,406,153,8.5,maxh=48)
    section('02','The read-through',342)
    p(text(r['summary']),28,314,539,9.3,maxh=119)
    section('03','News radar / last 12 hours',183)
    news=s.get('news',[])[:6]
    if not news:p('N/A / No eligible stories supplied.',28,155,539,9,MUTED)
    for i,a in enumerate(news):
        x=28+(i%2)*275;top=155-(i//2)*39
        url=a.get('url') or '';parsed=urlsplit(url)
        title=text(str(a.get('title') or 'N/A')[:160])
        if parsed.scheme in ('https','http') and parsed.netloc:title=f'<link href="{escape(url,quote=True)}" color="{TEAL}">{title}</link>'
        p(stamp(a.get('published_IST')),x,top,261,6.5,MUTED)
        p(title,x,top-10,261,8,maxh=27)
    p('Selected-query sample; linked headlines retain source wording. Syndicated duplicates may remain.',28,34,539,6.5,MUTED)
    c.showPage();base(2,'The numbers behind the view.',day+'  |  Source observations  |  N/A means unavailable')
    section('04','Across markets',712)
    # A true table with aligned values and timestamps; no fabricated sparklines.
    for i,(name,x,w) in enumerate([('MARKET',38,150),('VALUE',198,100),('AS OF',311,140),('STATUS',466,90)]):label(name,x,683,w)
    rows=[]
    for name in ('NIFTY','BANKNIFTY'):
        spot=s.get('spot',{}).get(name,{})
        if spot.get('status')=='PASS':
            value=number(spot.get('close'))+' ('+signed(spot.get('change_pct'))+'%)'
            asof=text(spot.get('latest_date'))+' close'
        else:value='N/A';asof='N/A'
        rows.append({'name':name+' spot','display_value':value,'display_asof':asof,
                     'status':'D CLOSE' if spot.get('status')=='PASS' else 'UNAVAILABLE'})
    for a in s.get('global',[])[:9]:
        rows.append({'name':a['name'],'display_value':number(a.get('value')),
                     'display_asof':stamp(a.get('asof')),'status':a.get('status','UNAVAILABLE')})
    for i,a in enumerate(rows):
        top=666-i*13
        if i%2==0:rect(28,top+2,539,13,'#FFFFFF')
        p(text(a['name']),38,top,152,7.6)
        p(a['display_value'],198,top,105,7.2,INK,True)
        p(a['display_asof'],311,top,146,7,MUTED)
        p(text(a['status']),466,top,93,6.7,TEAL if a['display_value']!='N/A' else MUTED)
    section('05','Options / provisional archive levels',510)
    for i,name in enumerate(('NIFTY','BANKNIFTY')):
        a=s.get('options',{}).get(name,{});x=28+i*275;rect(x,482,264,122,'#FFFFFF',7)
        p(name,x+12,471,130,12,INK,True);p('EXP '+text(a.get('expiry')),x+135,469,118,7.5,MUTED)
        p('PCR '+number(a.get('pcr_current'),3),x+12,449,118,14,TEAL,True)
        p('Max pain '+number(a.get('max_pain')),x+132,446,120,8.2,INK,True)
        p('Previous '+number(a.get('pcr_previous'),3)+' | '+text(a.get('pcr_direction') or 'WITHHELD')+' / shadow, not counted',x+12,425,239,6.7,MUTED,maxh=18)
        p('Call wall '+number(a.get('call_walls'))+' | Put wall '+number(a.get('put_walls')),x+12,408,239,8,maxh=20)
        p('OI change / C '+number(a.get('call_oi_change'),0)+' | P '+number(a.get('put_oi_change'),0),x+12,386,239,7.2,MUTED)
    section('06','Positioning & flows',350)
    f=s.get('flows',[])
    for i,a in enumerate(f[:5]):
        top=322-i*22
        if i%2==0:rect(28,top+3,539,22,'#FFFFFF')
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
            sub='Raw provider OI | '+text(a.get('expiry'))+' expiry | signal withheld'
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
        p(sub,247,top-10,312,6.2,MUTED,maxh=9)
    if not f:p('N/A / Flow observations unavailable.',36,322,520,8.5,MUTED)
    section('07','On the calendar / selected events',200)
    for i,a in enumerate(s.get('calendar',[])[:4]):
        top=172-i*14;p(stamp(a.get('scheduled_IST')) if a.get('scheduled_IST') else text(a.get('date_IST')),28,top,140,7,MUTED)
        p(text(a.get('title')),171,top,396,8,maxh=14)
    if not s.get('calendar'):p('N/A / Calendar coverage unavailable.',28,172,539,8.5,MUTED)
    rect(28,112,539,44,'#E0EEEA',6);label('Data notes',39,104)
    bank=s.get('options',{}).get('BANKNIFTY',{})
    note='Bank Nifty: '+text(bank.get('reason','No comparison restriction recorded'))
    p(note,39,90,517,7,maxh=20)
    p('OI units unverified. PCR/walls and futures remain outside the six-signal score.',28,61,539,7,AMBER)
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
