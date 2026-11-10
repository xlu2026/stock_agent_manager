"""数据契约与快照体检的测试。

用一份手工构造的小快照覆盖"干净数据"和五种脏数据：
价格非法、重复行、指纹不符、财报公告日倒挂、面板缺口过大。
"""
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
from quant.providers.snapshot_check import check_snapshot  # noqa: E402

DATES = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
ASSETS = ["SYN001", "SYN002"]


def clean_snapshot() -> Snapshot:
    prices = []
    for d in DATES:
        for a in ASSETS:
            prices.append(
                {
                    "date": d,
                    "asset": a,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.2,
                    "volume": 1000,
                    "adj_factor": 1.0,
                }
            )
    return Snapshot(
        universe="synthetic_40",
        source="unit-test",
        provider="fixture",
        adjust_mode="backward",
        prices=prices,
        calendar=[{"date": d} for d in DATES],
        fundamentals=[
            {
                "asset": "SYN001",
                "report_date": "2023-12-31",
                "available_date": "2024-03-30",
                "book": 100.0,
                "earnings": 10.0,
            }
        ],
        universe_rows=[{"date": d, "asset": a} for d in DATES for a in ASSETS],
        notes={"suspended_filled": 0},
    )


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-snap-")
        write_snapshot(self.dir, clean_snapshot())

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _rewrite_prices(self, rows) -> None:
        path = os.path.join(self.dir, "prices.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    def _rewrite_manifest(self, mutate) -> None:
        path = os.path.join(self.dir, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        mutate(manifest)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)

    def test_clean_snapshot_passes(self) -> None:
        result = check_snapshot(self.dir)
        self.assertTrue(result["ok"], [c for c in result["checks"] if c["status"] == "fail"])
        self.assertEqual(result["stats"]["assets"], 2)
        self.assertEqual(result["stats"]["dates"], 5)

    def test_negative_price_fails(self) -> None:
        rows = [
            {"date": d, "asset": a, "open": -1.0, "high": 0.5, "low": -2.0, "close": 0.2, "volume": 0, "adj_factor": 1.0}
            for d in DATES
            for a in ASSETS
        ]
        self._rewrite_prices(rows)
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        ids = {c["id"] for c in result["checks"] if c["status"] == "fail"}
        self.assertIn("prices.values", ids)

    def test_duplicate_rows_fail(self) -> None:
        snap = clean_snapshot()
        snap.prices.append(dict(snap.prices[0]))
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        write_snapshot(self.dir, snap)
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        self.assertIn("prices.duplicates", {c["id"] for c in result["checks"] if c["status"] == "fail"})

    def test_hash_mismatch_fails(self) -> None:
        rows = [
            {"date": d, "asset": a, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.3, "volume": 1000, "adj_factor": 1.0}
            for d in DATES
            for a in ASSETS
        ]
        self._rewrite_prices(rows)  # 改了数据但没更新 manifest
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        self.assertIn("manifest.files", {c["id"] for c in result["checks"] if c["status"] == "fail"})

    def test_fundamental_announced_before_report_fails(self) -> None:
        snap = clean_snapshot()
        snap.fundamentals[0]["available_date"] = "2023-01-01"  # 公告日早于报告期
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        write_snapshot(self.dir, snap)
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        self.assertIn("fundamentals.availability", {c["id"] for c in result["checks"] if c["status"] == "fail"})

    def test_large_coverage_hole_fails(self) -> None:
        snap = clean_snapshot()
        # 只剩一个日期，缺失 80%
        snap.prices = [p for p in snap.prices if p["date"] == DATES[0]]
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        write_snapshot(self.dir, snap)
        result = check_snapshot(self.dir)
        self.assertFalse(result["ok"])
        self.assertIn("prices.coverage", {c["id"] for c in result["checks"] if c["status"] == "fail"})

    def test_manifest_records_notes_and_adjust(self) -> None:
        with open(os.path.join(self.dir, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["adjust_mode"], "backward")
        self.assertEqual(manifest["schema_version"], 2)
        self.assertIn("notes", manifest)
        self.assertIn("prices.csv", manifest["files"])


if __name__ == "__main__":
    unittest.main()
