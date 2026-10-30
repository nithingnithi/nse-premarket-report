import test from 'node:test';
import assert from 'node:assert/strict';
import {validateChain} from './chain_validation.mjs';

const base = () => ({records:{underlying:'NIFTY',timestamp:'2026-10-29T15:30:00+05:30',
  expiryDate:'2026-10-30',data:[
    {strikePrice:24000,expiryDate:'2026-10-30',CE:{openInterest:10},PE:{openInterest:20}},
    {strikePrice:24100,expiryDate:'2026-10-30',CE:{openInterest:5},PE:{openInterest:8}}
  ]}});
const cutoff = new Date('2026-10-30T07:45:00+05:30');
const validate = raw => validateChain(raw,'NIFTY',cutoff);

test('complete-looking chain remains partial until coverage and units are verified', () => {
  const result=validate(base());
  assert.equal(result.status,'PARTIAL');
  assert.equal(result.oi_unit,'UNVERIFIED');
});
test('missing option side is partial', () => {
  const raw=base(); delete raw.records.data[0].PE;
  assert.equal(validate(raw).status,'PARTIAL');
});
test('duplicate strike is unavailable', () => {
  const raw=base(); raw.records.data[1].strikePrice=24000;
  assert.equal(validate(raw).reason,'Duplicate strike');
});
test('null, blank, negative and nonfinite OI are unavailable', () => {
  for (const value of [null,'',-1,Infinity,'NaN']) {
    const raw=base(); raw.records.data[0].CE.openInterest=value;
    assert.equal(validate(raw).status,'UNAVAILABLE');
  }
});
test('mixed expiries are unavailable', () => {
  const raw=base(); raw.records.data[1].expiryDate='2026-11-06';
  assert.equal(validate(raw).reason,'Mixed or missing row expiry');
});
test('missing metadata and wrong source are withheld', () => {
  const raw=base(); delete raw.records.expiryDate;
  assert.equal(validate(raw).status,'PARTIAL');
  raw.records.expiryDate='2026-10-30'; raw.records.underlying='BANKNIFTY';
  assert.equal(validate(raw).status,'UNAVAILABLE');
});
test('future, stale and malformed source times are withheld', () => {
  const raw=base(); raw.records.timestamp='2026-10-30T12:00:00+05:30';
  assert.equal(validate(raw).reason,'Future-dated source timestamp');
  raw.records.timestamp='2026-10-20T15:30:00+05:30';
  assert.equal(validate(raw).reason,'Stale source timestamp');
  raw.records.timestamp='not a timestamp';
  assert.equal(validate(raw).status,'UNAVAILABLE');
});
