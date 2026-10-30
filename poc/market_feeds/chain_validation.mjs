// Offline schema checks only. No provider calls and no derived trading values.
const number = value => (typeof value === 'number' ||
  (typeof value === 'string' && value.trim() !== '')) && Number.isFinite(Number(value));

function sourceTime(value) {
  if (typeof value !== 'string') return null;
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const match = /^(\d\d)-([A-Za-z]{3})-(\d{4}) (\d\d):(\d\d):(\d\d)$/.exec(value);
  if (!match) return null;
  const month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    .indexOf(match[2][0].toUpperCase()+match[2].slice(1).toLowerCase());
  if (month < 0) return null;
  const parsed = new Date(Date.UTC(Number(match[3]),month,Number(match[1]),
    Number(match[4]),Number(match[5])-330,Number(match[6])));
  const local = new Date(parsed.getTime()+330*60000);
  if (local.getUTCFullYear() !== Number(match[3]) || local.getUTCMonth() !== month ||
      local.getUTCDate() !== Number(match[1]) || local.getUTCHours() !== Number(match[4]) ||
      local.getUTCMinutes() !== Number(match[5]) || local.getUTCSeconds() !== Number(match[6])) return null;
  return parsed;
}

export function validateChain(raw, expectedSymbol = 'NIFTY', cutoff = new Date(), maxAgeHours = 72) {
  const records = raw?.records;
  if (!records || !Array.isArray(records.data) || !records.data.length) {
    return {status:'UNAVAILABLE', reason:'Missing option-chain rows'};
  }
  const asof = sourceTime(records.timestamp);
  if (!asof || Number.isNaN(cutoff.getTime())) return {status:'UNAVAILABLE', reason:'Invalid source timestamp'};
  if (asof > cutoff) return {status:'UNAVAILABLE', reason:'Future-dated source timestamp'};
  if (cutoff - asof > maxAgeHours*3600000) return {status:'PARTIAL', reason:'Stale source timestamp'};
  const sourceSymbol = records.underlying ?? records.symbol;
  if (sourceSymbol !== expectedSymbol) {
    return {status:'UNAVAILABLE', reason:'Missing or mismatched underlying identifier'};
  }
  const expiry = records.expiryDate;
  if (typeof expiry !== 'string' || !expiry.trim()) {
    return {status:'PARTIAL', reason:'Selected expiry missing from metadata', rows:records.data.length};
  }
  const seen = new Set();
  let missingSides = 0;
  for (const row of records.data) {
    if (row?.expiryDate !== expiry ||
        (row.CE?.expiryDate && row.CE.expiryDate !== expiry) ||
        (row.PE?.expiryDate && row.PE.expiryDate !== expiry)) {
      return {status:'UNAVAILABLE', reason:'Mixed or missing row expiry'};
    }
    if (!number(row.strikePrice) || Number(row.strikePrice) <= 0) {
      return {status:'UNAVAILABLE', reason:'Invalid strike'};
    }
    const strike = Number(row.strikePrice);
    if (seen.has(strike)) return {status:'UNAVAILABLE', reason:'Duplicate strike'};
    seen.add(strike);
    if (!row.CE || !row.PE) {
      missingSides++;
      continue;
    }
    if (!number(row.CE.openInterest) || Number(row.CE.openInterest) < 0 ||
        !number(row.PE.openInterest) || Number(row.PE.openInterest) < 0) {
      return {status:'UNAVAILABLE', reason:'Missing or invalid option OI'};
    }
  }
  if (missingSides) {
    return {status:'PARTIAL', reason:'Missing CE or PE side', expiry, rows:records.data.length,
      missing_side_rows:missingSides};
  }
  // A response alone cannot prove full strike coverage, timestamp freshness or OI units.
  return {status:'PARTIAL', reason:'Full strike coverage, timestamp freshness and OI units unverified',
    expiry, rows:records.data.length, asof_source:records.timestamp,
    oi_unit:'UNVERIFIED'};
}
