"""量化内核的回归测试：确定性、前视偏差、spec 校验、实验登记。

    python -m unittest discover -s tests -v
"""
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
os.chdir(ROOT)

from quant import experiments as exp_store
from quant.data import load_panel
from quant.engine import run_backtest
from quant.spec import SpecError, parse_spec
from quant.validate import validate_strategy

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


class SpecTests(unittest.TestCase):
    def test_unknown_field_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**BASE, "live_submit_order": True})

    def test_unknown_factor_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**BASE, "factor": "magic"})

    def test_start_after_end_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**BASE, "start": "2022-01-01", "end": "2021-01-01"})

    def test_zero_cost_fails_validation(self) -> None:
        result = validate_strategy({**BASE, "cost_bps": 0})
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "rejected")

    def test_valid_spec_accepted(self) -> None:
        result = validate_strategy(BASE)
        self.assertTrue(result["ok"], result)
        self.assertFalse(
            [c for c in result["checks"] if c["status"] == "fail"],
        )


class DeterminismTests(unittest.TestCase):
    def test_same_spec_same_nav_hash(self) -> None:
        spec = parse_spec(BASE)
        a = run_backtest(spec)
        b = run_backtest(spec)
        self.assertEqual(a.metrics["nav_hash"], b.metrics["nav_hash"])
        self.assertEqual(a.nav, b.nav)
        self.assertEqual(a.experiment_id, b.experiment_id)

    def test_different_window_different_id(self) -> None:
        a = run_backtest(parse_spec(BASE))
        b = run_backtest(parse_spec({**BASE, "end": "2021-06-30"}))
        self.assertNotEqual(a.experiment_id, b.experiment_id)

    def test_pinned_data_version_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_backtest(parse_spec({**BASE, "data_version": "dv-deadbeef0000"}))


class LookaheadTests(unittest.TestCase):
    def test_signal_is_strictly_before_fill(self) -> None:
        bt = run_backtest(parse_spec(BASE))
        panel = load_panel()
        idx = {d: i for i, d in enumerate(panel.dates)}
        self.assertTrue(bt.holdings)
        for h in bt.holdings:
            self.assertLess(idx[h["signal_date"]], idx[h["date"]])
            self.assertEqual(idx[h["date"]] - idx[h["signal_date"]], 1)


class MetricsTests(unittest.TestCase):
    def test_metric_sanity(self) -> None:
        bt = run_backtest(parse_spec(BASE))
        m = bt.metrics
        for key in ("total_return", "cagr", "annual_volatility", "sharpe", "max_drawdown", "nav_hash"):
            self.assertIn(key, m)
        self.assertLessEqual(m["max_drawdown"], 0.0)
        self.assertEqual(m["trading_days"], len(bt.nav))
        self.assertGreater(m["sharpe"], -10)
        self.assertGreater(len(m["nav_hash"]), 32)


class ExperimentStoreTests(unittest.TestCase):
    """测试写临时目录，避免污染真实的 experiments/ 记录。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="nfr-exp-")
        cls._old = os.environ.get("NFR_EXPERIMENTS_DIR")
        os.environ["NFR_EXPERIMENTS_DIR"] = cls._tmp

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old is None:
            os.environ.pop("NFR_EXPERIMENTS_DIR", None)
        else:
            os.environ["NFR_EXPERIMENTS_DIR"] = cls._old
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_roundtrip_and_traversal_guard(self) -> None:
        bt = run_backtest(parse_spec(BASE))
        rec = exp_store.save(bt)
        self.assertEqual(rec["experiment_id"], bt.experiment_id)
        got = exp_store.get_experiment(bt.experiment_id, include_series=False)
        self.assertEqual(got["metrics"]["nav_hash"], bt.metrics["nav_hash"])
        with self.assertRaises(ValueError):
            exp_store.get_experiment("../secrets")

    def test_missing_experiment_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            exp_store.get_experiment("exp-000000000000")


class DataFingerprintTests(unittest.TestCase):
    def test_panel_hash_matches_manifest(self) -> None:
        panel = load_panel()
        with open(os.path.join("quant", "data", "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(panel.data_sha256, manifest["sha256"])
        self.assertEqual(len(panel.assets), 40)
        self.assertGreater(len(panel.dates), 1500)


if __name__ == "__main__":
    unittest.main()
