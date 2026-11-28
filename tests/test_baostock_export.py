"""baostock 导出脚本的纯函数测试（不联网、不需要 baostock）。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.export_baostock_snapshot import (  # noqa: E402
    _asset,
    _asset_to_code,
    _continuous_rows,
    _extend_continuous,
    _fundamental_row,
    _latest_quarters,
    _merge_prices,
    _num,
    _overlap_changed,
    _trim_dates,
)


class HelperTests(unittest.TestCase):
    def test_asset_code_mapping(self) -> None:
        self.assertEqual(_asset("sh.600000"), "600000.SH")
        self.assertEqual(_asset("sz.000001"), "000001.SZ")

    def test_asset_code_rejects_garbage(self) -> None:
        with self.assertRaises(ValueError):
            _asset("600000")

    def test_fundamental_row_derives_book_per_share(self) -> None:
        row = {
            "pubDate": "2024-04-30",
            "statDate": "2023-12-31",
            "epsTTM": "1.250401",
            "roeAvg": "0.051598",
        }
        parsed = _fundamental_row("600000.SH", row)
        self.assertEqual(parsed[0], "600000.SH")
        self.assertEqual(parsed[1], "2023-12-31")
        self.assertEqual(parsed[2], "2024-04-30")
        self.assertAlmostEqual(parsed[3], 1.250401 / 0.051598, places=3)
        self.assertAlmostEqual(parsed[4], 1.2504, places=3)

    def test_loss_making_quarter_is_skipped(self) -> None:
        row = {"pubDate": "2024-04-30", "statDate": "2023-12-31", "epsTTM": "-0.1", "roeAvg": "0.02"}
        self.assertIsNone(_fundamental_row("600000.SH", row))

    def test_missing_publish_date_is_skipped(self) -> None:
        row = {"pubDate": "", "statDate": "2023-12-31", "epsTTM": "1.0", "roeAvg": "0.1"}
        self.assertIsNone(_fundamental_row("600000.SH", row))

    def test_num_handles_empty_and_garbage(self) -> None:
        self.assertIsNone(_num(""))
        self.assertIsNone(_num(None))
        self.assertIsNone(_num("abc"))
        self.assertEqual(_num(" 1.5 "), 1.5)


def _price_row(date: str, asset: str, close: float) -> list:
    return [date, asset, str(close), str(close), str(close), str(close), "100", "1.0"]


class ContinuousPriceTests(unittest.TestCase):
    def test_ex_dividend_uses_preclose_not_previous_close(self) -> None:
        raw = [
            ["2020-11-24", "10", "10.1", "9.9", "10.0", "10.0", "100"],
            ["2020-11-25", "9.6", "9.7", "9.4", "9.5", "9.5", "100"],
        ]
        rows = _continuous_rows("600655.SH", raw)
        # 除权日 close/preclose = 0，连续价不变；不是用 10.0 算出的 -5%
        self.assertAlmostEqual(float(rows[0][5]), 10.0)
        self.assertAlmostEqual(float(rows[1][5]), 10.0)
        self.assertAlmostEqual(float(rows[1][2]), 10.0 * 9.6 / 9.5)

    def test_daily_return_is_continuous(self) -> None:
        raw = [
            ["2024-01-02", "10", "10", "10", "10", "10", "1"],
            ["2024-01-03", "11", "11", "11", "11", "10", "1"],
        ]
        rows = _continuous_rows("AAA", raw)
        self.assertAlmostEqual(float(rows[1][5]) / float(rows[0][5]) - 1, 0.1)


    def test_continuous_increment_uses_base_close(self) -> None:
        old = [["2024-01-02", "A", "10", "10", "10", "10", "1", "1.0"]]
        raw = [
            ["2024-01-02", "10", "10", "10", "10", "10", "1"],
            ["2024-01-03", "11", "11", "11", "11", "10", "1"],
        ]
        new = _extend_continuous(old, {"A": raw}, "2024-01-02")
        self.assertEqual(len(new), 1)
        self.assertAlmostEqual(float(new[0][5]), 11.0)

    def test_continuous_increment_ex_dividend(self) -> None:
        old = [["2024-01-02", "A", "10", "10", "10", "10", "1", "1.0"]]
        raw = [
            ["2024-01-02", "10", "10", "10", "10", "10", "1"],
            ["2024-01-03", "9.5", "9.5", "9.5", "9.5", "9.5", "1"],
        ]
        new = _extend_continuous(old, {"A": raw}, "2024-01-02")
        self.assertAlmostEqual(float(new[0][5]), 10.0)


class IncrementalHelperTests(unittest.TestCase):
    def test_asset_to_code_roundtrip(self) -> None:
        self.assertEqual(_asset_to_code("600000.SH"), "sh.600000")
        self.assertEqual(_asset("sh.600000"), "600000.SH")
        with self.assertRaises(ValueError):
            _asset_to_code("600000")

    def test_overlap_detects_corporate_action(self) -> None:
        old = [_price_row("2026-11-09", "600000.SH", 10.0)]
        new = [_price_row("2026-11-09", "600000.SH", 9.8)]  # 差 2%：超过容差
        bad = _overlap_changed(old, new, {"2026-11-09"})
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0][0], "600000.SH")

    def test_overlap_ignores_rounding_noise(self) -> None:
        old = [_price_row("2026-11-09", "600000.SH", 10.0)]
        new = [_price_row("2026-11-09", "600000.SH", 10.0004)]  # 0.004%
        self.assertEqual(_overlap_changed(old, new, {"2026-11-09"}), [])

    def test_merge_only_appends_after_last_date(self) -> None:
        old = [_price_row("2026-11-09", "600000.SH", 10.0)]
        new = [
            _price_row("2026-11-09", "600000.SH", 9.5),  # 重叠行不该覆盖
            _price_row("2026-11-10", "600000.SH", 10.2),
        ]
        merged = _merge_prices(old, new, "2026-11-09")
        self.assertEqual([r[0] for r in merged], ["2026-11-09", "2026-11-10"])
        self.assertEqual(merged[0][5], "10.0")

    def test_latest_quarters_wraps_year(self) -> None:
        self.assertEqual(
            _latest_quarters("2026-02-01", 3),
            [(2026, 1), (2025, 4), (2025, 3)],
        )

    def test_trim_dates_drops_day_without_prices(self) -> None:
        dates = ["2026-11-10", "2026-11-11", "2026-11-12"]
        prices = [_price_row("2026-11-11", "600000.SH", 10.0)]
        self.assertEqual(_trim_dates(dates, prices), ["2026-11-10", "2026-11-11"])

    def test_trim_dates_empty_prices(self) -> None:
        self.assertEqual(_trim_dates(["2026-11-10"], []), [])


if __name__ == "__main__":
    unittest.main()
