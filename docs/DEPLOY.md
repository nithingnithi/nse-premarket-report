# Browser-only deployment checklist

Canonical Worker: `infra/worker/worker.js` only. The `cloudflare/nse-scheduler` Wrangler project is retired; do not deploy it. If an older `nse-morning-scheduler` Worker is already active, disable or delete its triggers before enabling this Worker.

1. Keep `infra/worker/worker.js` on `improve/report-v2-deploy` until its tests and GitHub Actions review pass. Do not enable the Worker before the workflow changes reach `main`.
2. In GitHub Settings → Developer settings → Personal access tokens, create a fine-grained token for **this repository only**, with Actions **read/write** and Contents **read** (holiday and ledger checks). Set a short expiry. Never paste it into this repository or a chat.
3. In Cloudflare Workers & Pages, create a Worker, paste the single file `infra/worker/worker.js` into the browser editor, and save it.
4. Set plain variables: `REPO=nithingnithi/nse-premarket-report`, `WORKFLOW_FILE=integrated-collect.yml`, `REF=improve/report-v2-deploy` during staging, `DRY_RUN=true`.
5. Set encrypted secrets in Cloudflare: `GITHUB_TOKEN`, `ALERT_BOT_TOKEN`, `ALERT_CHAT_ID`. Use the verified owner **private** chat, not the channel ID. Do not expose their values in logs.
6. Add three Cron Triggers in UTC on Monday–Friday: `5 2 * * 1-5`, `15 2 * * 1-5`, `50 2 * * 1-5`. These correspond to 07:35, 07:45, 08:20 IST. Remove the old `30 2 * * 1-5` trigger if present.
7. Use Cloudflare's scheduled-event test with `DRY_RUN=true`; confirm only `DRY_RUN` status appears and no GitHub/Telegram request occurs. Check the GitHub workflow list and the bot's private destination separately.
8. After reviewed merge to `main`, switch `REF=main`, then `DRY_RUN=false`. The 07:35 dispatch is preflight; 07:45 collects; 08:20 checks for a dated, confirmed `SENT` delivery ledger. Confirm first-morning Actions results, `handoff/latest.json`, delivery ledger, PDF in channel, and private alert behavior.
9. Rollback: set `DRY_RUN=true` immediately, then disable all three Cloudflare Cron Triggers. Leave the GitHub native fallback crons as configured; inspect the ledger before any manual resend.

GitHub/Cloudflare scheduling can run late. A failed holiday or ledger check stops without sending an alert; inspect Worker logs if the morning result is missing.
