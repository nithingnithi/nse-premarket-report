"""Send a bounded status update when the dated market handoff is unavailable."""
import datetime as dt
import json
import os
from pathlib import Path

from integrated.deliver import persist, reserve
from integrated.review import IST
from integrated.telegram import send_text


def status_message(day, reason):
    return (f"NSE morning briefing | {day} | 07:45 IST cutoff\n"
            "Market data: N/A\n"
            "Bias: INSUFFICIENT DATA TO ASSIGN FINAL BIAS | score N/A | coverage N/A\n"
            "Positive factors: none verified\n"
            "Negative factors: none verified\n"
            "Recent news and calendar: N/A\n"
            f"Reason: {reason}\n"
            "This is a delivery/status check, not a market call.")


def decision(root, now):
    local = now.astimezone(IST)
    day = local.date().isoformat()
    if local.weekday() >= 5:
        return None
    if (root / f'delivery_ledger/{day}.json').exists():
        return None
    snapshot_path = root / f'handoff/{day}.json'
    try:
        snapshot = json.loads(snapshot_path.read_text())
    except (OSError, ValueError):
        snapshot = None
    if isinstance(snapshot, dict) and snapshot.get('report_date') == day:
        if snapshot.get('trading_day') == 'CLOSED':
            return None
    if not dt.time(8, 5) <= local.time() <= dt.time(8, 10):
        return None
    if isinstance(snapshot, dict) and snapshot.get('report_date') == day:
        if snapshot.get('trading_day') == 'OPEN':
            return status_message(day, 'Today’s market handoff was not validated for delivery.')
        return status_message(day, 'Today’s trading session or provider data could not be verified.')
    return status_message(day, 'Today’s market handoff was not available by 08:05 IST; trading session unverified.')


def run(root, now, dry_run=True, commit=persist, sender=send_text, clock=None):
    message = decision(root, now)
    if message is None:
        local = now.astimezone(IST)
        day = local.date().isoformat()
        if (local.weekday() < 5 and local.time() > dt.time(8, 10)
                and not (root / f'delivery_ledger/{day}.json').exists()):
            snapshot_path = root / f'handoff/{day}.json'
            try:
                snapshot = json.loads(snapshot_path.read_text())
            except (OSError, ValueError):
                snapshot = None
            if not (isinstance(snapshot, dict) and snapshot.get('report_date') == day
                    and snapshot.get('trading_day') == 'CLOSED'):
                raise ValueError('No confirmed delivery by fallback cutoff')
        return 'SKIPPED'
    if dry_run:
        return message
    day = now.astimezone(IST).date().isoformat()
    ledger = root / f'delivery_ledger/{day}.json'
    reserve(ledger, {'report_date': day, 'status': 'RESERVED_UNCERTAIN_UNTIL_VERIFIED',
                     'run_id': os.environ.get('GITHUB_RUN_ID')}, commit)
    current = clock() if clock is not None else dt.datetime.now(IST)
    if current.astimezone(IST).date() != now.astimezone(IST).date() or not dt.time(8, 5) <= current.astimezone(IST).time() <= dt.time(8, 10):
        raise ValueError('Fallback delivery window closed after reservation')
    result = sender(message)
    ledger.write_text(json.dumps({'report_date': day, **result}, indent=2))
    commit(ledger)
    return result['status']


def main():
    dry = os.environ.get('DRY_RUN', 'true') == 'true'
    try:
        result = run(Path('.'), dt.datetime.now(IST), dry_run=dry)
    except Exception:
        raise SystemExit('Morning fallback failed safely; inspect the delivery ledger and channel before any retry.')
    print('MORNING_FALLBACK_' + ('DRY_RUN' if isinstance(result, str) and result.startswith('NSE morning') else str(result)))


if __name__ == '__main__':
    main()
