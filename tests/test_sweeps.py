"""参数网格与多重检验的纯函数测试。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.sweeps import bh_qvalues, expand_grid, sharpe_pvalue, summarize  # noqa: E402


class GridTests(unittest.TestCase):
    def test_expand_grid_cartesian(self) -> None:
        specs = expand_grid(
            {"strategy": "momentum_param", "params": {"lookback": 252}},
            {"params.lookback": [60, 120], "params.skip": [5, 10]},
        )
        self.assertEqual(len(specs), 4)
        self.assertEqual(
            {(s["params"]["lookback"], s["params"]["skip"]) for s in specs},
            {(60, 5), (60, 10), (120, 5), (120, 10)},
        )


class MultipleTestingTests(unittest.TestCase):
    def test_bh_constant_example(self) -> None:
        q = bh_qvalues([0.01, 0.02, 0.03, 0.04])
        self.assertEqual(len(q), 4)
        self.assertTrue(all(abs(x - 0.04) < 1e-9 for x in q))

    def test_sharpe_pvalue_decreases(self) -> None:
        self.assertLess(sharpe_pvalue(1.0, 5), sharpe_pvalue(0.0, 5))

    def test_summarize_marks_trials(self) -> None:
        rows = [
            {"name": "a", "experiment_id": "e1", "metrics": {"cagr": 0.1, "sharpe": 1.0, "trading_days": 756, "max_drawdown": -0.1}},
            {"name": "b", "experiment_id": "e2", "metrics": {"cagr": -0.1, "sharpe": -1.0, "trading_days": 756, "max_drawdown": -0.3}},
        ]
        summary = summarize(rows)
        self.assertEqual(summary["n_trials"], 2)
        self.assertEqual(summary["best"]["name"], "a")
        self.assertIn("bh_q", summary["rows"][0])


if __name__ == "__main__":
    unittest.main()
