"""Append one compact comparison row per completed collection run."""
import csv
import json
import os
from pathlib import Path

KEYS=('futures_build_up','pcr_direction','strike_walls')
FIELDS=('report_date','run_id','attempt','official_score','available_of_6','official_bias',
        *(f'shadow_{key}' for key in KEYS),*(f'reason_{key}' for key in KEYS))

def row(snapshot,run_id,attempt):
    score=snapshot['score'];shadows=snapshot.get('shadow_signals',{})
    item={'report_date':snapshot['report_date'],'run_id':str(run_id),'attempt':str(attempt),
          'official_score':score['score'],'available_of_6':score['available'],
          'official_bias':score['bias']}
    for key in KEYS:
        value=shadows.get(key,{})
        item[f'shadow_{key}']=value.get('value') if value.get('value') is not None else 'N/A'
        item[f'reason_{key}']=value.get('reason') or ''
    return item

def append(path,snapshot,run_id,attempt):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    if path.exists():
        with path.open(newline='',encoding='utf-8') as stream:
            reader=csv.DictReader(stream)
            if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError('Shadow history columns changed')
            records=list(reader)
    new=row(snapshot,run_id,attempt)
    identity=(new['report_date'],new['run_id'],new['attempt'])
    records=[r for r in records if (r['report_date'],r['run_id'],r['attempt'])!=identity]
    records.append(new)
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(records)
    return len(records)

def main():
    report_date=os.environ.get('REPORT_DATE')
    if not report_date:
        pointer=json.loads(Path('handoff/latest.json').read_text())
        report_date=pointer['report_date']
    snapshot=json.loads((Path('handoff')/(report_date+'.json')).read_text())
    count=append('history/shadow-signals.csv',snapshot,os.environ.get('GITHUB_RUN_ID','local'),
                 os.environ.get('GITHUB_RUN_ATTEMPT','1'))
    print('SHADOW_HISTORY_ROWS',count)

if __name__=='__main__':main()
