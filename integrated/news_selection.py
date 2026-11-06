"""Deterministic, bounded selection of market headlines for the briefing."""
import datetime as dt
import re
import unicodedata
from difflib import SequenceMatcher

MARKET_TERMS={
    'nifty':5,'sensex':5,'bank nifty':5,'nse':4,'rbi':4,'federal reserve':4,
    'fed':3,'inflation':3,'cpi':3,'interest rate':3,'rupee':3,'oil':2,
    'crude':2,'earnings':2,'tariff':2,'treasury':2,'market':1,'stocks':1,
}
PERSONAL_TERMS=('credit card','personal loan','home loan','insurance plan',
                'tax saving','mutual fund sip','sip calculator','retirement planning',
                'best stocks to buy','how to invest')

def normalized(title):
    return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',title).casefold()))

def select(rows,cutoff,limit=6):
    lower=cutoff-dt.timedelta(hours=12)
    ranked=[]
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        title=row.get('title');published=row.get('published_IST')
        if not isinstance(title,str) or not isinstance(published,str):continue
        try:stamp=dt.datetime.fromisoformat(published)
        except ValueError:continue
        if stamp.tzinfo is None or not lower<stamp<=cutoff:continue
        key=normalized(title)
        if any(term in key for term in PERSONAL_TERMS):continue
        relevance=sum(weight for term,weight in MARKET_TERMS.items() if term in key)
        if relevance<=0:continue
        ranked.append((relevance,stamp,row,key))
    ranked.sort(key=lambda x:(-x[0],-x[1].timestamp()))
    kept=[]
    for _,_,row,key in ranked:
        if any(row.get('url')==prior.get('url') or key==prior_key or
               (len(key)>30 and len(prior_key)>30 and
                SequenceMatcher(None,key,prior_key).ratio()>=.92)
               for prior,prior_key in kept):continue
        kept.append((row,key))
        if len(kept)==limit:break
    return [row for row,_ in kept]
