"""时点成分的测试：体检的覆盖率分母、导出脚本的名单前向填充。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402
from quant.providers.snapshot_check import check_snapshot  # noqa: E402
from scripts.export_baostock_snapshot import (  # noqa: E402
    _members_by_date,
    _month_ends,
    _universe_rows,
)

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]


def _snapshot(missing_days: tuple[str, ...] = ()) -> Snapshot:
    prices = []
    for d in DATES:
        prices.append({"date": d, "asset": "AAA", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100, "adj_factor": 1.0})
        if d not in missing_days:
            prices.append({"date": d, "asset": "BBB", "open": 5, "high": 5, "low": 5, "close": 5, "volume": 100, "adj_factor": 1.0})
    universe = []
    for d in DATES:
        universe.append({"date": d, "asset": "AAA"})
        if d == DATES[0]:
            universe.append({"date": d, "asset": "BBB"})  # BBB 只在第一天是成分
    return Snapshot(
        universe="pit_test",
        source="unit-test",
        provider="fixture",
        adjust_mode="none",
        prices=prices,
        calendar=[{"date": d} for d in DATES],
        universe_rows=universe,
    )


class PitCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-pit-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_outside_membership_is_not_a_hole(self) -> None:
        """BBB 只在第一天是成分，后面没行情是正常的，不该判缺失。"""
        write_snapshot(self.dir, _snapshot())
        result = check_snapshot(self.dir)
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        self.assertTrue(result["ok"], fails)

    def test_missing_inside_membership_still_fails(self) -> None:
        """BBB 第二天仍是成分但没行情，必须判 fail。"""
        snap = _snapshot(missing_days=("2024-01-03",))
        for row in snap.universe_rows:
            if row["date"] == "2024-01-03" and row["asset"] == "BBB":
                break
        else:
            snap.universe_rows.append({"date": "2024-01-03", "asset": "BBB"})
        write_snapshot(self.dir, snap)
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        self.assertIn("prices.coverage", {c["id"] for c in result["checks"] if c["status"] == "fail"})


class HelperTests(unittest.TestCase):
    def test_month_ends(self) -> None:
        cal = ["2024-01-02", "2024-01-31", "2024-02-01", "2024-02-29"]
        self.assertEqual(_month_ends(cal), ["2024-01-31", "2024-02-29"])

    def test_members_by_date_forwards_fill_and_rewrites_codes(self) -> None:
        by_effective = {"2019-12-30": {"sh.600000", "sz.000001"}}
        members = _members_by_date(["2020-01-02", "2020-01-03"], by_effective)
        self.assertEqual(members["2020-01-02"], {"600000.SH", "000001.SZ"})
        self.assertEqual(members["2020-01-03"], {"600000.SH", "000001.SZ"})

    def test_dates_before_first_snapshot_backfill_earliest_list(self) -> None:
        """第一个查询点之前的日期，用最早那份名单回填（半年调一次，这段没变化）。"""
        by_effective = {"2019-01-28": {"sh.600000"}}
        members = _members_by_date(["2019-01-02", "2019-01-28"], by_effective)
        self.assertEqual(members["2019-01-02"], {"600000.SH"})
        self.assertEqual(members["2019-01-28"], {"600000.SH"})

    def test_universe_rows_only_include_members(self) -> None:
        members = {
            "2020-01-02": {"600000.SH", "000001.SZ"},
            "2020-01-03": {"600000.SH"},
        }
        rows = _universe_rows(["2020-01-02", "2020-01-03"], members, ["sh.600000", "sz.000001"])
        self.assertEqual(
            rows,
            [["2020-01-02", "000001.SZ"], ["2020-01-02", "600000.SH"], ["2020-01-03", "600000.SH"]],
        )


if __name__ == "__main__":
    unittest.main()
