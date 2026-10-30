// Optional read-only NSE/BSE experiment. No network access by default.
// Deliberately locked until NSE/BSE automated-access terms are reviewed.
const NSE_BSE_NETWORK_ENABLED = false;
const enabled = NSE_BSE_NETWORK_ENABLED && process.argv.includes('--live') && process.env.ENABLE_NSE_BSE_PROBE === 'true';
if (!enabled) {
  console.log(JSON.stringify({status:'DISABLED',reason:'NSE/BSE network access pending terms review',data:[],production_scoring_enabled:false},null,2));
  process.exit(0);
}
const {validateChain} = await import('./chain_validation.mjs');
const result={status:'PROBE_ONLY',fetched_at:new Date().toISOString(),source:'nse-bse-api (unofficial)',production_scoring_enabled:false,data:[]};
async function sample(name,fn,validate) {
  try { result.data.push({name,status:'OBSERVED',...validate(await fn())}); }
  catch { result.data.push({name,status:'UNAVAILABLE',reason:'Provider error or invalid data (details withheld)'}); }
}
let nse,bse;
try {
  const pkg=await import('nse-bse-api');
  nse=new pkg.NSE(); bse=new pkg.BSE();
  await sample('NIFTY option chain V3',()=>nse.optionChainV3({symbol:'NIFTY'}),raw=>validateChain(raw,'NIFTY'));
  await sample('India VIX historical',()=>nse.fetch_historical_vix_data({from_date:new Date(Date.now()-7*86400000),to_date:new Date()}),raw=>{
    if(!Array.isArray(raw)||!raw.length)throw Error('Missing VIX history');
    return {status:'PARTIAL',rows:raw.length,reason:'VIX price, dates and source metadata unverified'};
  });
  await sample('BSE results calendar',()=>bse.resultCalendar({fromDate:new Date(),toDate:new Date(Date.now()+14*86400000)}),raw=>{
    if(!Array.isArray(raw))throw Error('Invalid events');
    return {status:'PARTIAL',rows:raw.length,reason:'Event dates and source metadata unverified'};
  });
} catch {
  result.status='SETUP_OR_PROVIDER_FAILURE'; result.reason='Dependency initialization failed (details withheld)';
} finally {
  try { await nse?.exit?.(); } catch {}
  try { await bse?.close?.(); } catch {}
}
console.log(JSON.stringify(result,null,2));
