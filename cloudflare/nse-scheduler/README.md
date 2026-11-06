# Retired scheduler — do not deploy

This older Wrangler project is retained for reference only. Its cron list is empty and its `scheduled` handler does not dispatch workflows. Do not run `wrangler deploy` here or activate this Worker in Cloudflare.

The only supported deployment path is [`infra/worker/worker.js`](../../infra/worker/worker.js), using [`docs/DEPLOY.md`](../../docs/DEPLOY.md). Its IST schedule is 07:35 preflight, 07:45 collection and 08:20 watchdog. If the old `nse-morning-scheduler` Worker already exists in Cloudflare, disable or delete its triggers before activating the canonical Worker.
