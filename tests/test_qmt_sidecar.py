"""QMT 只读导出路径的测试（用假的 xtquant，不需要本机装终端）。

2026-10 起 QMT 客户端被限制联网与本地文件读写，但终端里已有的数据仍可读。
这条路径最关键的性质是**只读**：`QmtProvider.fetch` 只能调用读接口，
绝不能调用 `download_history_data`。测试里的假 xtdata 一旦被下载调用就抛错，
把这条性质钉死。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers.qmt import QmtProvider  # noqa: E402
from quant.providers.snapshot_check import check_snapshot  # noqa: E402

DATES = ["20240102", "20240103", "20240104"]


class _Frame:
    """模拟 pandas.DataFrame 里被 qmt.py 用到的那一小部分。"""

    def __init__(self, rows: list[tuple[str, dict]]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def iterrows(self):
        return iter(self._rows)


def _bar(close: float, volume: float = 1000.0) -> dict:
    return {"open": close, "high": close, "low": close, "close": close, "volume": volume}


def _frames() -> dict:
    return {
        "AAA.SH": _Frame(
            [
                ("20240102", _bar(10.0)),
                ("20240103", _bar(0.0, 0)),  # 停牌：全 0 行
                ("20240104", _bar(12.0)),
            ]
        ),
        "BBB.SZ": _Frame(
            [
                ("20240102", _bar(5.0)),
                ("20240103", _bar(5.2)),
                ("20240104", _bar(5.4)),
            ]
        ),
        "CCC.SH": _Frame([]),  # 本地没下载过
    }


class FakeXtdata:
    def __init__(self, frames: dict, dates: list[str]) -> None:
        self.frames = frames
        self.dates = dates
        self.download_calls: list = []

    def get_market_data_ex(self, field_list=None, stock_list=None, period=None, start_time=None, end_time=None, dividend_type=None):
        if stock_list is None:
            return self.frames
        return {code: frame for code, frame in self.frames.items() if code in stock_list}

    def get_trading_dates(self, market, start_time=None, end_time=None):
        return self.dates

    def get_stock_list_in_sector(self, sector):
        return list(self.frames)

    def download_history_data(self, *args, **kwargs):
        self.download_calls.append((args, kwargs))
        raise AssertionError("只读导出不应调用 download_history_data")


def install_fake_xtdata(frames: dict | None = None, dates: list[str] | None = None) -> FakeXtdata:
    fake = FakeXtdata(frames or _frames(), dates or DATES)
    pkg = types.ModuleType("xtquant")
    sub = types.ModuleType("xtquant.xtdata")
    sub.get_market_data_ex = fake.get_market_data_ex
    sub.get_trading_dates = fake.get_trading_dates
    sub.get_stock_list_in_sector = fake.get_stock_list_in_sector
    sub.download_history_data = fake.download_history_data
    pkg.xtdata = sub
    sys.modules["xtquant"] = pkg
    sys.modules["xtquant.xtdata"] = sub
    return fake


class FakeXtquantCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-qmt-")
        self._saved = {k: sys.modules.get(k) for k in ("xtquant", "xtquant.xtdata")}
        self.fake = install_fake_xtdata()

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)


class ProviderReadOnlyTests(FakeXtquantCase):
    def test_fetch_never_downloads_and_fills_suspension(self) -> None:
        provider = QmtProvider(dividend_type="back")
        snap = provider.fetch("20240102", "20240104", "test_pool", stocks=["AAA.SH", "BBB.SZ"])
        self.assertEqual(self.fake.download_calls, [])
        self.assertEqual(len(snap.prices), 6)
        self.assertEqual(snap.notes["suspended_filled"], 1)
        self.assertEqual(snap.notes.get("empty_symbols", []), [])
        self.assertEqual(snap.adjust_mode, "backward")
        self.assertTrue(all(p["adj_factor"] == 1.0 for p in snap.prices))

        suspended = next(p for p in snap.prices if p["asset"] == "AAA.SH" and p["date"] == "2024-01-03")
        self.assertEqual(suspended["close"], 10.0)  # 沿用前收盘
        self.assertEqual(suspended["volume"], 0)
        self.assertAlmostEqual(
            next(p for p in snap.prices if p["asset"] == "AAA.SH" and p["date"] == "2024-01-04")["close"],
            12.0,
        )

    def test_missing_local_symbol_is_reported_not_fabricated(self) -> None:
        provider = QmtProvider()
        snap = provider.fetch("20240102", "20240104", "test_pool", stocks=["AAA.SH", "CCC.SH"])
        self.assertIn("CCC.SH", snap.notes["empty_symbols"])
        self.assertEqual({p["asset"] for p in snap.prices}, {"AAA.SH"})

    def test_universe_map_marks_point_in_time(self) -> None:
        provider = QmtProvider()
        snap = provider.fetch(
            "20240102",
            "20240104",
            "test_pool",
            stocks=["AAA.SH", "BBB.SZ"],
            universe_map={"2024-01-02": ["AAA.SH"], "2024-01-03": ["AAA.SH", "BBB.SZ"], "2024-01-04": ["AAA.SH"]},
        )
        self.assertTrue(snap.notes["universe_point_in_time"])
        self.assertEqual(len(snap.universe_rows), 4)

    def test_without_universe_map_it_admits_survivorship_risk(self) -> None:
        provider = QmtProvider()
        snap = provider.fetch("20240102", "20240104", "test_pool", stocks=["AAA.SH"])
        self.assertFalse(snap.notes["universe_point_in_time"])
        self.assertIn("幸存者偏差", snap.notes["universe_warning"])


class SidecarScriptTests(FakeXtquantCase):
    def _run(self, argv: list[str]) -> int:
        import contextlib
        import io

        from scripts.export_qmt_snapshot import main as export_main

        with contextlib.redirect_stdout(io.StringIO()):
            return export_main(argv)

    def test_probe_writes_nothing(self) -> None:
        out = os.path.join(self.dir, "never")
        code = self._run(
            ["--probe", "--stocks", "AAA.SH,CCC.SH", "--start", "20240102", "--end", "20240104", "--out", out]
        )
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(out))

    def test_export_passes_check_and_is_loadable(self) -> None:
        out = os.path.join(self.dir, "snap")
        code = self._run(
            [
                "--stocks",
                "AAA.SH,BBB.SZ",
                "--start",
                "20240102",
                "--end",
                "20240104",
                "--out",
                out,
                "--universe",
                "test_pool",
            ]
        )
        self.assertEqual(code, 0)
        result = check_snapshot(out)
        self.assertTrue(result["ok"], [c for c in result["checks"] if c["status"] == "fail"])
        self.assertEqual(self.fake.download_calls, [])

        from quant.data import load_panel

        panel = load_panel(out)
        self.assertEqual(panel.universe, "test_pool")
        self.assertEqual(panel.source, "qmt / xtquant（终端本地缓存，只读）")
        self.assertEqual(panel.adjust_mode, "backward")
        self.assertEqual(panel.filled_rows, 0)

    def test_missing_xtquant_is_a_clear_error(self) -> None:
        for name in ("xtquant", "xtquant.xtdata"):
            sys.modules.pop(name, None)
        code = self._run(["--probe", "--stocks", "AAA.SH", "--start", "20240102", "--end", "20240104"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
