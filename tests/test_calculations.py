"""Invented inputs only: none of these fixtures is market evidence."""

import itertools
import unittest
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from nse_report.calculations import (
    CashRow, DataError, FutureBar, MissingData, OptionChain, OptionRow, SIGNALS,
    cash_trends, compare_options, fii_positions, futures_build_up, number,
    option_metrics, score_summary, select_expiry, vix_caution,
)

LATEST, PREVIOUS, EXPIRY = "2030-01-08", "2030-01-07", "2030-01-10"
SESSIONS = (LATEST, PREVIOUS, "2030-01-04", "2030-01-03", "2030-01-02")
STRIKES = (100, 110, 120)


def future(session=LATEST, close=105, oi=1100):
    return FutureBar("TEST_FUT|1", EXPIRY, session, close, oi, "raw_test_counts", "SYNTHETIC")


def chain(session=LATEST, calls=(10, 20, 10), puts=(30, 20, 10)):
    return OptionChain("TEST_INDEX", EXPIRY, session, "raw_test_counts", "SYNTHETIC",
                       tuple(OptionRow(*row) for row in zip(STRIKES, calls, puts)))


def cash(participant="FII", nets=(-10, 20, -5, 15, -30)):
    return [CashRow(participant, d, 100 + n, 100, "raw_test_amount", "SYNTHETIC")
            for d, n in zip(SESSIONS, nets)]


class FuturesTests(unittest.TestCase):
    def calculate(self, current, previous=None):
        return futures_build_up(current, previous or future(PREVIOUS, 100, 1000),
                                latest_session=LATEST, previous_session=PREVIOUS)

    def test_four_hand_worked_classes(self):
        for price, oi, expected in (
            (105, 1100, "LONG_BUILD_UP"), (95, 1100, "SHORT_BUILD_UP"),
            (105, 900, "SHORT_COVERING"), (95, 900, "LONG_UNWINDING"),
        ):
            with self.subTest(expected=expected):
                result = self.calculate(future(close=price, oi=oi))
                self.assertEqual(result["classification"], expected)
                self.assertEqual(result["price_change"], price - 100)
                self.assertEqual(result["oi_change"], oi - 1000)

    def test_flat_price_or_oi_has_no_directional_class(self):
        for price, oi in ((100, 1100), (105, 1000), (100, 1000)):
            self.assertEqual(self.calculate(future(close=price, oi=oi))["classification"],
                             "NO_DIRECTIONAL_BUILD_UP")

    def test_zero_previous_oi_does_not_divide_by_zero(self):
        self.assertIsNone(self.calculate(future(), future(PREVIOUS, 100, 0))["oi_change_pct"])

    def test_missing_is_not_zero(self):
        with self.assertRaises(MissingData):
            self.calculate(future(oi=None))

    def test_roll_units_and_provider_mismatches_fail(self):
        for changes in ({"instrument": "TEST_FUT|2"}, {"expiry": "2030-02-10"},
                        {"unit": "lots"}, {"provider": "OTHER"}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                self.calculate(replace(future(), **changes))

    def test_stale_and_expired_observations_fail(self):
        for bar in (replace(future(), session=PREVIOUS), replace(future(), expiry="2030-01-06")):
            with self.assertRaises(DataError):
                self.calculate(bar)

    def test_reversed_expected_sessions_fail(self):
        with self.assertRaises(DataError):
            futures_build_up(future(), future(PREVIOUS), latest_session=PREVIOUS,
                             previous_session=LATEST)


class OptionTests(unittest.TestCase):
    def metrics(self, value=None):
        return option_metrics(value or chain(), expected_strikes=STRIKES)

    def comparison(self, current=None, previous=None):
        return compare_options(current or chain(), previous or chain(PREVIOUS, (8, 18, 9), (25, 18, 7)),
                               expected_strikes=iter(STRIKES), latest_session=LATEST,
                               previous_session=PREVIOUS)

    def test_hand_worked_pcr_walls_and_max_pain(self):
        result = self.metrics()
        self.assertEqual((result["call_oi"], result["put_oi"], result["pcr"]), (40, 60, Fraction(3, 2)))
        self.assertEqual(result["call_walls"], (110,))
        self.assertEqual(result["put_walls"], (100,))
        self.assertEqual(result["payout_by_strike"], {100: 400, 110: 200, 120: 400})
        self.assertEqual(result["max_pain_strikes"], (110,))
        self.assertEqual(result["payout_unit"], "index points x raw_test_counts")

    def test_hand_worked_previous_oi_and_pcr_direction(self):
        result = self.comparison()
        self.assertEqual(result["previous"]["pcr"], Fraction(10, 7))
        self.assertEqual(result["pcr_change"], Fraction(1, 14))
        self.assertEqual(result["pcr_direction"], "UP")
        self.assertEqual((result["call_oi_change"], result["put_oi_change"]), (5, 10))
        self.assertEqual(result["strike_oi_changes"], {100: (2, 5), 110: (2, 2), 120: (1, 3)})

    def test_pcr_down_and_unchanged(self):
        self.assertEqual(self.comparison(previous=chain(PREVIOUS))["pcr_direction"], "UNCHANGED")
        self.assertEqual(self.comparison(previous=chain(PREVIOUS, puts=(40, 40, 40)))["pcr_direction"], "DOWN")

    def test_tied_walls_all_retained(self):
        result = self.metrics(chain(calls=(20, 20, 10), puts=(10, 20, 20)))
        self.assertEqual(result["call_walls"], (100, 110))
        self.assertEqual(result["put_walls"], (110, 120))

    def test_tied_max_pain_all_retained(self):
        result = self.metrics(chain(calls=(10, 0, 0), puts=(0, 0, 10)))
        self.assertEqual(result["max_pain_strikes"], (100, 110, 120))

    def test_zero_call_denominator_not_pcr_zero(self):
        result = self.metrics(chain(calls=(0, 0, 0)))
        self.assertIsNone(result["pcr"])
        self.assertEqual(result["call_walls"], ())
        self.assertIsNone(self.comparison(current=chain(calls=(0, 0, 0)))["pcr_direction"])

    def test_all_zero_oi_no_arbitrary_wall_or_max_pain(self):
        result = self.metrics(chain(calls=(0, 0, 0), puts=(0, 0, 0)))
        self.assertEqual(result["max_pain_strikes"], ())
        self.assertEqual(result["put_walls"], ())

    def test_incomplete_chain_and_missing_leg_fail(self):
        for value in (replace(chain(), rows=chain().rows[:-1]), chain(calls=(10, None, 10))):
            with self.assertRaises(MissingData):
                self.metrics(value)

    def test_duplicate_or_unexpected_strike_fail(self):
        for extra in (OptionRow(110, 1, 1), OptionRow(130, 1, 1)):
            with self.assertRaises(DataError):
                self.metrics(replace(chain(), rows=chain().rows + (extra,)))

    def test_invalid_expected_universe_fails(self):
        for universe, error in (((), MissingData), ((100, 100, 110, 120), DataError)):
            with self.assertRaises(error):
                option_metrics(chain(), expected_strikes=universe)

    def test_mixed_baseline_metadata_fails(self):
        for changes in ({"underlying": "OTHER"}, {"expiry": "2030-02-10"},
                        {"unit": "lots"}, {"provider": "OTHER"}, {"session": LATEST}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                self.comparison(previous=replace(chain(PREVIOUS), **changes))

    def test_missing_baseline_preserves_independent_current_metrics(self):
        self.assertEqual(self.metrics()["pcr"], Fraction(3, 2))
        with self.assertRaises(MissingData):
            self.comparison(previous=chain(PREVIOUS, puts=(None, 20, 10)))


class FlowsTests(unittest.TestCase):
    def positions(self, longs, shorts, **changes):
        return fii_positions(longs, shorts, session=changes.get("session", LATEST),
                             expected_session=LATEST, unit="raw_test_counts")

    def trends(self, rows=None, participant="FII"):
        return cash_trends(cash(participant) if rows is None else rows,
                           participant=participant, expected_sessions=SESSIONS,
                           unit="raw_test_amount", provider="SYNTHETIC")

    def test_hand_worked_fii_long_short_net_ratio(self):
        result = self.positions(120, 80)
        self.assertEqual((result["long"], result["short"], result["net"]), (120, 80, 40))
        self.assertEqual(result["long_short_ratio"], Fraction(3, 2))
        self.assertEqual(result["long_share"], Fraction(3, 5))
        self.assertEqual(result["scope"], "aggregate index futures")

    def test_fii_zero_denominators(self):
        self.assertIsNone(self.positions(120, 0)["long_short_ratio"])
        self.assertIsNone(self.positions(0, 0)["long_share"])
        self.assertEqual(self.positions(0, 80)["net"], -80)

    def test_fii_missing_or_stale_fails(self):
        with self.assertRaises(MissingData):
            self.positions(None, 80)
        with self.assertRaises(DataError):
            self.positions(120, 80, session=PREVIOUS)

    def test_hand_worked_three_and_five_cash_sessions(self):
        result = self.trends()
        self.assertEqual(result["net_3_sessions"], 5)
        self.assertEqual(result["net_5_sessions"], -10)
        dii = self.trends(cash("DII", (10, -20, 5, -15, 30)), participant="DII")
        self.assertEqual((dii["net_3_sessions"], dii["net_5_sessions"]), (-5, 10))

    def test_cash_input_order_does_not_change_session_windows(self):
        self.assertEqual(self.trends(list(reversed(cash()))), self.trends())

    def test_cash_missing_duplicate_or_extra_session_fails(self):
        for rows, error in ((cash()[:-1], MissingData), (cash() + [cash()[0]], DataError),
                            (cash() + [replace(cash()[0], session="2030-01-09")], DataError)):
            with self.assertRaises(error):
                self.trends(rows)

    def test_cash_mixed_units_participant_or_provider_fails(self):
        for changes in ({"unit": "crore"}, {"participant": "DII"}, {"provider": "OTHER"}):
            with self.assertRaises(DataError):
                self.trends([replace(cash()[0], **changes)] + cash()[1:])

    def test_cash_missing_amount_and_wrong_session_list_fail(self):
        with self.assertRaises(MissingData):
            self.trends([replace(cash()[0], buy=None)] + cash()[1:])
        for dates in (SESSIONS[:-1], tuple(reversed(SESSIONS)), (LATEST,) * 5):
            with self.assertRaises(DataError):
                cash_trends(cash(), participant="FII", expected_sessions=dates,
                            unit="raw_test_amount", provider="SYNTHETIC")


class ScoreTests(unittest.TestCase):
    def test_exact_thresholds_and_neutral_zero_counts_available(self):
        for points, bias in (((1, 1, 1, 0, 0, 0), "BULLISH"),
                             ((-1, -1, -1, 0, 0, 0), "BEARISH"),
                             ((1, 1, 0, 0, 0, 0), "NEUTRAL"),
                             ((0,) * 6, "NEUTRAL")):
            result = score_summary(dict(zip(SIGNALS, points)))
            self.assertEqual(result["bias"], bias)
            self.assertEqual(result["available"], 6)

    def test_partial_score_cannot_assign_direction_across_threshold(self):
        result = score_summary(dict(zip(SIGNALS, (1, 1, 1, 0, 0, None))))
        self.assertEqual((result["score"], result["available"], result["score_range"]), (3, 5, (2, 4)))
        self.assertEqual(result["bias"], "INSUFFICIENT DATA TO ASSIGN FINAL BIAS")
        self.assertEqual(result["missing"], ("dii_cash",))

    def test_provisional_conclusions(self):
        for values, expected in (((1, 1, 1, 1, 1, None), "PROVISIONAL BULLISH"),
                                 ((-1, -1, -1, -1, -1, None), "PROVISIONAL BEARISH"),
                                 ((0, 0, 0, 0, None, None), "PROVISIONAL NEUTRAL")):
            self.assertEqual(score_summary(dict(zip(SIGNALS, values)))["bias"], expected)

    def test_no_data_has_full_range(self):
        result = score_summary({})
        self.assertEqual((result["score"], result["available"], result["score_range"]), (0, 0, (-6, 6)))
        self.assertEqual(result["bias"], "INSUFFICIENT DATA TO ASSIGN FINAL BIAS")

    def test_invalid_points_and_seventh_signal_fail(self):
        for value in (True, False, 1.0, Decimal(1), "1", 2, -2):
            with self.assertRaises(DataError):
                score_summary({SIGNALS[0]: value})
        with self.assertRaises(DataError):
            score_summary({"vix": 1})

    def test_exhaustive_missing_signal_ranges(self):
        # Independent oracle: enumerate actual completions, then compare all bounds/categories.
        for values in itertools.product((-1, 0, 1, None), repeat=6):
            missing = [i for i, v in enumerate(values) if v is None]
            totals = []
            for replacement in itertools.product((-1, 0, 1), repeat=len(missing)):
                completed = list(values)
                for index, point in zip(missing, replacement):
                    completed[index] = point
                totals.append(sum(completed))
            categories = {"BULLISH" if s >= 3 else "BEARISH" if s <= -3 else "NEUTRAL" for s in totals}
            result = score_summary(dict(zip(SIGNALS, values)))
            self.assertEqual(result["score_range"], (min(totals), max(totals)))
            self.assertEqual(set(result["possible_categories"]), categories)
            self.assertEqual(result["available"], 6 - len(missing))
            if len(categories) > 1:
                self.assertEqual(result["bias"], "INSUFFICIENT DATA TO ASSIGN FINAL BIAS")


class ValidationAndPolicyTests(unittest.TestCase):
    def test_invalid_numbers_fail(self):
        for value in (-1, "NaN", "Infinity", "-Infinity", True, "abc", 1.2):
            with self.assertRaises(DataError):
                number(value, "OI", integer=True)
        with self.assertRaises(DataError):
            number("1.5", "OI", integer=True)

    def test_explicit_expiry_day_inclusion_and_no_weekday_assumption(self):
        expiries = ("2030-01-15", LATEST, "2030-01-01")
        self.assertEqual(select_expiry(expiries, report_date=LATEST, include_report_date=True), LATEST)
        self.assertEqual(select_expiry(expiries, report_date=LATEST, include_report_date=False), "2030-01-15")
        with self.assertRaises(MissingData):
            select_expiry(("2030-01-01",), report_date=LATEST, include_report_date=True)
        with self.assertRaises(DataError):
            select_expiry(expiries, report_date=LATEST, include_report_date=None)

    def test_vix_is_separate_and_requires_explicit_threshold(self):
        self.assertEqual(vix_caution(None, threshold=20), "UNKNOWN")
        self.assertEqual(vix_caution("19.9", threshold=20), "NO_THRESHOLD_FLAG")
        self.assertEqual(vix_caution(20, threshold=20), "CAUTION")
        self.assertEqual(vix_caution(21, threshold=20), "CAUTION")
        with self.assertRaises(TypeError):
            vix_caution(20)


if __name__ == "__main__":
    unittest.main()
