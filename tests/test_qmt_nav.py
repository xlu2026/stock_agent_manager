"""QMT 日线导入与 NAV 对账测试。"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402
from scripts.compare_qmt_nav import compare, load_csv  # noqa: E402
from scripts.import_qmt_bars import build  # noqa: E402
from quant.deploy.qmt import render_qmt_bars_export  # noqa: E402

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]


def _base(path: str) -> None:
    prices = [
        {"date": d, "asset": a, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "adj_factor": 1.0}
        for d in DATES
        for a in ("AAA", "BBB")
    ]
    write_snapshot(
        path,
        Snapshot(
            universe="test",
            source="fixture",
            provider="fixture",
            adjust_mode="backward",
            prices=prices,
            calendar=[{"date": d} for d in DATES],
            universe_rows=[{"date": d, "asset": a} for d in DATES for a in ("AAA", "BBB")],
        ),
    )


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-qmtbars-")
        self.base = os.path.join(self.dir, "base")
        _base(self.base)
        self.bars = os.path.join(self.dir, "bars.csv")
        with open(self.bars, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "asset", "close"])
            for d in DATES:
                w.writerow([d, "AAA", 10])
                w.writerow([d, "BBB", 20])

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_build_snapshot(self) -> None:
        snap, base = build(self.bars, self.base)
        self.assertEqual(base, os.path.abspath(self.base))
        self.assertEqual(len(snap.prices), 6)
        self.assertEqual(snap.notes["price_construction"], "qmt_close_only")

    def test_bars_export_compiles(self) -> None:
        source = render_qmt_bars_export(["AAA", "BBB"], os.path.join(self.dir, "bars_out.csv"))
        compile(source, "<qmt-bars>", "exec")
        self.assertIn("get_history_data", source)


class NavTests(unittest.TestCase):
    def test_compare(self) -> None:
        qmt = {"2024-01-01": 1.0, "2024-01-02": 1.1, "2024-01-03": 1.2}
        eng = {"2024-01-01": 1.0, "2024-01-02": 1.05, "2024-01-03": 1.1}
        result = compare(qmt, eng)
        self.assertEqual(result["common_days"], 3)
        self.assertGreater(result["qmt_total"], result["engine_total"])
        self.assertGreater(result["daily_corr"], 0.9)

    def test_load_csv(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as fh:
            fh.write("date,net_value\n2024-01-01,1.0\n2024-01-02,1.1\n")
            path = fh.name
        try:
            self.assertEqual(load_csv(path), {"2024-01-01": 1.0, "2024-01-02": 1.1})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
