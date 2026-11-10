"""schema v2 的加载与通用 CSV 导入器测试。

覆盖四件事，每一件都对应一个真实会咬人的错：

1. ``adj_factor`` 要乘回价格，否则除权日就是假跌停；
2. ``available_date`` 决定财报哪天生效，之前必须是 NaN 而不是 0；
3. ``universe.csv`` 让排名只看当日成分，未上市/已退出的不进池；
4. 停牌空洞用前收盘填充并**计数**，不允许静默发生。
"""
from __future__ import annotations

import csv
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.data import DataError, load_panel  # noqa: E402
from quant.engine import run_backtest  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402
from quant.providers.csv_import import import_snapshot  # noqa: E402
from quant.spec import parse_spec  # noqa: E402

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]


def _write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _price_row(d: str, a: str, close: float, *, factor: float = 1.0, volume: int = 1000) -> dict:
    return {
        "date": d,
        "asset": a,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "adj_factor": factor,
    }


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-v2-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


class V2LoaderTests(TempDirCase):
    def _snapshot(self, **overrides) -> Snapshot:
        prices = [
            _price_row("2024-01-02", "AAA", 10.0, factor=1.0),
            _price_row("2024-01-03", "AAA", 10.0, factor=2.0),  # 复权后 20.0
            _price_row("2024-01-04", "AAA", 21.0, factor=2.0),  # 复权后 42.0
            _price_row("2024-01-02", "BBB", 5.0),
            _price_row("2024-01-03", "BBB", 5.5),
            _price_row("2024-01-04", "BBB", 6.0),
        ]
        base = dict(
            universe="test_pool",
            source="unit-test",
            provider="fixture",
            adjust_mode="backward",
            prices=prices,
            calendar=[{"date": d} for d in DATES],
            fundamentals=[
                {
                    "asset": "AAA",
                    "report_date": "2023-12-31",
                    "available_date": "2024-01-03",
                    "book": 100.0,
                    "earnings": 10.0,
                }
            ],
            universe_rows=[
                {"date": "2024-01-02", "asset": "AAA"},
                {"date": "2024-01-03", "asset": "AAA"},
                {"date": "2024-01-03", "asset": "BBB"},
                {"date": "2024-01-04", "asset": "AAA"},
            ],
        )
        base.update(overrides)
        return Snapshot(**base)

    def test_adj_factor_is_multiplied_into_prices(self) -> None:
        write_snapshot(self.dir, self._snapshot())
        panel = load_panel(self.dir)
        self.assertEqual(panel.data_version[:3], "dv-")
        self.assertAlmostEqual(panel.close["AAA"][0], 10.0)
        self.assertAlmostEqual(panel.close["AAA"][1], 20.0)
        self.assertAlmostEqual(panel.close["AAA"][2], 42.0)
        # 后复权后收益是 +100%，不是 0%
        self.assertAlmostEqual(panel.close["AAA"][1] / panel.close["AAA"][0] - 1.0, 1.0)

    def test_fundamentals_take_effect_on_available_date(self) -> None:
        write_snapshot(self.dir, self._snapshot())
        panel = load_panel(self.dir)
        self.assertTrue(panel.book["AAA"][0] != panel.book["AAA"][0])  # NaN：公告日之前不可用
        self.assertAlmostEqual(panel.book["AAA"][1], 100.0)
        self.assertAlmostEqual(panel.earnings["AAA"][2], 10.0)

    def test_universe_is_point_in_time(self) -> None:
        write_snapshot(self.dir, self._snapshot())
        panel = load_panel(self.dir)
        self.assertTrue(panel.has_point_in_time_universe())
        self.assertEqual(panel.allowed_at(0), ("AAA",))
        self.assertEqual(panel.allowed_at(1), ("AAA", "BBB"))
        self.assertEqual(panel.allowed_at(2), ("AAA",))

    def test_missing_cell_is_filled_and_counted(self) -> None:
        snap = self._snapshot()
        snap.prices = [p for p in snap.prices if not (p["date"] == "2024-01-03" and p["asset"] == "BBB")]
        snap.universe_rows = [r for r in snap.universe_rows if not (r["date"] == "2024-01-03" and r["asset"] == "BBB")]
        write_snapshot(self.dir, snap)
        panel = load_panel(self.dir)
        self.assertEqual(panel.filled_rows, 1)
        self.assertAlmostEqual(panel.close["BBB"][1], 5.0)  # 沿用前收盘
        self.assertEqual(panel.volume["BBB"][1], 0.0)

    def test_calendar_day_without_any_price_is_rejected(self) -> None:
        snap = self._snapshot(calendar=[{"date": d} for d in DATES] + [{"date": "2024-01-05"}])
        write_snapshot(self.dir, snap)
        with self.assertRaises(DataError) as ctx:
            load_panel(self.dir)
        self.assertIn("截断", str(ctx.exception))

    def test_duplicate_price_row_is_rejected(self) -> None:
        snap = self._snapshot()
        snap.prices.append(dict(snap.prices[0]))
        write_snapshot(self.dir, snap)
        with self.assertRaises(DataError) as ctx:
            load_panel(self.dir)
        self.assertIn("重复", str(ctx.exception))

    def test_v1_sample_is_unchanged(self) -> None:
        """旧快照必须逐位不变：data_version 是实验登记簿里的外键。"""
        panel = load_panel()
        self.assertEqual(panel.data_version, "dv-572bafec2a92")
        self.assertEqual(panel.schema_version, 1)
        self.assertEqual(panel.filled_rows, 0)
        self.assertFalse(panel.has_point_in_time_universe())


class UniverseInEngineTests(TempDirCase):
    def test_out_of_universe_asset_is_never_picked(self) -> None:
        """BBB 价格完全不动（低波动因子会给它最高分），但它不在池里，就不该被选中。"""
        dates = [f"2024-{(m):02d}-{(d):02d}" for m in (1, 2, 3) for d in range(1, 29)]
        dates = sorted(set(dates))
        prices = []
        for i, d in enumerate(dates):
            prices.append(_price_row(d, "AAA", 10.0 + (i % 5) * 0.2))
            prices.append(_price_row(d, "BBB", 5.0))  # 零波动
            prices.append(_price_row(d, "CCC", 8.0 + (i % 3) * 0.3))
        snap = Snapshot(
            universe="test_pool",
            source="unit-test",
            provider="fixture",
            adjust_mode="none",
            prices=prices,
            calendar=[{"date": d} for d in dates],
            universe_rows=[{"date": d, "asset": a} for d in dates for a in ("AAA", "CCC")],
            notes={"universe_point_in_time": True},
        )
        write_snapshot(self.dir, snap)

        old = os.environ.get("NFR_DATA_DIR")
        os.environ["NFR_DATA_DIR"] = self.dir
        try:
            spec = parse_spec(
                {
                    "factor": "low_vol_60d",
                    "universe": "test_pool",
                    "start": dates[61],
                    "end": dates[-1],
                    "rebalance": "W",
                    "top_k": 1,
                    "cost_bps": 10,
                }
            )
            bt = run_backtest(spec)
        finally:
            if old is None:
                os.environ.pop("NFR_DATA_DIR", None)
            else:
                os.environ["NFR_DATA_DIR"] = old

        self.assertTrue(bt.holdings)
        for h in bt.holdings:
            self.assertNotIn("BBB", h["names"])
        self.assertTrue(bt.provenance["data_universe_point_in_time"])
        self.assertEqual(bt.provenance["data_source"], "unit-test")


class CsvImportTests(TempDirCase):
    def test_chinese_headers_and_compact_dates(self) -> None:
        raw = os.path.join(self.dir, "prices.csv")
        _write_csv(
            raw,
            ["交易日期", "股票代码", "开盘价", "最高价", "最低价", "收盘价", "成交量", "复权因子"],
            [
                ["20240103", "600000.SH", "10.5", "11", "10.2", "10.8", "1,000", "1"],
                ["20240102", "600000.SH", "10", "10.6", "9.9", "10.5", "2,000", "1"],
            ],
        )
        out = os.path.join(self.dir, "snap")
        result = import_snapshot(out, prices_path=raw, universe="csi300", source="unit-test")
        self.assertTrue(result["ok"], result["check"]["checks"])
        panel = load_panel(out)
        self.assertEqual(panel.dates, ["2024-01-02", "2024-01-03"])
        self.assertAlmostEqual(panel.close["600000.SH"][1], 10.8)
        self.assertEqual(panel.volume["600000.SH"][0], 2000)

    def test_row_order_does_not_change_fingerprint(self) -> None:
        header = ["date", "asset", "open", "high", "low", "close", "volume", "adj_factor"]
        rows = [
            ["2024-01-02", "AAA", "10", "10", "10", "10", "100", "1"],
            ["2024-01-02", "BBB", "5", "5", "5", "5", "100", "1"],
            ["2024-01-03", "AAA", "11", "11", "11", "11", "100", "1"],
            ["2024-01-03", "BBB", "6", "6", "6", "6", "100", "1"],
        ]
        a = os.path.join(self.dir, "a.csv")
        b = os.path.join(self.dir, "b.csv")
        _write_csv(a, header, rows)
        _write_csv(b, header, list(reversed(rows)))
        first = import_snapshot(os.path.join(self.dir, "s1"), prices_path=a, universe="p")
        second = import_snapshot(os.path.join(self.dir, "s2"), prices_path=b, universe="p")
        self.assertEqual(first["data_version"], second["data_version"])

    def test_fundamentals_without_available_date_are_rejected(self) -> None:
        raw = os.path.join(self.dir, "fundamentals.csv")
        _write_csv(
            raw,
            ["asset", "report_date", "available_date", "book", "earnings"],
            [["AAA", "2023-12-31", "", "100", "10"]],
        )
        with self.assertRaises(Exception) as ctx:
            import_snapshot(
                os.path.join(self.dir, "snap"),
                prices_path=self._price_file(),
                universe="p",
                fundamentals_path=raw,
            )
        self.assertIn("公告日", str(ctx.exception))

    def test_importer_rejects_duplicate_rows(self) -> None:
        raw = os.path.join(self.dir, "dup.csv")
        _write_csv(
            raw,
            ["date", "asset", "open", "high", "low", "close", "volume"],
            [
                ["2024-01-02", "AAA", "10", "10", "10", "10", "100"],
                ["2024-01-02", "AAA", "10", "10", "10", "10", "100"],
            ],
        )
        with self.assertRaises(Exception) as ctx:
            import_snapshot(os.path.join(self.dir, "snap"), prices_path=raw, universe="p")
        self.assertIn("重复", str(ctx.exception))

    def _price_file(self) -> str:
        raw = os.path.join(self.dir, "ok_prices.csv")
        _write_csv(
            raw,
            ["date", "asset", "open", "high", "low", "close", "volume"],
            [["2024-01-02", "AAA", "10", "10", "10", "10", "100"]],
        )
        return raw


if __name__ == "__main__":
    unittest.main()
