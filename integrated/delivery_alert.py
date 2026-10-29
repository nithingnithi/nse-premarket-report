"""Private, read-only delivery watchdog. Never retries or posts to the channel."""
import datetime as dt
import json
import os
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def decision(root, now):
    local = now.astimezone(IST)
    if local.time() < dt.time(8, 0):
        return 'TOO_EARLY'
    day = local.date().isoformat()
    snapshot = root / 'handoff' / f'{day}.json'
    if snapshot.exists():
        try:
            data = json.loads(snapshot.read_text(encoding='utf-8'))
            if data.get('report_date') == day and data.get('trading_day') == 'CLOSED':
                return 'CLOSED'
        except (OSError, ValueError, TypeError):
            pass
    ledger = root / 'delivery_ledger' / f'{day}.json'
    if ledger.exists():
        try:
            data = json.loads(ledger.read_text(encoding='utf-8'))
            if data.get('report_date') == day and data.get('status') == 'SENT':
                return 'DELIVERED'
        except (OSError, ValueError, TypeError):
            pass
    return 'ALERT'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_private(day, opener=None):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token) or not re.fullmatch(r'[1-9][0-9]*', chat):
        raise ValueError('Private Telegram alert configuration is unavailable')
    client = opener or urllib.request.build_opener(NoRedirect())
    def call(method, payload):
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method,
                                         data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with client.open(request, timeout=20) as response:
                result = json.load(response)
        except Exception:
            raise RuntimeError('Private delivery alert request failed; sensitive details suppressed') from None
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('Private delivery alert request was rejected; sensitive details suppressed')
        return result.get('result')
    destination = call('getChat', {'chat_id': chat})
    if not isinstance(destination, dict) or destination.get('type') != 'private' or destination.get('id') != int(chat):
        raise RuntimeError('Configured alert destination is not the verified private chat')
    call('sendMessage', {'chat_id': chat,
                         'text': f'NSE Morning Report {day}: no verified delivery was recorded by 08:00 IST. The PDF may have sent; inspect the channel and ledger before retrying.'})


def main():
    now = dt.datetime.now(IST)
    status = decision(Path('.'), now)
    if status != 'ALERT':
        print('DELIVERY_WATCHDOG', status)
        return
    if os.environ.get('DRY_RUN') == 'true':
        print('DELIVERY_WATCHDOG WOULD_ALERT')
        return
    send_private(now.date().isoformat())
    print('DELIVERY_WATCHDOG PRIVATE_ALERT_SENT')


if __name__ == '__main__':
    main()
