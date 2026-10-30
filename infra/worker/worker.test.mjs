import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('./worker.js', import.meta.url), 'utf8');
const { run } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const env = { REPO:'nithingnithi/nse-premarket-report', WORKFLOW_FILE:'integrated-collect.yml',
  REF:'main', DRY_RUN:'false', GITHUB_TOKEN:'fixture', ALERT_BOT_TOKEN:'123:fixture', ALERT_CHAT_ID:'12345' };
const date = Date.parse('2026-10-30T02:15:00Z');
const silent = { log() {} };
function fixture(dispatch=204, ledger=404, record=null) {
  const calls=[];
  const fetcher=async (url,options) => {
    calls.push({url,options});
    if (url.endsWith('/dispatches')) return {status:dispatch};
    if (url.includes('/delivery_ledger/')) return {status:ledger,json:async()=>({content:Buffer.from(JSON.stringify(record)).toString('base64')})};
    if (url.endsWith('/getChat')) return {status:200,json:async()=>({ok:true,result:{id:12345,type:'private'}})};
    if (url.endsWith('/sendMessage')) return {status:200};
    throw new Error('Unexpected fixture request');
  };
  return {calls,fetcher};
}
let f=fixture();
assert.equal(await run('15 2 * * 1-5',date,env,f.fetcher,silent),'DISPATCHED');
assert.equal(f.calls.filter(x=>x.url.endsWith('/dispatches')).length,1);
f=fixture(500);
assert.equal(await run('15 2 * * 1-5',date,env,f.fetcher,silent),'DISPATCH_FAILED');
assert.equal(f.calls.filter(x=>x.url.endsWith('/sendMessage')).length,1);
f=fixture();
assert.equal(await run('15 2 * * 1-5',Date.parse('2026-10-20T02:15:00Z'),env,f.fetcher,silent),'HOLIDAY');
assert.equal(f.calls.length,0);
f=fixture(204,200,{report_date:'2026-10-30',status:'RESERVED_UNCERTAIN_UNTIL_VERIFIED'});
assert.equal(await run('30 2 * * 1-5',date,env,f.fetcher,silent),'ALERT_SENT');
assert.equal(f.calls.filter(x=>x.url.endsWith('/sendMessage')).length,1);
f=fixture(204,200,{report_date:'2026-10-30',status:'SENT',pdf_sha256:'a'.repeat(64)});
assert.equal(await run('30 2 * * 1-5',date,env,f.fetcher,silent),'CONFIRMED_SENT');
assert.equal(f.calls.filter(x=>x.url.endsWith('/sendMessage')).length,0);
f=fixture();
assert.equal(await run('30 2 * * 1-5',Date.parse('2027-01-04T02:30:00Z'),env,f.fetcher,silent),'CALENDAR_UNKNOWN');
assert.equal(f.calls.filter(x=>x.url.endsWith('/sendMessage')).length,1);
f=fixture();
await assert.rejects(run('15 2 * * 1-5',date,{...env,REF:'improve/report-v2-deploy'},f.fetcher,silent));
assert.equal(f.calls.length,0);
console.log('7 Worker fixture cases passed');
