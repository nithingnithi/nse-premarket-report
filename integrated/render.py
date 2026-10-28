"""Fixed two-page layout; untrusted text escaped; numbers come from snapshot."""
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, KeepInFrame
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
STYLE=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=12,textColor=HexColor('#18263a'))

def text(v):return 'N/A' if v is None or v==[] else escape(str(v))
def block(c,items,x,y,w,h):
    flow=[Paragraph(i,STYLE) for i in items]
    box=KeepInFrame(w,h,flow,mode='error');box.wrapOn(c,w,h);box.drawOn(c,x,y+h-box.height)
def render(s,r,path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('NSE Morning Report '+s['report_date'])
    def header(page):
        c.setFillColor(HexColor('#112740'));c.rect(0,766,595,76,fill=1,stroke=0)
        c.setFillColor(HexColor('#ffffff'));c.setFont('Helvetica-Bold',18);c.drawString(32,809,'NSE Morning Report')
        c.setFont('Helvetica',10);c.drawString(32,789,s['report_date']+' | PARTIAL TRIAL | cutoff 07:45 IST')
        c.setFillColor(HexColor('#18263a'));c.setFont('Helvetica',8);c.drawString(32,20,f'Page {page}/2 | Source freshness and coverage limitations apply. No causal claims inferred.')
    header(1);q=s['score'];missing=', '.join(q['missing'])
    rows=[f'<b>{text(q["bias"])}</b>',f'Score: {q["score"]} | Available: {q["available"]}/6 | Possible range: {text(q["score_range"])}',f'<b>India VIX caution: {text(s.get("vix_flag","UNKNOWN"))}</b> (separate from score)',f'Missing signals: {text(missing)}','<br/><b>Top 3 alerts</b>']
    rows += [f'{i+1}. {text(a)}' for i,a in enumerate(r['alerts'])]
    rows += ['<br/><b>Review</b>',text(r['summary']),'<br/><b>Dated MCP context</b>']
    rows += [f'{text(x["source"])} | {text(x["data_date"])}: {text(x["text"])}' for x in r.get('mcp_context',[])] or ['N/A']
    rows += ['<br/><b>News: previous 12 hours ending at cutoff</b>']
    for a in s.get('news',[])[:6]:
        url=a.get('url','');parsed=urlsplit(url)
        if parsed.scheme not in ('https','http') or not parsed.netloc:url=''
        title=text(str(a.get('title','N/A'))[:160])
        rows.append(f'{text(a.get("published_IST"))} | '+(f'<link href="{escape(url,quote=True)}" color="#145a9c">{title}</link>' if url else title))
    if not s.get('news'):rows.append('N/A: no eligible news supplied.')
    rows += [text(s.get('news_note','Coverage unavailable.'))]
    block(c,rows,32,55,531,690);c.showPage();header(2)
    rows=['<b>Global / forex / commodities</b>']
    for a in s.get('global',[]):rows.append(f'{text(a["name"])}: {text(a.get("value"))} | {text(a.get("asof"))} | {text(a.get("status"))}')
    if not s.get('global'):rows.append('N/A')
    rows += ['<br/><b>Options: same-expiry archive observations (provisional)</b>']
    for name in ('NIFTY','BANKNIFTY'):
        a=s.get('options',{}).get(name,{})
        rows += [f'{name}: expiry {text(a.get("expiry"))} | PCR {text(a.get("pcr_current"))[:16]} | max pain {text(a.get("max_pain"))}',f'Call walls {text(a.get("call_walls"))}; put walls {text(a.get("put_walls"))}; OI changes CE {text(a.get("call_oi_change"))}, PE {text(a.get("put_oi_change"))}.']
    rows += ['<br/><b>Futures and institutional flows</b>']
    for a in s.get('flows',[]):
        obs=a.get('observations',[]);v=obs[0] if obs else {}
        if 'index-futures' in a['check']:
            detail=f'long {v.get("long_contracts","N/A")}, short {v.get("short_contracts","N/A")}, net {v.get("net_contracts","N/A")}, L/S {v.get("long_divided_by_short","N/A")}'
        elif 'cash' in a['check']:detail=f'3-session net {a.get("net_sum_last_3_raw","N/A")}; 5-session net {a.get("net_sum_last_5_raw","N/A")} (raw units)'
        else:detail='Scoring withheld: source consistency pending'
        rows.append(f'{text(a["check"])} | {text(a["status"])} | {text(detail)}')
    rows += ['<br/><b>Selected economic calendar (partial)</b>']
    for a in s.get('calendar',[])[:4]:rows.append(f'{text(a.get("scheduled_IST") or a.get("date_IST"))} | {text(a.get("title"))}')
    if not s.get('calendar'):rows.append('N/A')
    rows += ['<br/><b>Limitations / outstanding validation</b>']+[text(x) for x in s['limitations']]
    rows += [f'Previous sessions: {text(s.get("completed_sessions",{}).get("NFO"))}. Collected {text(s["collected_at_IST"])}.']
    block(c,rows,32,45,531,700);c.save()
