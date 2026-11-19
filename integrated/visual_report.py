"""Three-page visual report from the validated integration snapshot.

This module formats observations only. The collector owns validation and scoring.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from integrated.render import number, reason, signed, stamp, text

W, H, M = 595, 842, 28
NAVY = '#102039'
INK = '#1D2E43'
MUTED = '#65768B'
BG = '#F4F7FB'
LINE = '#DDE5EE'
GREEN = '#16966B'
RED = '#C94958'
AMBER = '#A86B0F'
BLUE = '#2E74B9'


def dec(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def color(value):
    n = dec(value)
    return GREEN if n is not None and n > 0 else RED if n is not None and n < 0 else MUTED


def label_reason(row):
    if not isinstance(row, dict):
        return 'No validated observation'
    if row.get('status') == 'AFTER CUTOFF':
        return 'Quote after 07:45 cutoff'
    if row.get('status') == 'STALE':
        return 'Quote is stale'
    return str(row.get('reason') or row.get('change_reason') or 'No validated observation')


def valid_daily(row, sessions):
    return (isinstance(row, dict) and row.get('status') == 'PASS'
            and bool(sessions) and row.get('latest_date') == sessions[0]
            and dec(row.get('close')) is not None)


def valid_sector(row, sessions):
    return (isinstance(row, dict) and row.get('status') == 'PASS'
            and bool(sessions) and row.get('latest_date') == sessions[0]
            and dec(row.get('change_pct')) is not None)


def valid_market(row, cutoff):
    if not isinstance(row, dict) or row.get('status') not in ('PASS', 'PROVISIONAL'):
        return False
    value = dec(row.get('value'))
    try:
        when = dt.datetime.fromisoformat(row['asof'])
        return value is not None and value > 0 and when.tzinfo is not None and when <= cutoff
    except (KeyError, ValueError, TypeError):
        return False


class Sheet:
    def __init__(self, path, report_date, cutoff, synthetic):
        self.c = canvas.Canvas(str(path), pagesize=(W, H), pageCompression=1)
        self.c.setTitle('NSE Morning Report | ' + report_date)
        self.date, self.cutoff, self.synthetic = report_date, cutoff, synthetic
        self.font = 'Helvetica'
        for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                          '/System/Library/Fonts/Supplemental/Georgia.ttf'):
            if Path(candidate).exists():
                font = TTFont('VisualUnicode', candidate)
                if 0x20B9 in font.face.charToGlyph:
                    pdfmetrics.registerFont(font)
                    self.font = 'VisualUnicode'
                    break

    def box(self, x, top, width, height, fill='#FFFFFF', radius=8, border=False):
        c = self.c
        c.setFillColor(HexColor(fill))
        c.setStrokeColor(HexColor(LINE if border else fill))
        c.setLineWidth(.7)
        c.roundRect(x, H-top-height, width, height, radius, fill=1, stroke=int(border))

    def line(self, x1, top1, x2, top2):
        self.c.setStrokeColor(HexColor(LINE))
        self.c.setLineWidth(.7)
        self.c.line(x1, H-top1, x2, H-top2)

    def write(self, value, x, top, width, size=8, ink=INK, bold=False,
              max_lines=1, url=None):
        raw = 'N/A' if value is None or value == '' else str(value)
        face = 'Helvetica-Bold' if bold else self.font
        style = ParagraphStyle('visual', fontName=face, fontSize=size,
                               leading=size*1.22, textColor=HexColor(ink))
        # Shrink only to fit the reserved block; never replace missing data with zero.
        html = (escape(raw).replace('₹', '<font name="VisualUnicode">₹</font>')
                if self.font == 'VisualUnicode' else escape(raw.replace('₹', 'INR ')))
        para = Paragraph(html, style)
        _, height = para.wrap(width, 100)
        if height > max_lines*size*1.22:
            style.fontSize = max(6.2, size-1)
            style.leading = style.fontSize*1.2
            para = Paragraph(html, style)
            _, height = para.wrap(width, 100)
        if height > max_lines*style.leading + .2:
            # A layout overflow is explicit; headline text is never silently cut.
            raise ValueError('Visual report text exceeds its card: ' + raw[:80])
        para.drawOn(self.c, x, H-top-height)
        if url:
            parsed = urlsplit(str(url))
            if parsed.scheme in ('http', 'https') and parsed.netloc:
                self.c.linkURL(str(url), (x, H-top-height, x+width, H-top), relative=0)
        return height

    def section(self, title, top, subtitle=''):
        self.write(title.upper(), M, top, 285, 9.2, INK, True)
        if subtitle:
            self.write(subtitle, 315, top+1, W-M-315, 6.8, MUTED, max_lines=2)

    def page(self, n, title, subtitle):
        c = self.c
        c.setFillColor(HexColor(BG)); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(HexColor(NAVY)); c.rect(0, H-98, W, 98, fill=1, stroke=0)
        c.setFillColor(HexColor(BLUE)); c.rect(0, H-5, W, 5, fill=1, stroke=0)
        self.write('NSE / MORNING INTELLIGENCE', M, 18, 365, 8, '#9DD9EE', True)
        self.write(title, M, 35, 485, 22, '#FFFFFF', True)
        self.write(subtitle, M, 70, 480, 8, '#D4E1ED')
        self.box(W-89, 20, 61, 21, '#EAF2FC', 11)
        self.write(f'{n:02d} / 03', W-76, 25, 50, 8, BLUE, True)
        self.box(M, 105, W-2*M, 25, '#FFF4DB', 6)
        banner = ('SYNTHETIC FIXTURE / NOT LIVE MARKET DATA' if self.synthetic else
                  '07:45 IST CUTOFF / MISSING VALUES SHOWN AS N/A WITH REASONS')
        self.write(banner, M+10, 111, W-2*M-20, 7.5, AMBER, True)
        self.line(M, 803, W-M, 803)
        self.write('Source observations as saved at cutoff  |  N/A means withheld', M, 811, 430, 7, MUTED)
        self.write(f'{n:02d} / 03', W-62, 811, 40, 7, MUTED, True)


def render_visual(s, review, path):
    """Render the existing six-signal snapshot; do not recalculate its score."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cutoff = dt.datetime.fromisoformat(s['cutoff_IST'])
    if cutoff.tzinfo is None:
        raise ValueError('Report cutoff must be timezone aware')
    q = s['score']
    if q.get('total') != 6 or len(q.get('signals', {})) != 6:
        raise ValueError('Expected the existing six-signal score')
    synthetic = any('SYNTHETIC' in str(x).upper() for x in s.get('limitations', []))
    v = Sheet(path, s['report_date'], cutoff, synthetic)
    nse = s.get('completed_sessions', {}).get('NSE', [])
    bse = s.get('completed_sessions', {}).get('BSE', [])
    nfo = s.get('completed_sessions', {}).get('NFO', [])
    spot = s.get('spot', {})
    markets = {x.get('name'): x for x in s.get('global', []) if isinstance(x, dict)}
    sectors = s.get('sectors', {})
    extra = s.get('extra_data', {})
    flows = {x.get('check'): x for x in s.get('flows', []) if isinstance(x, dict)}
    options = s.get('options', {})

    def market(name):
        row = markets.get(name, {})
        return row if valid_market(row, cutoff) else None

    def daily(name):
        row = s.get('vix_daily', {}) if name == 'India VIX' else spot.get(name, {})
        return row if valid_daily(row, bse if name == 'SENSEX' else nse) else None

    def na(row):
        return 'N/A: ' + label_reason(row)

    def card_value(value, x, top, width, size=18, ink=INK):
        v.write(value, x, top, width, size, ink, True, 2)

    day = dt.date.fromisoformat(s['report_date']).strftime('%a, %d %b %Y')
    d = nse[0] if nse else 'N/A'
    prior = nse[1] if len(nse) > 1 else 'N/A'

    # PAGE 1: opening dashboard
    v.page(1, 'Opening dashboard', f'{day}  |  NSE D: {d}  |  D-1: {prior}  |  07:45 IST')
    v.box(M, 140, 224, 105, NAVY, 10)
    v.write('SIX-SIGNAL MODEL', M+14, 151, 196, 8, '#B2C4D8', True)
    bias = str(q['bias']).replace('_', ' ').upper()
    if bias == 'INSUFFICIENT DATA TO ASSIGN FINAL BIAS':
        bias = 'INSUFFICIENT DATA'
    card_value(bias, M+14, 174, 200, 18 if len(bias)>14 else 25,
               AMBER if q['available']<6 else GREEN if q['score']>=3 else RED if q['score']<=-3 else '#FFFFFF')
    v.write(f"SCORE {q['score']:+d}  /  {q['available']}/6 valid", M+14, 211, 199, 10, '#FFFFFF', True)
    if q['available'] < 6:
        v.write('Possible score ' + str(q.get('score_range', 'N/A')) + ' | provisional', M+14, 229, 199, 7, '#CAD8E7')
    else:
        v.write('VIX is a separate caution flag', M+14, 229, 199, 7, '#CAD8E7')
    gift = market('GIFT NIFTY')
    nifty = daily('NIFTY')
    gap = dec(gift['value'])-dec(nifty['close']) if gift and nifty else None
    gap_pct = gap*100/dec(nifty['close']) if gap is not None and dec(nifty['close']) else None
    v.box(260, 140, 153, 105, border=True)
    v.write('GIFT NIFTY / CUTOFF', 272, 153, 130, 7.5, MUTED, True)
    card_value(number(gift['value']) if gift else 'N/A', 272, 174, 130, 21)
    v.write((signed(gap, 0)+' pts ('+signed(gap_pct)+'%)') if gap is not None else na(markets.get('GIFT NIFTY', {})),
            272, 211, 130, 8, color(gap) if gap is not None else AMBER, True, 2)
    v.write(stamp(gift.get('asof')) if gift else 'vs prior Nifty close', 272, 231, 130, 6.7, MUTED)
    vv = daily('India VIX')
    v.box(421, 140, 146, 105, border=True)
    v.write('INDIA VIX / D', 433, 153, 122, 7.5, MUTED, True)
    card_value(number(vv.get('close')) if vv else 'N/A', 433, 174, 122, 21)
    v.write((signed(vv.get('change_pct'))+'% vs D-1') if vv else na(s.get('vix_daily', {})),
            433, 211, 122, 8, color(vv.get('change_pct')) if vv else AMBER, True, 2)
    v.write('Caution: '+str(s.get('vix_flag', 'UNKNOWN')), 433, 231, 122, 6.7, AMBER)

    v.section('Model inputs', 253, 'Each signal = -1, 0 or +1')
    v.box(M, 272, W-2*M, 62, border=True)
    names = [('futures_build_up','FUTURES'),('pcr_direction','PCR'),('strike_walls','OI WALLS'),
             ('fii_futures','FII FUTURES'),('fii_cash','FII CASH'),('dii_cash','DII CASH')]
    cw = (W-2*M)/6
    for i,(key,name) in enumerate(names):
        x = M+i*cw
        if i: v.line(x, 280, x, 326)
        v.write(name, x+5, 283, cw-10, 7, MUTED, True)
        value = q['signals'].get(key)
        v.write(f'{value:+d}' if type(value) is int else 'N/A', x+5, 298, cw-10, 17,
                color(value) if value is not None else AMBER, True)
        v.write('valid' if value is not None else 'missing', x+5, 319, cw-10, 6.5, MUTED)

    v.section('Previous NSE close', 342, 'D close, not today’s opening price')
    v.box(M, 360, 260, 204, border=True)
    for i,(name,key) in enumerate((('Nifty 50','NIFTY'),('Sensex','SENSEX'),('Bank Nifty','BANKNIFTY'),
                                    ('Midcap 100','MIDCAP100'),('Smallcap 100','SMALLCAP100'))):
        row = daily(key)
        y = 370+i*37
        v.write(name.upper(), M+12, y, 120, 7.4, MUTED, True)
        v.write(number(row.get('close')) if row else 'N/A', M+12, y+13, 151, 13, INK, True)
        v.write(signed(row.get('change_pct'))+'%' if row and row.get('change_pct') is not None else 'N/A',
                M+184, y+15, 65, 9, color(row.get('change_pct')) if row else AMBER, True)
        if i<4: v.line(M+10, y+34, M+250, y+34)
    v.box(298, 360, 269, 204, border=True)
    breadth = s.get('breadth', {})
    adv, decline = dec(breadth.get('advances')), dec(breadth.get('declines'))
    v.write('BREADTH / NSE', 310, 371, 240, 8, MUTED, True)
    if adv is not None and decline is not None and adv+decline>0:
        v.write(number(adv,0)+' advancing', 310, 390, 125, 10, GREEN, True)
        v.write(number(decline,0)+' declining', 440, 390, 110, 10, RED, True)
        v.box(310, 415, 245, 12, '#EDF2F7', 6)
        v.box(310, 415, 245*float(adv/(adv+decline)), 12, GREEN, 6)
    else:
        v.write('N/A: '+(label_reason(breadth) if breadth else 'Previous-session breadth not collected'),
                310, 390, 245, 7.5, AMBER, max_lines=2)
    v.write('SECTOR MOMENTUM / D', 310, 447, 240, 8, MUTED, True)
    for i,name in enumerate(('PSU Bank','Realty','Auto','FMCG','Energy','IT')):
        row=sectors.get(name,{})
        change=dec(row.get('change_pct')) if valid_sector(row,nse) else None
        y=465+i*15
        v.write(name,310,y,82,7.5,MUTED)
        v.box(405,y+2,87,5,'#EDF2F7',2)
        if change is not None:
            v.box(405,y+2,min(87,abs(float(change))*35),5,color(change),2)
        v.write(signed(change)+'%' if change is not None else 'N/A',500,y,55,7.5,
                color(change) if change is not None else AMBER,True)

    v.section('Global markets & cross-assets', 573,
              'Mixed sessions; metals are USD/troy oz and may be live')
    v.box(M, 592, 264, 111, border=True)
    v.write('OVERSEAS INDICES',M+11,602,240,7.6,MUTED,True)
    global_names=(('DOW','DOW JONES'),('S&P 500','S&P'),('US TECH','US Tech 100'),
                  ('NIKKEI','NIKKEI 225'),('HANG SENG','HANG SENG'),('KOSPI','KOSPI'))
    for i,(label,key) in enumerate(global_names):
        x=M+11+(i//3)*129;y=617+(i%3)*27
        row=market(key)
        v.write(label,x,y,120,6.9,MUTED,True)
        v.write(number(row.get('value')) if row else 'N/A',x,y+10,67,8,INK if row else AMBER,True)
        v.write((signed(row.get('change_pct'))+'%') if row and row.get('change_pct') is not None else 'N/A',
                x+69,y+10,54,7.4,color(row.get('change_pct')) if row else AMBER,True)
    v.box(302,592,265,111,border=True)
    v.write('MACRO / FX / COMMODITIES',313,602,240,7.6,MUTED,True)
    macro=[('US 10Y',extra.get('us_10y',{}),'%'),('BRENT',market('Oil (Brent)'),'USD'),
           ('WTI',market('Oil (WTI)'),'USD'),('USD/INR',market('USD INR'),'INR'),
           ('GOLD',extra.get('metals',{}).get('GOLD',{}),'USD/oz'),
           ('SILVER',extra.get('metals',{}).get('SILVER',{}),'USD/oz')]
    for i,(label,row,unit) in enumerate(macro):
        x=313+(i//3)*126;y=623+(i%3)*22
        raw=row.get('value') if row else None
        amount=dec(raw)
        valid=(amount is not None and amount>0 and row.get('status') in ('PASS','PROVISIONAL')) if row else False
        if label in ('GOLD','SILVER') and row:
            valid=valid and row.get('unit')=='USD per troy oz'
            try:
                observed=dt.datetime.fromisoformat(row['asof_IST'])
                valid=valid and observed.tzinfo is not None
            except (KeyError,ValueError,TypeError):
                valid=False
        if label=='US 10Y' and row:
            valid=valid and row.get('unit')=='%'
        v.write(label,x,y,55,6.8,MUTED,True)
        displayed=(('$' if label in ('GOLD','SILVER') else '')+number(raw)+('%' if unit=='%' else '')) if valid else 'N/A'
        v.write(displayed,x+58,y,61,7.6,INK if valid else AMBER,True)
    v.section('US-listed ADRs',714,'US EOD; no implied NSE premium')
    v.box(M,732,W-2*M,63,border=True)
    for i,name in enumerate(('Infosys','Wipro','ICICI Bank','HDFC Bank')):
        x=M+i*(W-2*M)/4
        if i:v.line(x,740,x,783)
        row=extra.get('adrs',{}).get(name,{})
        valid=row.get('status')=='PROVISIONAL' and row.get('unit')=='USD per ADR'
        v.write(name.upper(),x+9,743,115,7.2,MUTED,True)
        v.write(signed(row.get('change_pct'))+'%' if valid and row.get('change_pct') is not None else 'N/A',
                x+9,759,115,13,color(row.get('change_pct')) if valid else AMBER,True)
        adr_time=(('As of '+stamp(row.get('asof_IST'))) if row.get('asof_IST') else
                  (str(row.get('date') or 'Date N/A')+' EOD; time N/A'))
        v.write(adr_time if valid else label_reason(row),
                x+9,779,115,6.2,MUTED if valid else AMBER,max_lines=2)
    v.c.showPage()

    # PAGE 2: flows, options, reference levels
    v.page(2,'Flows, options & levels','Institutional participation  |  Futures structure  |  Expiry-specific OI')
    v.section('Institutional flows',140,'₹ cr for cash; futures in contracts')
    card_width=(W-2*M-16)/3
    for i,(name,key) in enumerate((('FII CASH','FII cash'),('DII CASH','DII cash'),
                                    ('FII INDEX FUTURES','FII index-futures positions'))):
        row=flows.get(key,{})
        obs=row.get('observations') or []
        first=obs[0] if obs else {}
        value=first.get('net_contracts') if i==2 else first.get('net_raw')
        valid=row.get('status')=='PASS' and dec(value) is not None
        x=M+i*(card_width+8)
        v.box(x,159,card_width,118,border=True)
        v.write(name,x+11,172,card_width-22,7.8,MUTED,True)
        card_value(signed(value,0) if valid else 'N/A',x+11,195,card_width-22,19,color(value) if valid else AMBER)
        if valid and i<2:
            v.write('3D '+signed(row.get('net_sum_last_3_raw'),0)+' | 5D '+signed(row.get('net_sum_last_5_raw'),0),
                    x+11,232,card_width-22,7.5,MUTED)
            days='  '.join(str(z.get('date',''))[-5:]+':'+signed(z.get('net_raw'),0) for z in obs[:5])
            v.write(days or 'Daily values N/A',x+11,249,card_width-22,6.4,MUTED,max_lines=2)
        elif valid:
            v.write('L:S '+number(first.get('long_divided_by_short'),3),x+11,232,card_width-22,7.5,MUTED)
            v.write('Prior net '+signed(obs[1].get('net_contracts'),0) if len(obs)>1 else 'Prior net N/A',
                    x+11,249,card_width-22,6.8,MUTED)
        else:v.write(label_reason(row),x+11,231,card_width-22,7,AMBER,max_lines=3)
    fi=flows.get('FII index-futures positions',{})
    fi_obs=fi.get('observations') or []
    v.box(M,286,W-2*M,48,border=True)
    v.write('FII INDEX-FUTURES POSITIONING',M+12,294,250,7.7,MUTED,True)
    first=fi_obs[0] if fi.get('status')=='PASS' and fi_obs else {}
    long,short=dec(first.get('long_contracts')),dec(first.get('short_contracts'))
    if long is not None and short is not None and long+short>0:
        v.write('LONG '+number(long,0)+' / SHORT '+number(short,0),M+12,310,247,8.1,INK,True)
        v.box(291,310,259,13,'#FDEDF0',6)
        v.box(291,310,259*float(long/(long+short)),13,GREEN,6)
    else:v.write('N/A: '+label_reason(fi),M+12,311,517,8,AMBER)

    v.section('Futures price + open interest',342,'Same contract on D and D-1')
    def future_info(row):
        obs=row.get('daily_observations') or []
        if (row.get('status')!='PASS' or not row.get('instrument_key') or
                not row.get('expiry') or len(obs)<2 or len(nfo)<2 or
                obs[0].get('date')!=nfo[0] or obs[1].get('date')!=nfo[1]):
            return None,None,'N/A',str(row.get('reason') or 'Same-contract D/D-1 evidence missing')
        a,b=obs[:2]
        p1,p0,o1,o0=map(dec,(a.get('close'),b.get('close'),a.get('oi_raw'),b.get('oi_raw')))
        if None in (p1,p0,o1,o0) or p0<=0 or o0<=0 or p1<=0 or o1<0:
            return None,None,'N/A','Invalid or missing same-contract price/OI'
        dp,do=p1-p0,o1-o0
        kind={ (1,1):'LONG BUILD',(-1,1):'SHORT BUILD',(1,-1):'SHORT COVERING',(-1,-1):'LONG UNWINDING'}.get(
            ((dp>0)-(dp<0),(do>0)-(do<0)),'N/A')
        return dp*100/p0,do*100/o0,kind,('Unchanged price or OI; build-up withheld' if kind=='N/A' else '')
    for i,(name,key) in enumerate((('NIFTY','NIFTY futures'),('BANK NIFTY','BANKNIFTY futures'))):
        row=flows.get(key,{})
        dp,do,kind,why=future_info(row)
        x=M+i*274.5
        v.box(x,360,264.5,111,border=True)
        v.write(name+' FUTURES',x+12,371,157,9,INK,True)
        v.write(kind,x+159,373,94,7,AMBER if kind=='N/A' else color(dp),True)
        v.write('PRICE CHANGE',x+12,394,114,7.3,MUTED,True)
        v.write('OI CHANGE',x+138,394,114,7.3,MUTED,True)
        v.write(signed(dp)+'%' if dp is not None else 'N/A',x+12,408,114,15,color(dp) if dp is not None else AMBER,True)
        v.write(signed(do)+'%' if do is not None else 'N/A',x+138,408,114,15,color(do) if do is not None else AMBER,True)
        v.line(x+12,438,x+252,438)
        obs=row.get('daily_observations') or []
        cur=obs[0] if obs else {}
        v.write(('Close '+number(cur.get('close'))+' | OI '+number(cur.get('oi_raw'),0)) if dp is not None and kind!='N/A' else why,
                x+12,445,240,7.3,MUTED if dp is not None else AMBER,max_lines=2)
        v.write('Expiry '+str(row.get('expiry') or 'N/A')+' | raw provider OI',x+12,459,240,6.6,MUTED)

    v.section('Option chain / expiry-specific',478,'No mixed expiry or invalid-chain calculations')
    for i,name in enumerate(('NIFTY','BANKNIFTY')):
        row=options.get(name,{})
        usable=row.get('status') in ('PASS','PROVISIONAL','PARTIAL')
        comparable=row.get('status') in ('PASS','PROVISIONAL')
        x=M+i*274.5
        v.box(x,498,264.5,148,border=True)
        v.write(name,x+12,509,130,9.5,INK,True)
        v.write('EXP '+str(row.get('expiry') or 'N/A'),x+145,511,108,7,MUTED,True)
        metrics=[('PCR',number(row.get('pcr_current'),3) if usable else 'N/A'),
                 ('PREVIOUS PCR',number(row.get('pcr_previous'),3) if comparable else 'N/A'),
                 ('CALL OI WALL',number(row.get('call_walls'),0) if usable else 'N/A'),
                 ('PUT OI WALL',number(row.get('put_walls'),0) if usable else 'N/A'),
                 ('MAX PAIN',number(row.get('max_pain'),0) if usable else 'N/A'),
                 ('CALL / PUT OI CHANGE',(number(row.get('call_oi_change'),0)+' / '+number(row.get('put_oi_change'),0)) if comparable else 'N/A')]
        for j,(label,value) in enumerate(metrics):
            y=530+j*16
            v.write(label,x+12,y,133,7.1,MUTED)
            v.write(value,x+149,y,103,7.6,AMBER if 'N/A' in value else INK,True)
        if row.get('status') not in ('PASS','PROVISIONAL'):
            prefix='Current levels only; ' if row.get('status')=='PARTIAL' else 'Reason: '
            v.write(prefix+label_reason(row),x+12,631,240,6.5,AMBER,max_lines=2)
    v.section('Index reference levels',655,'OI walls and distance from D close; no price forecast')
    v.box(M,674,W-2*M,117,border=True)
    for i,(name,key) in enumerate((('NIFTY 50','NIFTY'),('BANK NIFTY','BANKNIFTY'))):
        x=M+10+i*266
        if i:v.line(x-8,683,x-8,781)
        row=options.get(key,{})
        cash=daily(key)
        v.write(name,x,685,245,8.5,INK,True)
        for j,(label,field) in enumerate((('PUT WALL','put_walls'),('CALL WALL','call_walls'),('MAX PAIN','max_pain'))):
            levels=(row.get(field) or []) if row.get('status') in ('PASS','PROVISIONAL','PARTIAL') else []
            one=levels[0] if isinstance(levels,list) and len(levels)==1 else None
            level=dec(one)
            distance=level-dec(cash['close']) if level is not None and cash else None
            v.write(label,x,704+j*23,80,7,MUTED,True)
            v.write(number(level,0)+' ('+signed(distance,0)+' pts)' if level is not None else 'N/A',
                    x+83,704+j*23,160,7.5,GREEN if j==0 else RED if j==1 else INK,True)
        if row.get('status') not in ('PASS','PROVISIONAL'):
            v.write(label_reason(row),x,774,243,6.2,AMBER,max_lines=2)
    v.c.showPage()

    # PAGE 3: dated news, events and explicit gaps
    v.page(3,'News, events & data quality','Recent headlines  |  IST calendar  |  Missing-field explanations')
    news=s.get('news',[])[:8]
    v.section('Market-moving news',140,s.get('news_note') or f'{len(news)} shown from saved window')
    for i in range(max(1,len(news))):
        x=M+(i%2)*274.5;y=159+(i//2)*78
        v.box(x,y,264.5,72,border=True)
        if i>=len(news):
            v.write('N/A',x+11,y+11,240,9,AMBER,True)
            if i==len(news):v.write(s.get('news_note') or 'No further validated stories in window',x+11,y+29,240,7,MUTED,max_lines=3)
            continue
        story=news[i]
        source=story.get('source') or urlsplit(story.get('url') or '').hostname or 'Source N/A'
        v.write(str(source)+' / '+stamp(story.get('published_IST')),x+11,y+10,240,6.7,BLUE,True,max_lines=2)
        v.write(story.get('title') or 'N/A: headline missing',x+11,y+25,240,8,INK,True,max_lines=3,url=story.get('url'))
    v.section('Catalyst calendar / IST',472,'Only saved and dated events')
    v.box(M,490,W-2*M,93,border=True)
    calendar=s.get('calendar',[])[:4]
    india=s.get('today_india',[])[:2]
    events=(calendar+india)[:6]
    for i in range(6):
        x=M+12+(i//3)*266;y=497+(i%3)*28
        if i and i%3:v.line(x,y-5,x+246,y-5)
        if i>=len(events):
            if i==len(events):v.write('N/A: '+str(s.get('calendar_note') or 'No further validated events'),x,y,245,7,AMBER,max_lines=3)
            continue
        item=events[i]
        v.write(item.get('title') or 'N/A',x,y,245,8,INK,True,max_lines=2,url=item.get('url'))
        v.write(stamp(item.get('scheduled_IST')) if item.get('scheduled_IST') else str(item.get('date_IST') or 'Time N/A'),
                x,y+16,245,7,BLUE)
    v.section('N/A / source watchlist',590,'Important unavailable fields and exact reasons')
    gaps=[]
    for name in ('GIFT NIFTY','USD INR','Oil (Brent)','NIKKEI 225','HANG SENG','KOSPI'):
        if market(name) is None:
            gaps.append((name,label_reason(markets[name]) if name in markets else 'No configured provider observation'))
    for name in ('GOLD','SILVER'):
        row=extra.get('metals',{}).get(name,{})
        if row.get('status') not in ('PASS','PROVISIONAL'):
            gaps.append((name,label_reason(row)))
    for name,key in (('NIFTY OPTIONS','NIFTY'),('BANK NIFTY OPTIONS','BANKNIFTY')):
        row=options.get(key,{})
        if row.get('status')=='PARTIAL':
            gaps.append((name.replace('OPTIONS','COMPARISON'),label_reason(row)))
        elif row.get('status') not in ('PASS','PROVISIONAL'):
            gaps.append((name,label_reason(row)))
    for name in ('FII cash','DII cash','FII index-futures positions'):
        row=flows.get(name,{})
        if row.get('status')!='PASS':gaps.append((name.upper(),label_reason(row)))
    for name in ('Infosys','Wipro','ICICI Bank','HDFC Bank'):
        row=extra.get('adrs',{}).get(name,{})
        if row.get('status') not in ('PASS','PROVISIONAL'):
            gaps.append((name.upper()+' ADR',label_reason(row)))
    corporate=s.get('india_corporate_events')
    if not corporate or str(corporate).startswith('N/A'):
        gaps.append(('CORPORATE EVENTS',str(corporate or 'No validated official source')))
    v.box(M,609,W-2*M,133,border=True)
    for i,(name,why) in enumerate(gaps[:8]):
        x=M+10+(i//4)*266;y=618+(i%4)*30
        v.write(name+' — N/A',x,y,245,7.3,AMBER,True,max_lines=1)
        v.write(why,x,y+11,245,6.3,MUTED,max_lines=2)
    if not gaps:v.write('No monitored gaps in this saved snapshot.',M+12,636,500,9,GREEN)
    v.box(M,750,W-2*M,42,NAVY,8)
    v.write('VALIDITY: saved source time + status + reason; missing never becomes zero.',M+11,759,517,7.4,'#FFFFFF',True)
    clocks=[]
    for label,key in (('Dow','DOW JONES'),('Nikkei','NIKKEI 225'),
                      ('Brent','Oil (Brent)'),('USD/INR','USD INR')):
        row=market(key)
        if row:
            try:clocks.append(label+' '+dt.datetime.fromisoformat(row['asof']).strftime('%d %b %H:%M'))
            except (KeyError,ValueError,TypeError):pass
    if extra.get('us_10y',{}).get('status')=='PROVISIONAL':
        clocks.append('US10Y '+str(extra['us_10y'].get('date') or 'date N/A')+' EOD')
    for label in ('GOLD','SILVER'):
        row=extra.get('metals',{}).get(label,{})
        if row.get('status')=='PROVISIONAL':
            try:
                observed=dt.datetime.fromisoformat(row['asof_IST'])
                clocks.append(label+(' LIVE ' if observed>cutoff else ' ')+observed.strftime('%d %b %H:%M'))
            except (KeyError,ValueError,TypeError):pass
    if len(gaps)>8:clocks.append(str(len(gaps)-8)+' further unavailable fields')
    v.write(' | '.join(clocks) or 'Source times unavailable',M+11,773,517,6.3,'#D8E3F1',max_lines=2)
    v.c.save()
