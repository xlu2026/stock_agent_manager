"""QMT 策略渲染/投递测试：只验证文件，不连接 QMT、不下单。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.deploy.qmt import (  # noqa: E402
    QmtDeployError,
    load_account_config,
    rebalance_dates,
    render_qmt_strategy,
    stage_qmt_strategy,
    universe_changes,
)
from quant.spec import parse_spec  # noqa: E402

ASSETS = ["600000.SH", "000001.SZ", "600519.SH", "000333.SZ"]


def _spec(**extra):
    return parse_spec(
        {
            "factor": "momentum_12_1",
            "universe": "synthetic_40",
            "start": "2020-01-02",
            "end": "2021-12-31",
            "top_k": 2,
            **extra,
        }
    )


class ConfigTests(unittest.TestCase):
    def test_missing_config_is_empty(self) -> None:
        self.assertEqual(load_account_config("/definitely/not/here.json"), {})

    def test_config_is_embedded_as_runtime_path(self) -> None:
        path = os.path.join(tempfile.gettempdir(), "nfr-qmt-config-test.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"account_id": "TEST_ACCOUNT_ID"}')
        source = render_qmt_strategy(_spec(), ASSETS, account_id="fallback", config_path=path)
        self.assertIn("_load_account", source)
        self.assertIn("CONFIG_PATH", source)
        self.assertEqual(load_account_config(path)["account_id"], "TEST_ACCOUNT_ID")


class AlignmentHelperTests(unittest.TestCase):
    def test_rebalance_dates_are_period_ends(self) -> None:
        dates = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-29"]
        self.assertEqual(
            rebalance_dates(dates, "2024-01-01", "2024-02-29", "M"),
            ["2024-01-31", "2024-02-29"],
        )

    def test_universe_changes_compress(self) -> None:
        rows = [
            {"date": "2024-01-01", "asset": "A"},
            {"date": "2024-01-02", "asset": "A"},
            {"date": "2024-02-01", "asset": "A"},
            {"date": "2024-02-01", "asset": "B"},
        ]
        self.assertEqual(
            universe_changes(rows),
            [("2024-01-01", ["A"]), ("2024-02-01", ["A", "B"])],
        )

    def test_members_use_effective_date(self) -> None:
        source = render_qmt_strategy(
            _spec(),
            ASSETS,
            universe_changes=[("2024-01-01", ["600000.SH"]), ("2024-02-01", ["000001.SZ"])],
            rebalance_dates=["2024-01-31"],
        )
        ns = {}
        exec(source, ns)
        self.assertEqual(ns["_members"]("2024-01-15"), ["600000.SH"])
        self.assertEqual(ns["_members"]("2024-02-15"), ["000001.SZ"])


class RenderTests(unittest.TestCase):
    def test_momentum_renders_valid_python(self) -> None:
        source = render_qmt_strategy(_spec(), ASSETS, account_id="test-account")
        compile(source, "<qmt>", "exec")
        self.assertIn("order_shares", source)
        self.assertIn("ACCOUNT_ID = 'test-account'", source)
        self.assertIn("600000.SH", source)
        self.assertIn("#coding:gbk", source)

    def test_momentum_param_renders(self) -> None:
        spec = parse_spec(
            {
                "strategy": "momentum_param",
                "params": {"lookback": 120, "skip": 10},
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
                "top_k": 2,
            }
        )
        compile(render_qmt_strategy(spec, ASSETS), "<qmt>", "exec")

    def test_paper_mode_is_dynamic_and_appends_nav(self) -> None:
        source = render_qmt_strategy(
            _spec(),
            ASSETS,
            rebalance_dates=["2024-01-31"],
            nav_path=os.path.join(tempfile.gettempdir(), "nfr_paper_nav.csv"),
            paper=True,
        )
        ns = {}
        exec(source, ns)
        self.assertTrue(ns["PAPER"])
        self.assertEqual(ns["REBALANCE_DATES"], [])
        self.assertIn("STATE_PATH", source)
        self.assertIn("os.path.exists(NAV_PATH)", source)
        compile(source, "<qmt-paper>", "exec")

    def test_invalid_history_is_filtered_and_signal_is_prior_bar(self) -> None:
        source = render_qmt_strategy(
            _spec(), ASSETS, asset_first_dates={a: "2022-01-01" for a in ASSETS}
        )
        ns = {}
        exec(source, ns)
        self.assertFalse(ns["_valid"]([0.0] * 260, 253))
        self.assertIsNone(ns["_factor_value"]("momentum_12_1", [0.0] * 260))
        self.assertIn("signal_closes", source)
        self.assertEqual(ns["_scores"]({a: [1.0] * 300 for a in ASSETS}, "2021-01-01"), {})

    def test_composite_renders(self) -> None:
        spec = parse_spec(
            {
                "strategy": "composite",
                "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5}},
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
                "top_k": 2,
            }
        )
        compile(render_qmt_strategy(spec, ASSETS), "<qmt>", "exec")

    def test_value_factor_rejected(self) -> None:
        spec = parse_spec(
            {
                "factor": "value_proxy",
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
            }
        )
        with self.assertRaises(QmtDeployError):
            render_qmt_strategy(spec, ASSETS)

    def test_vol_target_rejected(self) -> None:
        spec = parse_spec(
            {
                "factor": "momentum_12_1",
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
                "weighting": "vol_target",
            }
        )
        with self.assertRaises(QmtDeployError):
            render_qmt_strategy(spec, ASSETS)


class StageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-qmt-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_stage_writes_gbk_and_audit(self) -> None:
        result = stage_qmt_strategy(_spec(), ASSETS, "test-account", self.dir, name="demo")
        self.assertTrue(os.path.exists(result["source"]))
        self.assertTrue(os.path.exists(result["audit"]))
        with open(result["source"], "rb") as fh:
            data = fh.read()
        self.assertIn("order_shares".encode("ascii"), data)
        self.assertIn("test-account".encode("ascii"), data)

    def test_overwrite_requires_force(self) -> None:
        stage_qmt_strategy(_spec(), ASSETS, "test-account", self.dir, name="demo")
        with self.assertRaises(QmtDeployError):
            stage_qmt_strategy(_spec(), ASSETS, "test-account", self.dir, name="demo")
        stage_qmt_strategy(_spec(), ASSETS, "test-account", self.dir, name="demo", force=True)


if __name__ == "__main__":
    unittest.main()
