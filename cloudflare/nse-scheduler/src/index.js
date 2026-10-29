const TARGETS = {
  "5 2 * * 1-5": { workflow: "integrated-collect.yml", mode: "preflight" },
  "15 2 * * 1-5": { workflow: "integrated-collect.yml", mode: "collect" },
  "30 2 * * 1-5": { workflow: "integrated-delivery-alert.yml", mode: "alert" },
};

function istDay(timestamp) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export async function dispatch(cron, scheduledTime, token, fetcher = fetch) {
  const target = TARGETS[cron];
  if (!target || !token) throw new Error("Scheduler configuration is incomplete");
  const inputs = target.mode === "alert" ? {} : {
    mode: target.mode, report_date: istDay(scheduledTime),
  };
  const response = await fetcher(
    `https://api.github.com/repos/nithingnithi/nse-premarket-report/actions/workflows/${target.workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "nse-morning-scheduler",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    },
  );
  if (!response.ok) throw new Error(`GitHub dispatch failed: HTTP ${response.status}`);
  return { mode: target.mode, reportDate: istDay(scheduledTime) };
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatch(controller.cron, controller.scheduledTime, env.GITHUB_ACTIONS_TOKEN)
      .then(({ mode, reportDate }) => console.log(`Dispatched ${mode} for ${reportDate}`))
      .catch((error) => console.error(error.message)));
  },
};
