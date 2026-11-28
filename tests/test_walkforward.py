"""walk-forward 折划分测试。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.walkforward import baseline_spec, fixed_spec, grid_specs, make_folds, test_spec  # noqa: E402

CALENDAR = []
for year in range(2019, 2027):
    CALENDAR += [f"{year}-01-02", f"{year}-06-30", f"{year}-12-31"]


class FoldTests(unittest.TestCase):
    def test_make_folds(self) -> None:
        folds = make_folds(CALENDAR, "2020-03-02", 2023, 2025)
        self.assertEqual([f["test_year"] for f in folds], [2023, 2024, 2025])
        self.assertEqual(folds[0]["train_start"], "2020-03-02")
        self.assertEqual(folds[0]["train_end"], "2022-12-31")
        self.assertEqual(folds[1]["train_start"], "2021-01-02")

    def test_grid_and_specs(self) -> None:
        fold = make_folds(CALENDAR, "2020-03-02", 2023, 2023)[0]
        self.assertEqual(len(grid_specs(fold)), 9)
        fixed = fixed_spec(fold)
        self.assertEqual(fixed["top_k"], 8)
        self.assertEqual(fixed["params"]["factors"], {"momentum_12_1": 0.5, "low_vol_60d": 0.5})
        base = baseline_spec(fold)
        self.assertEqual(base["strategy"], "single_factor")
        winner = test_spec(fold, {"momentum_12_1": 0.7, "low_vol_60d": 0.3}, 5)
        self.assertEqual(winner["start"], fold["test_start"])


if __name__ == "__main__":
    unittest.main()
