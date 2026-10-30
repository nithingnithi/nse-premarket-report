// Single-file Cloudflare Worker. Secrets are bindings, never logged.
const OWNER = 'nithingnithi/nse-premarket-report';
const CRONS = { '5 2 * * 1-5': 'preflight', '15 2 * * 1-5': 'collect', '30 2 * * 1-5': 'watchdog' };
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
  // Holidays apply to all three crons. A failed calendar read fails closed.
  const holidayResponse = await github(api(repo, 'contents/holidays.json?ref=' + encodeURIComponent(ref)), env.GITHUB_TOKEN, fetcher);
  if (holidayResponse.status !== 200) throw new Error(`Holiday lookup HTTP ${holidayResponse.status}`);
  const encoded = await holidayResponse.json();
  const holidays = JSON.parse(atob(encoded.content.replace(/\s/g, '')));
  if (!Array.isArray(holidays) || !holidays.every(x => /^\d{4}-\d{2}-\d{2}$/.test(x)))
    throw new Error('Holiday calendar invalid');
  if (holidays.includes(date)) return 'HOLIDAY';
  if (mode !== 'watchdog') {
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
  if (ledger.status === 200) return 'LEDGER_PRESENT';
  if (ledger.status !== 404) throw new Error(`Ledger check HTTP ${ledger.status}`);
  const runs = await github(api(repo, 'actions/runs?branch=main&status=success&per_page=100'), env.GITHUB_TOKEN, fetcher);
  if (runs.status !== 200) throw new Error(`Run check HTTP ${runs.status}`);
  const payload = await runs.json();
  if (!Array.isArray(payload.workflow_runs)) throw new Error('Run list invalid');
  const success = payload.workflow_runs.some(r => r.path === '.github/workflows/integrated-cloud.yml' &&
    r.conclusion === 'success' && day(Date.parse(r.created_at)) === date);
  if (success) return 'CLOUD_SUCCEEDED';
  await alert(env, `NSE report ${date}: no delivery ledger or successful cloud run by 08:00 IST. Inspect before retrying.`, fetcher, log);
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
