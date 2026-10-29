"""Resolve the IST report date and safely gate external workflow triggers."""
import datetime as dt
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def resolve(now, event, input_mode='', input_date='', payload_mode='', payload_date=''):
    local = now.astimezone(IST)
    day = local.date().isoformat()
    mode = (payload_mode if event == 'repository_dispatch' else input_mode) or 'collect'
    requested = payload_date if event == 'repository_dispatch' else input_date
    if mode not in ('collect', 'preflight'):
        raise ValueError('Unsupported schedule mode')
    if requested:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', requested) or requested != day:
            raise ValueError('Requested report date is not today in IST')
    start = local.replace(hour=7, minute=45, second=0, microsecond=0)
    end = start + dt.timedelta(minutes=25)
    collect = mode == 'collect' and start <= local <= end
    return {'day': day, 'mode': mode, 'collect': collect}


def main():
    try:
        result = resolve(dt.datetime.now(IST), os.environ.get('GITHUB_EVENT_NAME', ''),
                         os.environ.get('INPUT_MODE', ''), os.environ.get('INPUT_REPORT_DATE', ''),
                         os.environ.get('PAYLOAD_MODE', ''), os.environ.get('PAYLOAD_REPORT_DATE', ''))
    except ValueError:
        raise SystemExit('Schedule trigger rejected: mode or IST report date invalid') from None
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with Path(output).open('a', encoding='utf-8') as stream:
            for key, value in result.items():
                stream.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')
    print('SCHEDULE_GATE', result['day'], result['mode'], 'collect' if result['collect'] else 'skip')


if __name__ == '__main__':
    main()
