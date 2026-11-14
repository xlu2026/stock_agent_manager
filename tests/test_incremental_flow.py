"""增量刷新的编排测试：用假的 baostock 客户端，不联网。"""
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

from quant.data import load_panel  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402
from scripts.export_baostock_snapshot import _run_incremental  # noqa: E402

OLD = ["2024-01-02", "2024-01-03"]
NEW = ["2024-01-04", "2024-01-05"]
PROFIT_FIELDS = [
    "code", "pubDate", "statDate", "roeAvg", "npMargin", "gpMargin",
    "netProfit", "epsTTM", "MBRevenue", "totalShare", "liqaShare",
]


class FakeRS:
    def __init__(self, rows, fields=None):
        self._rows = rows
        self.fields = fields or []
        self.error_code = "0"
        self.error_msg = "success"
        self._i = -1

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


class FakeBS:
    def query_trade_dates(self, start_date, end_date):
        return FakeRS([[d, "1"] for d in OLD + NEW])

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        rows = [[d, "10.0", "10.0", "10.0", "10.0", "100"] for d in OLD + NEW]
        return FakeRS(rows)

    def query_hs300_stocks(self, date=""):
        return FakeRS([[date, "sh.600000", "测试"]])

    def query_profit_data(self, code, year, quarter):
        row = ["sh.600000", "2024-04-30", "2024-03-31", "0.1", "0.2", "0.3", "100", "1.0", "50", "1000", "1000"]
        return FakeRS([row], fields=PROFIT_FIELDS)


def _base_snapshot() -> Snapshot:
    return Snapshot(
        universe="test_pool",
        source="unit-test",
        provider="fixture",
        adjust_mode="backward",
        prices=[
            {"date": d, "asset": "600000.SH", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100, "adj_factor": 1.0}
            for d in OLD
        ],
        calendar=[{"date": d} for d in OLD],
        universe_rows=[{"date": d, "asset": "600000.SH"} for d in OLD],
        fundamentals=[
            {"asset": "600000.SH", "report_date": "2023-12-31", "available_date": "2024-01-02", "book": 10.0, "earnings": 1.0}
        ],
    )


class IncrementalFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-inc-")
        self.base = os.path.join(self.dir, "base")
        write_snapshot(self.base, _base_snapshot())

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _args(self, out: str, end: str = "2024-01-05") -> types.SimpleNamespace:
        return types.SimpleNamespace(
            out=out,
            base_dir=self.base,
            end=end,
            start="2024-01-02",
            overlap_days=2,
            adjust="backward",
            universe="test_pool",
            source="unit-test",
            stocks=None,
            index="hs300",
            sample=40,
            fundamentals=True,
            min_coverage=0.9,
            timeout=20,
            no_build=False,
        )

    def test_incremental_appends_new_dates(self) -> None:
        out = os.path.join(self.dir, "out")
        code = _run_incremental(FakeBS(), self._args(out))
        self.assertEqual(code, 0)
        panel = load_panel(out)
        self.assertEqual(panel.dates, OLD + NEW)
        self.assertEqual(len(panel.assets), 1)
        self.assertTrue(panel.has_point_in_time_universe())
        self.assertIn("incremental", panel.notes)
        self.assertTrue(panel.notes["incremental"])
        self.assertEqual(panel.notes["appended_price_rows"], 2)

    def test_already_latest_is_noop(self) -> None:
        out = os.path.join(self.dir, "out")
        code = _run_incremental(FakeBS(), self._args(out, end="2024-01-03"))
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(out, "manifest.json")))

    def test_out_equals_base_is_refused(self) -> None:
        code = _run_incremental(FakeBS(), self._args(self.base))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
