// Optional read-only NSE/BSE experiment. No network access by default.
const enabled = process.argv.includes('--live') && process.env.ENABLE_NSE_BSE_PROBE === 'true';
if (!enabled) {
  console.log(JSON.stringify({status:'DISABLED',reason:'Requires --live and ENABLE_NSE_BSE_PROBE=true',data:[],production_scoring_enabled:false},null,2));
  process.exit(0);
}
const result={status:'PROBE_ONLY',fetched_at:new Date().toISOString(),source:'nse-bse-api (unofficial)',production_scoring_enabled:false,data:[]};
async function sample(name,fn,validate) {
  try { result.data.push({name,status:'OBSERVED',...validate(await fn())}); }
  catch { result.data.push({name,status:'UNAVAILABLE',reason:'Provider error or invalid data (details withheld)'}); }
}
let nse,bse;
try {
  const pkg=await import('nse-bse-api');
  nse=new pkg.NSE(); bse=new pkg.BSE();
  await sample('NIFTY option chain V3',()=>nse.optionChainV3({symbol:'NIFTY'}),raw=>{
    const rows=raw?.records?.data, timestamp=raw?.records?.timestamp;
    if(!Array.isArray(rows)||!rows.length||!timestamp)throw Error('Missing chain or time');
    if(!rows.every(r=>Number.isFinite(Number(r.strikePrice))&&Number(r.strikePrice)>0&&
      (!r.CE||(Number.isFinite(Number(r.CE.openInterest))&&Number(r.CE.openInterest)>=0))&&
      (!r.PE||(Number.isFinite(Number(r.PE.openInterest))&&Number(r.PE.openInterest)>=0))))
      throw Error('Invalid strike or OI');
    return {asof_source:timestamp,rows:rows.length,expiries:[...new Set(rows.map(r=>r.expiryDates).filter(Boolean))],
      note:'Metadata only; no PCR, max pain or scoring. Validate complete chain against NSE EOD records.'};
  });
  await sample('India VIX historical',()=>nse.fetch_historical_vix_data({from_date:new Date(Date.now()-7*86400000),to_date:new Date()}),raw=>{
    if(!Array.isArray(raw)||!raw.length)throw Error('Missing VIX history');
    return {rows:raw.length,note:'Availability only; price and timestamps require verification'};
  });
  await sample('BSE results calendar',()=>bse.resultCalendar({fromDate:new Date(),toDate:new Date(Date.now()+14*86400000)}),raw=>{
    if(!Array.isArray(raw))throw Error('Invalid events');
    return {rows:raw.length,note:'Event dates not verified'};
  });
} catch {
  result.status='SETUP_OR_PROVIDER_FAILURE'; result.reason='Dependency initialization failed (details withheld)';
} finally {
  try { await nse?.exit?.(); } catch {}
  try { await bse?.close?.(); } catch {}
}
console.log(JSON.stringify(result,null,2));
