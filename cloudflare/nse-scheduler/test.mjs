import assert from "node:assert/strict";
import { dispatch } from "./src/index.js";

const seen = [];
const mockFetch = async (url, options) => {
  seen.push({ url, options });
  return { ok: true, status: 204 };
};
const scheduled = Date.parse("2026-10-29T02:05:00Z");
await dispatch("5 2 * * 1-5", scheduled, "fixture", mockFetch);
await dispatch("15 2 * * 1-5", scheduled + 600000, "fixture", mockFetch);
await dispatch("30 2 * * 1-5", scheduled + 1500000, "fixture", mockFetch);
assert.deepEqual(seen.map(({ options }) => JSON.parse(options.body).inputs.mode),
                 ["preflight", "collect", undefined]);
assert(seen.every(({ options }) => JSON.parse(options.body).ref === "main"));
assert(seen.every(({ options }) => options.headers.Authorization === "Bearer fixture"));
assert(seen.every(({ url }) => url.includes("/actions/workflows/")));
assert.deepEqual(JSON.parse(seen[1].options.body).inputs.report_date, "2026-10-29");
await assert.rejects(dispatch("unknown", scheduled, "fixture", mockFetch));
console.log("Worker dispatch fixture tests passed");
