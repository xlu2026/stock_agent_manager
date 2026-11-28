"""组合构造器与权重方案的测试。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.data import load_panel  # noqa: E402
from quant.engine import run_backtest  # noqa: E402
from quant.portfolio import construct  # noqa: E402
from quant.spec import parse_spec  # noqa: E402

BASE = {
    "factor": "momentum_12_1",
    "universe": "synthetic_40",
    "start": "2020-01-02",
    "end": "2021-12-31",
    "rebalance": "M",
    "top_k": 8,
    "cost_bps": 10,
    "seed": 42,
}


class ConstructTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel = load_panel()
        cls.assets = cls.panel.assets[:4]
        cls.i = min(300, len(cls.panel.dates) - 1)

    def test_equal_is_exact(self) -> None:
        w = construct(self.panel, self.assets, {}, self.i, "equal")
        self.assertEqual(w, {a: 0.25 for a in self.assets})

    def test_score_weights_sum_to_one_and_tilt(self) -> None:
        scores = {a: float(j + 1) for j, a in enumerate(self.assets)}
        w = construct(self.panel, self.assets, scores, self.i, "score")
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertGreater(w[self.assets[-1]], w[self.assets[0]])

    def test_inverse_vol_cap(self) -> None:
        w = construct(self.panel, self.assets, {}, self.i, "inverse_vol")
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertLessEqual(max(w.values()), 0.2500001)

    def test_vol_target_never_levers(self) -> None:
        w = construct(self.panel, self.assets, {}, self.i, "vol_target")
        self.assertGreater(sum(w.values()), 0.0)
        self.assertLessEqual(sum(w.values()), 1.0)


class WeightingEngineTests(unittest.TestCase):
    def test_new_weighting_changes_nav_but_equal_is_baseline(self) -> None:
        equal = run_backtest(parse_spec(BASE))
        score = run_backtest(parse_spec({**BASE, "weighting": "score"}))
        self.assertEqual(equal.spec.canonical()["weighting"], "equal")
        self.assertNotEqual(equal.metrics["nav_hash"], score.metrics["nav_hash"])


if __name__ == "__main__":
    unittest.main()
