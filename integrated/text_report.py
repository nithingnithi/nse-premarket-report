"""One bounded, factual Telegram briefing from the dated handoff."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def value(item, key='value'):
    if not isinstance(item, dict) or item.get(key) is None:
        return 'N/A' + (f" ({item['reason']})" if isinstance(item, dict) and item.get('reason') else '')
    return str(item[key])


def short(text, limit=110):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit-1] + '…'


def stamp(text):
    try:
        d = datetime.fromisoformat(text)
        return d.astimezone(IST).strftime('%d %b %H:%M IST') if d.tzinfo else 'time N/A'
    except (TypeError, ValueError):
        return 'time N/A'


def format_report(snapshot, review):
    score = snapshot['score']
    cutoff = datetime.fromisoformat(snapshot['cutoff_IST'])
    if cutoff.tzinfo is None:
        raise ValueError('Cutoff must include a timezone')
    lines = [f"NSE morning briefing | {snapshot['report_date']} | cutoff 07:45 IST",
             f"Bias: {score['bias']} | score {score['score']:+d} | {score['available']}/6 signals",
             f"Range: {score['score_range']} | missing: {', '.join(score['missing']) or 'none'}",
             f"VIX: {value(snapshot.get('vix'), 'level')} | caution: {snapshot.get('vix_flag','UNKNOWN')}",
             '', 'Positive factors:']
    positives = [k for k, v in score['signals'].items() if v == 1]
    negatives = [k for k, v in score['signals'].items() if v == -1]
    lines += [', '.join(positives) or 'None confirmed', 'Negative factors:',
              ', '.join(negatives) or 'None confirmed', '', 'Top alerts:']
    lines += [short(a, 120) for a in review['alerts']]
    lines += ['', 'India markets:']
    for name, row in snapshot.get('indices', {}).items():
        lines.append(f"{name}: {value(row, 'last_price')} | change {value(row, 'change_pct')}% | {row.get('asof','N/A')}")
    lines += ['', 'Global / forex / oil:']
    for row in snapshot.get('global', []):
        lines.append(f"{row.get('name','Unknown')}: {value(row)} | {stamp(row.get('asof'))}")
    lines += ['', 'Options:']
    for name, row in snapshot.get('options', {}).items():
        lines.append(f"{name}: {row.get('status','N/A')} | expiry {row.get('expiry','N/A')} | PCR {value(row,'pcr_current')} | call wall {row.get('call_walls','N/A')} | put wall {row.get('put_walls','N/A')} | max pain {row.get('max_pain','N/A')} | {short(row.get('reason',''),50)}")
    lines += ['', 'Futures and flows:']
    for row in snapshot.get('flows', []):
        name=row.get('check','Unknown')
        detail=short(row.get('reason') or row.get('net_sum_last_5_raw') or row.get('delta_close') or '',55)
        observations=row.get('observations') or row.get('daily_observations') or []
        if name in ('FII cash','DII cash'):
            detail='₹ cr: '+', '.join(f"{x.get('date','?')} {x.get('net_raw','N/A')}" for x in observations[:5])
        elif name=='FII index-futures positions':
            detail=', '.join(f"{x.get('date','?')} L{x.get('long_contracts','N/A')}/S{x.get('short_contracts','N/A')}/net{x.get('net_contracts','N/A')}" for x in observations[:2])
        elif name.endswith('futures'):
            detail=f"expiry {row.get('expiry','N/A')}; "+', '.join(f"{x.get('date','?')} close {x.get('close','N/A')} OI {x.get('oi_raw','N/A')}" for x in observations[:2])
        lines.append(f"{name}: {row.get('status','N/A')} | {detail}")
    lines += ['', 'Recent news (12h to 07:45 IST):']
    eligible=[];seen=set()
    for row in snapshot.get('news',[]):
        try:published=datetime.fromisoformat(row['published_IST'])
        except (KeyError,TypeError,ValueError):continue
        if published.tzinfo is None or not cutoff-timedelta(hours=12)<published<=cutoff:continue
        key=(row.get('url') or row.get('title','')).casefold()
        if key in seen:continue
        seen.add(key);eligible.append(row)
    if eligible:
        for row in eligible:
            lines.append(f"• {short(row.get('title'),80)} | {row.get('outlet','outlet N/A')} | {stamp(row.get('published_IST'))}\n{row.get('url','link N/A')}")
    else:
        lines.append('No verified recent news')
    lines.append(f"News: {len(eligible)} shown of {snapshot.get('news_matched_count','N/A')} matched in the window | {snapshot.get('news_status','N/A')}")
    if snapshot.get('news_note'):lines.append(short(snapshot['news_note'],100))
    lines += ['', 'Calendar:']
    for row in snapshot.get('calendar', []):
        lines.append(f"{short(row.get('title'),45)} | {stamp(row.get('scheduled_IST'))} | {row.get('source','link N/A')}")
    lines += ['', f"Data: {snapshot.get('collection_status','N/A')} | collected {stamp(snapshot.get('collected_at_IST'))}"]
    message = '\n'.join(lines)
    if not 1 <= len(message) <= 4096:
        raise ValueError('Plain-text report exceeds Telegram message limit')
    return message
