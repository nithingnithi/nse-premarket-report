# NSE morning scheduler (staged on improve/report-v2)

Deploy only after the reviewed workflows are merged to `main`; this Worker always dispatches `main`. It does not read market data or send a PDF.

1. In GitHub, create a **fine-grained** token limited to `nithingnithi/nse-premarket-report` with **Actions: write**. Store it only as the Cloudflare Worker secret `GITHUB_ACTIONS_TOKEN` (`wrangler secret put GITHUB_ACTIONS_TOKEN` from this directory). Never commit or print it. `repository_dispatch` is available in the workflow but requires **Contents: write** and is not used by this Worker.
2. Deploy from this directory with `wrangler deploy`. The Worker has no public HTTP route. Verify its three Cron Triggers in Cloudflare: 02:05, 02:15 and 02:30 UTC on weekdays (07:35, 07:45 and 08:00 IST).
3. At 07:35 the workflow performs only a date/mode preflight. At 07:45 it collects. At 08:00 the alert workflow checks the current date's ledger and sends the owner a **private** message if no verified channel delivery is recorded. Existing GitHub crons remain the collection/review fallback. GitHub/Cloudflare dispatch and job start may be delayed, so 08:00 is the check trigger, not a guaranteed notification time.
4. Confirm the first live scheduled run in Actions and verify the ledger and Telegram channel. If delivery is uncertain, inspect before any manual retry. Do not paste token values into logs or support messages.
