"""AkShare 适配器与快照交叉验证的测试（不联网）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers import akshare as ak_provider  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402
from scripts.compare_snapshots import compare  # noqa: E402

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]


def _snapshot(dir_path: str, closes: dict, universe=None, assets=("AAA", "BBB"), dates=None) -> None:
    dates = dates or DATES
    prices = []
    for asset in assets:
        for day, close in zip(dates, closes[asset]):
            prices.append(
                {
                    "date": day,
                    "asset": asset,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                    "adj_factor": 1.0,
                }
            )
    if universe is None:
        universe = [{"date": d, "asset": a} for d in dates for a in assets]
    write_snapshot(
        dir_path,
        Snapshot(
            universe="test",
            source="fixture",
            provider="fixture",
            adjust_mode="backward",
            prices=prices,
            calendar=[{"date": d} for d in dates],
            universe_rows=universe,
        ),
    )


class AkshareBuildTests(unittest.TestCase):
    def test_frame_rows_chains_pct(self) -> None:
        class DF:
            columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"]

            def iterrows(self):
                yield 0, {"日期": "2024-01-02", "开盘": 10, "收盘": 10, "最高": 10, "最低": 10, "成交量": 1, "涨跌幅": 0}
                yield 1, {"日期": "2024-01-03", "开盘": 11, "收盘": 11, "最高": 11, "最低": 11, "成交量": 1, "涨跌幅": 10}

        rows, used = ak_provider._frame_rows(DF(), "AAA")
        self.assertTrue(used)
        self.assertAlmostEqual(rows[0]["close"], 10.0)
        self.assertAlmostEqual(rows[1]["close"], 11.0)

    def test_frame_rows_ex_dividend_pct_zero(self) -> None:
        class DF:
            columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"]

            def iterrows(self):
                yield 0, {"日期": "2024-01-02", "开盘": 10, "收盘": 10, "最高": 10, "最低": 10, "成交量": 1, "涨跌幅": 0}
                yield 1, {"日期": "2024-01-03", "开盘": 9.5, "收盘": 9.5, "最高": 9.5, "最低": 9.5, "成交量": 1, "涨跌幅": 0}

        rows, _ = ak_provider._frame_rows(DF(), "AAA")
        self.assertAlmostEqual(rows[1]["close"], 10.0)

    def test_coverage_uses_membership_dates(self) -> None:
        rows = []
        for asset, closes in (("AAA", [10, 11, 12]), ("BBB", [20, 21])):
            for day, close in zip(DATES, closes):
                rows.append(
                    {"date": day, "asset": asset, "open": close, "high": close, "low": close, "close": close, "volume": 1, "adj_factor": 1.0}
                )
        universe = [{"date": d, "asset": "AAA"} for d in DATES] + [
            {"date": d, "asset": "BBB"} for d in DATES[:2]
        ]
        with mock.patch.object(ak_provider, "fetch_prices", return_value=(rows, [])):
            snap, warnings = ak_provider.build_snapshot(
                assets=["AAA", "BBB"],
                start=DATES[0],
                end=DATES[-1],
                universe_name="test",
                calendar=DATES,
                universe_rows=universe,
                min_coverage=0.9,
            )
        self.assertEqual(snap.assets(), ["AAA", "BBB"])

    def test_coverage_filter_and_universe(self) -> None:
        rows = []
        for asset, closes in (("AAA", [10, 11, 12]), ("BBB", [20, 21])):
            for day, close in zip(DATES, closes):
                rows.append(
                    {"date": day, "asset": asset, "open": close, "high": close, "low": close, "close": close, "volume": 1, "adj_factor": 1.0}
                )
        with mock.patch.object(ak_provider, "fetch_prices", return_value=(rows, [])):
            snap, warnings = ak_provider.build_snapshot(
                assets=["AAA", "BBB"],
                start=DATES[0],
                end=DATES[-1],
                universe_name="test",
                calendar=DATES,
                universe_rows=[{"date": d, "asset": a} for d in DATES for a in ("AAA", "BBB")],
                min_coverage=0.9,
            )
        self.assertEqual(snap.assets(), ["AAA"])
        self.assertTrue(any("BBB" in w for w in warnings))
        self.assertEqual({r["asset"] for r in snap.universe_rows}, {"AAA"})


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nvr-cmp-")
        self.a = os.path.join(self.dir, "a")
        self.b = os.path.join(self.dir, "b")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_compare_can_write_manifest_crosscheck(self) -> None:
        from scripts import compare_snapshots

        closes = {"AAA": [10, 11, 12], "BBB": [20, 21, 22]}
        _snapshot(self.a, closes)
        _snapshot(self.b, closes)
        code = compare_snapshots.main(["--a", self.a, "--b", self.b, "--update-manifest", self.b])
        self.assertEqual(code, 0)
        import json

        with open(os.path.join(self.b, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["crosscheck"]["verdict"], "ok")

    def test_identical(self) -> None:
        closes = {"AAA": [10, 11, 12], "BBB": [20, 21, 22]}
        _snapshot(self.a, closes)
        _snapshot(self.b, closes)
        result = compare(self.a, self.b)
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["return_diff_max"], 0.0)

    def test_constant_price_ratio_is_adjust_basis(self) -> None:
        _snapshot(self.a, {"AAA": [10, 11, 12], "BBB": [20, 21, 22]})
        _snapshot(self.b, {"AAA": [20, 22, 24], "BBB": [40, 42, 44]})
        result = compare(self.a, self.b)
        self.assertEqual(result["verdict"], "ok")
        self.assertAlmostEqual(result["price_ratio_median"], 0.5)

    def test_return_mismatch_warns(self) -> None:
        _snapshot(self.a, {"AAA": [10, 11, 12], "BBB": [20, 21, 22]})
        _snapshot(self.b, {"AAA": [10, 11, 13], "BBB": [20, 21, 22]})
        result = compare(self.a, self.b)
        self.assertIn(result["verdict"], ("warn", "warn_adjust_basis"))
        self.assertGreater(result["return_diff_max"], 0.002)

    def test_missing_rows_and_universe_diff(self) -> None:
        _snapshot(self.a, {"AAA": [10, 11, 12], "BBB": [20, 21, 22]})
        universe_b = [{"date": d, "asset": "AAA"} for d in DATES]
        _snapshot(self.b, {"AAA": [10, 11], "BBB": [20, 21, 22]}, universe=universe_b)
        result = compare(self.a, self.b)
        self.assertGreater(result["missing_rows_a"], 0)
        self.assertGreater(result["universe_diff_dates"], 0)


if __name__ == "__main__":
    unittest.main()
