"""实验对照表测试。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.compare_experiments import build  # noqa: E402


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-compare-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name: str, cagr: float) -> str:
        path = os.path.join(self.dir, name)
        payload = {
            "status": "ok",
            "id": name,
            "summary": {
                "strategy": "composite",
                "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5}},
                "metrics": {"cagr": cagr, "sharpe": 0.1, "max_drawdown": -0.2, "excess_cagr": 0.01, "annual_turnover": 2.0},
                "contract": {"resolved": {"start": "2021-01-04", "end": "2026-11-11"}},
            },
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_sorted_by_cagr(self) -> None:
        result = build([self._write("a.json", -0.1), self._write("b.json", 0.2)])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["rows"][0]["cagr"], 0.2)


if __name__ == "__main__":
    unittest.main()
