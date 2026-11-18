"""Manual, no-send GitHub Actions probe. Never print keys or raw responses."""
import datetime as dt
import os
from zoneinfo import ZoneInfo
from integrated.adapters import extra_data


def main():
    now=dt.datetime.now(ZoneInfo('Asia/Kolkata'))
    cutoff=now.replace(hour=7,minute=45,second=0,microsecond=0)
    result=extra_data.run(cutoff,os.environ.get('FRED_API_KEY',''),
                          os.environ.get('ALPHAVANTAGE_API_KEY',''))
    lines=['## Extra-data provider probe',
           'Manual read-only check. No Telegram, Drive, or report publication.',
           'All data values and credentials are omitted from this summary.',
           f"FRED DGS10: {result['us_10y']['status']}; date: {result['us_10y'].get('date','N/A')}; reason: {result['us_10y'].get('reason','none')}"]
    for name,row in result['adrs'].items():
        lines.append(f"ADR {name}: {row['status']}; date: {row.get('date','N/A')}; reason: {row.get('reason','none')}")
    lines.append(f"Requests: FRED {result['requests']['fred']}, Alpha Vantage {result['requests']['alpha']}")
    lines.append('Gold and silver remain unverified; this probe does not request them.')
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as handle:
            handle.write('\n\n'.join(lines)+'\n')
    print('Extra-data probe complete; see the sanitized job summary.')
    if result['us_10y']['status']!='PROVISIONAL' or not any(
            row['status']=='PROVISIONAL' for row in result['adrs'].values()):
        raise SystemExit('A provider did not return a validated dated observation.')


if __name__=='__main__':main()
