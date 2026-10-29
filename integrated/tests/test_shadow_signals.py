import unittest
from decimal import Decimal
from integrated.shadow_signals import futures,options,build,config
from integrated.adapters.flows import choose_future
from nse_report.calculations import OptionRow,OptionChain,compare_options,score_summary,DataError

DAYS=['2026-10-28','2026-10-27']

def five_strike_summary():
    old=OptionChain('NIFTY','2026-11-03',DAYS[1],'RAW','NSE',tuple(
        OptionRow(k,c,p) for k,c,p in [(100,8,25),(110,30,15),(120,10,8),(130,5,4),(140,2,1)]))
    new=OptionChain('NIFTY','2026-11-03',DAYS[0],'RAW','NSE',tuple(
        OptionRow(k,c,p) for k,c,p in [(100,6,12),(110,10,40),(120,35,10),(130,5,3),(140,2,1)]))
    x=compare_options(new,old,expected_strikes=[100,110,120,130,140],latest_session=DAYS[0],previous_session=DAYS[1])
    return {'status':'PROVISIONAL','expiry':'2026-11-03','strikes':5,
        'pcr_direction':x['pcr_direction'],
        'call_walls_previous':list(x['previous']['call_walls']),
        'put_walls_previous':list(x['previous']['put_walls']),
        'call_walls':list(x['current']['call_walls']),
        'put_walls':list(x['current']['put_walls'])}

class ShadowTests(unittest.TestCase):
    def test_five_strike_hand_calculated(self):
        x=five_strike_summary()
        self.assertEqual((sum([12,40,10,3,1]),sum([6,10,35,5,2])),(66,58))
        self.assertEqual(x['pcr_direction'],'UP')
        self.assertEqual({k:v['value'] for k,v in options(x).items()},
                         {'pcr_direction':1,'strike_walls':1})
    def test_expiry_day_keeps_one_contract(self):
        rows=[{'underlying_key':'NSE_INDEX|Nifty 50','instrument_key':'NSE_FO|101',
               'instrument_type':'FUT','segment':'NSE_FO','exchange':'NSE',
               'underlying_type':'INDEX','expiry':'2026-10-29','lot_size':65},
              {'underlying_key':'NSE_INDEX|Nifty 50','instrument_key':'NSE_FO|102',
               'instrument_type':'FUT','segment':'NSE_FO','exchange':'NSE',
               'underlying_type':'INDEX','expiry':'2026-11-23','lot_size':65}]
        from datetime import date
        selected=choose_future(rows,'NSE_INDEX|Nifty 50',date(2026,10,29))
        self.assertEqual(selected['instrument_key'],'NSE_FO|101')
        bar={'check':'NIFTY futures','status':'PASS',**selected,'latest_date':DAYS[0],
             'previous_date':DAYS[1],
             'daily_observations':[{'date':DAYS[0],'close':'95','oi_raw':1100},
                                   {'date':DAYS[1],'close':'100','oi_raw':1000}]}
        self.assertEqual(futures(bar,DAYS,'2026-10-29')['value'],-1)
        bar['daily_observations'][1]['date']='2026-10-26'
        self.assertIsNone(futures(bar,DAYS,'2026-10-29')['value'])
    def test_27_to_28_oct_rollover_uses_next_contract_on_both_days(self):
        from datetime import date
        rows=[{'underlying_key':'NSE_INDEX|Nifty 50','instrument_key':'NSE_FO|201',
               'instrument_type':'FUT','segment':'NSE_FO','exchange':'NSE',
               'underlying_type':'INDEX','expiry':'2026-10-27','lot_size':65},
              {'underlying_key':'NSE_INDEX|Nifty 50','instrument_key':'NSE_FO|202',
               'instrument_type':'FUT','segment':'NSE_FO','exchange':'NSE',
               'underlying_type':'INDEX','expiry':'2026-11-24','lot_size':65}]
        selected=choose_future(rows,'NSE_INDEX|Nifty 50',date(2026,10,29))
        self.assertEqual(selected['instrument_key'],'NSE_FO|202')
        pair={'status':'PASS',**selected,'latest_date':'2026-10-28','previous_date':'2026-10-27',
              'daily_observations':[{'date':'2026-10-28','close':'101','oi_raw':1100},
                                    {'date':'2026-10-27','close':'100','oi_raw':1000}]}
        self.assertEqual(futures(pair,DAYS,'2026-10-29')['value'],1)
    def test_tie_withholds_both_option_candidates(self):
        x=five_strike_summary();x['call_walls']=['120','130']
        result=options(x)
        self.assertTrue(all(v['value'] is None and 'tied' in v['reason'] for v in result.values()))
    def test_missing_side_or_baseline_has_reason(self):
        for x in ({'status':'UNAVAILABLE','reason':'Unpaired'},None):
            result=options(x)
            self.assertTrue(all(v['value'] is None and v['reason'] for v in result.values()))
    def test_shadow_does_not_change_score_or_bias(self):
        live={'fii_futures':-1,'fii_cash':1,'dii_cash':1}
        before=score_summary(live,bullish_threshold=3,bearish_threshold=-3)
        shadows=build([],five_strike_summary(),DAYS,'2026-10-29',True)
        after=score_summary(live,bullish_threshold=3,bearish_threshold=-3)
        self.assertEqual(before,after)
        self.assertEqual((after['score'],after['available'],after['bias']),
                         (1,3,'INSUFFICIENT DATA TO ASSIGN FINAL BIAS'))
        self.assertEqual(shadows['pcr_direction']['value'],1)
        with self.assertRaises(DataError):score_summary(live,bullish_threshold=2)
        self.assertEqual((config()['bullish_threshold'],config()['bearish_threshold']),(3,-3))
