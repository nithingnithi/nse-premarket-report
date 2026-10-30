// Single-file Cloudflare Worker. Secrets are bindings, never logged.
const OWNER = 'nithingnithi/nse-premarket-report';
const CRONS = { '5 2 * * 1-5': 'preflight', '15 2 * * 1-5': 'collect', '50 2 * * 1-5': 'watchdog' };
// 2026 NSE equity/F&O trading holidays. Review annually before the year changes.
// Sources: https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf
// https://www.nseindia.com/resources/exchange-communication-holidays
const HOLIDAYS_2026 = new Set(['2026-01-15','2026-01-26','2026-03-03','2026-03-26',
  '2026-03-31','2026-04-03','2026-04-14','2026-05-01','2026-05-28','2026-06-26',
  '2026-09-14','2026-10-02','2026-10-20','2026-11-10','2026-11-24','2026-12-25']);
const parts = (time) => Object.fromEntries(new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short'
}).formatToParts(new Date(time)).map(x => [x.type, x.value]));
const day = (time) => { const p = parts(time); return `${p.year}-${p.month}-${p.day}`; };
const api = (repo, path) => `https://api.github.com/repos/${repo}/${path}`;

async function github(url, token, fetcher) {
  const response = await fetcher(url, { headers: { Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`, 'User-Agent': 'nse-report-worker' } });
  return response;
}

export async function run(cron, scheduledTime, env, fetcher = fetch, log = console) {
  const mode = CRONS[cron];
  if (!mode) throw new Error('Unknown cron');
  const p = parts(scheduledTime);
  if (p.weekday === 'Sat' || p.weekday === 'Sun') return 'WEEKEND';
  const date = day(scheduledTime);
  if (env.DRY_RUN === 'true') { log.log(`DRY_RUN ${mode} ${date}`); return 'DRY_RUN'; }
  const repo = env.REPO || OWNER, workflow = env.WORKFLOW_FILE || 'integrated-collect.yml';
  const ref = env.REF || 'main';
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !/^[\w.-]+\.ya?ml$/.test(workflow) || !/^[\w./-]+$/.test(ref))
    throw new Error('Invalid Worker configuration');
  if (!env.GITHUB_TOKEN) throw new Error('GitHub token missing');
  if (!date.startsWith('2026-')) {
    log.log(`trading calendar unavailable ${date}`);
    if (mode === 'watchdog') await alert(env, `NSE report ${date}: trading calendar needs review; delivery status cannot be assumed.`, fetcher, log);
    return 'CALENDAR_UNKNOWN';
  }
  if (HOLIDAYS_2026.has(date)) return 'HOLIDAY';
  if (mode !== 'watchdog') {
    if (ref !== 'main') throw new Error('Live collection dispatch requires main; use the isolated staging workflow');
    const response = await fetcher(api(repo, `actions/workflows/${workflow}/dispatches`), {
      method: 'POST', headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        'Content-Type': 'application/json', 'User-Agent': 'nse-report-worker' },
      body: JSON.stringify({ ref, inputs: { mode, report_date: date } })
    });
    log.log(`workflow_dispatch ${mode} ${date} HTTP ${response.status}`);
    if (response.status !== 204) await alert(env, `NSE report ${date}: workflow dispatch failed (HTTP ${response.status}).`, fetcher, log);
    return response.status === 204 ? 'DISPATCHED' : 'DISPATCH_FAILED';
  }
  const ledger = await github(api(repo, `contents/delivery_ledger/${date}.json?ref=main`), env.GITHUB_TOKEN, fetcher);
  if (ledger.status === 200) {
    try {
      const payload = await ledger.json();
      const data = JSON.parse(atob(payload.content.replace(/\s/g,'')));
      if (data.report_date === date && data.status === 'SENT' && /^[a-f0-9]{64}$/.test(data.pdf_sha256))
        return 'CONFIRMED_SENT';
    } catch { /* A malformed ledger is unconfirmed, so alert. */ }
  }
  await alert(env, `NSE report ${date}: confirmed Telegram delivery is absent by 08:20 IST (ledger HTTP ${ledger.status}). Inspect before retrying.`, fetcher, log);
  return 'ALERT_SENT';
}

async function alert(env, message, fetcher, log) {
  const token = env.ALERT_BOT_TOKEN, chat = env.ALERT_CHAT_ID;
  if (!/^\d+:[A-Za-z0-9_-]+$/.test(token || '') || !/^[1-9]\d*$/.test(chat || ''))
    throw new Error('Private alert configuration invalid');
  const endpoint = `https://api.telegram.org/bot${token}/`;
  const send = async (method, body) => fetcher(endpoint + method, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const check = await send('getChat', { chat_id: chat });
  if (check.status !== 200) throw new Error(`Private chat check HTTP ${check.status}`);
  const detail = await check.json();
  if (detail.ok !== true || detail.result?.type !== 'private' || String(detail.result?.id) !== chat)
    throw new Error('Alert destination is not private');
  const response = await send('sendMessage', { chat_id: chat, text: message });
  log.log(`private alert HTTP ${response.status}`);
  if (response.status !== 200) throw new Error('Private alert failed');
}

export default { async scheduled(controller, env, ctx) {
  ctx.waitUntil(run(controller.cron, controller.scheduledTime, env).catch(() => console.error('Worker run failed')));
} };
