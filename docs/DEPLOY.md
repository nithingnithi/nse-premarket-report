# Browser-only deployment checklist

Canonical Worker for the plain-text morning briefing: `infra/worker/worker.js`. Do not also deploy the older `cloudflare/nse-scheduler` Worker or the PDF Worker from `improve/report-v2-deploy`; disable any old triggers before activating this one.

1. Merge the reviewed plain-text workflow to `main` before enabling the Worker. The Worker dispatches only the `main` workflows.
2. In GitHub Settings → Developer settings → Personal access tokens, create a fine-grained token for **this repository only**, with Actions **read/write** and Contents **read** (holiday and ledger checks). Set a short expiry. Never paste it into this repository or a chat.
3. In Cloudflare Workers & Pages, create a Worker, paste the single file `infra/worker/worker.js` into the browser editor, and save it.
4. Set plain variables: `REPO=nithingnithi/nse-premarket-report`, `REF=main`, `DRY_RUN=true` for the initial test.
5. Set encrypted secrets in Cloudflare: `GITHUB_TOKEN`, `ALERT_BOT_TOKEN`, `ALERT_CHAT_ID`. Use the verified owner **private** chat, not the channel ID. Do not expose their values in logs.
6. Add four Cloudflare Cron Triggers in UTC on Monday–Friday: `15 2 * * 2-6`, `25 2 * * 2-6`, `35 2 * * 2-6`, `50 2 * * 2-6`. These correspond to 07:45 collection, 07:55 briefing, 08:05 backup and 08:20 watchdog IST. Cloudflare numbers Sunday as 1; remove any old `1-5` triggers.
7. Use Cloudflare's scheduled-event test with `DRY_RUN=true`; confirm only `DRY_RUN` status appears and no GitHub/Telegram request occurs. Check the GitHub workflow list and the bot's private destination separately.
8. Set `DRY_RUN=false` only after the dry test. The 08:20 watchdog requires the dated `SENT` ledger with a text hash and Telegram message ID. On the first open morning, confirm Actions runs, `handoff/latest.json`, the ledger and the text message in the channel. A data failure should produce an explicitly labelled unavailable-data status by 08:05, not invented market figures.
9. Rollback: set `DRY_RUN=true`, disable the four Cloudflare triggers, and disable the two GitHub scheduled workflows if all automatic sends must stop. Inspect the ledger and channel before any manual resend.

The Worker calendar covers 2026 only; update its reviewed holiday dates before 2027. GitHub and Cloudflare can both run late. A failed ledger check raises a private alert. A failed private alert still requires manual inspection of Worker logs.
