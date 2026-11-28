"""策略注册表、参数校验与旧 spec 兼容性测试。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.engine import run_backtest, run_factor_analysis  # noqa: E402
from quant.spec import SpecError, parse_spec  # noqa: E402
from quant.validate import validate_strategy  # noqa: E402
from quant import strategies  # noqa: E402

LEGACY = {
    "factor": "momentum_12_1",
    "universe": "synthetic_40",
    "start": "2020-01-02",
    "end": "2024-12-31",
    "rebalance": "M",
    "top_k": 8,
    "weighting": "equal",
    "cost_bps": 10.0,
    "seed": 42,
    "data_version": "dv-572bafec2a92",
}

MOMENTUM = {
    "strategy": "momentum_param",
    "params": {"lookback": 252, "skip": 21},
    "universe": "synthetic_40",
    "start": "2020-01-02",
    "end": "2021-12-31",
    "rebalance": "M",
    "top_k": 8,
    "cost_bps": 10,
}


class RegistryTests(unittest.TestCase):
    def test_builtins_registered(self) -> None:
        self.assertEqual(strategies.ids(), ["composite", "momentum_param", "single_factor"])

    def test_unknown_strategy_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**MOMENTUM, "strategy": "nope"})


class LegacyCompatibilityTests(unittest.TestCase):
    def test_legacy_canonical_has_no_strategy_fields(self) -> None:
        spec = parse_spec(LEGACY)
        canonical = spec.canonical()
        self.assertNotIn("strategy", canonical)
        self.assertNotIn("params", canonical)
        self.assertEqual(canonical["factor"], "momentum_12_1")

    def test_legacy_nav_hash_unchanged(self) -> None:
        """旧实验的回归锚：2026-11 之前的动量实验 nav_hash。"""
        bt = run_backtest(parse_spec(LEGACY))
        self.assertEqual(
            bt.metrics["nav_hash"],
            "fc5c9e778707e5f1280d1084c4018342aa4013a248e9aec2b3b2391b64a47f1a",
        )

    def test_factor_and_strategy_are_exclusive(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**MOMENTUM, "factor": "momentum_12_1"})


class ParamTests(unittest.TestCase):
    def test_required_data_declared(self) -> None:
        single = strategies.get("single_factor")
        self.assertIn("fundamentals", single.required_data({"factor": "value_proxy"}))
        self.assertNotIn("fundamentals", single.required_data({"factor": "momentum_12_1"}))
        comp = strategies.get("composite")
        self.assertIn("fundamentals", comp.required_data({"factors": {"momentum_12_1": 0.5, "quality_proxy": 0.5}}))

    def test_defaults_are_filled(self) -> None:
        spec = parse_spec({**MOMENTUM, "params": {}})
        self.assertEqual(spec.params, {"lookback": 252, "skip": 21})
        self.assertEqual(spec.strategy_version, "1.0")

    def test_unknown_param_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**MOMENTUM, "params": {"lookback": 252, "nope": 1}})

    def test_skip_must_be_less_than_lookback(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**MOMENTUM, "params": {"lookback": 60, "skip": 60}})

    def test_out_of_range_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec({**MOMENTUM, "params": {"lookback": 5}})

    def test_validate_uses_strategy_warmup(self) -> None:
        spec = parse_spec({**MOMENTUM, "start": "2019-01-02"})
        result = validate_strategy(spec)
        self.assertFalse(result["ok"])
        self.assertIn("factor.warmup", {c["id"] for c in result["checks"] if c["status"] == "fail"})

    def test_mcp_schema_lists_strategies(self) -> None:
        from quant.mcp_server import SPEC_SCHEMA

        self.assertIn("composite", SPEC_SCHEMA["properties"]["strategy"]["enum"])
        self.assertIn("params", SPEC_SCHEMA["properties"])


class CompositeTests(unittest.TestCase):
    def test_requires_two_factors(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec(
                {
                    "strategy": "composite",
                    "params": {"factors": {"momentum_12_1": 1.0}},
                    "universe": "synthetic_40",
                    "start": "2020-01-02",
                    "end": "2021-12-31",
                }
            )

    def test_unknown_factor_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec(
                {
                    "strategy": "composite",
                    "params": {"factors": {"momentum_12_1": 0.5, "magic": 0.5}},
                    "universe": "synthetic_40",
                    "start": "2020-01-02",
                    "end": "2021-12-31",
                }
            )

    def test_zero_sum_weights_rejected(self) -> None:
        with self.assertRaises(SpecError):
            parse_spec(
                {
                    "strategy": "composite",
                    "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": -0.5}},
                    "universe": "synthetic_40",
                    "start": "2020-01-02",
                    "end": "2021-12-31",
                }
            )

    def test_composite_runs(self) -> None:
        spec = parse_spec(
            {
                "strategy": "composite",
                "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5}},
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
                "top_k": 8,
                "cost_bps": 10,
            }
        )
        bt = run_backtest(spec)
        self.assertEqual(len(bt.metrics["nav_hash"]), 64)

    def test_composite_enhancements_run(self) -> None:
        spec = parse_spec(
            {
                "strategy": "composite",
                "params": {
                    "factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5},
                    "normalize": "rank",
                    "winsorize": 0.1,
                    "neutralize": "demean",
                },
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
                "top_k": 8,
                "cost_bps": 10,
            }
        )
        self.assertEqual(len(run_backtest(spec).metrics["nav_hash"]), 64)

    def test_composite_component_ic(self) -> None:
        spec = parse_spec(
            {
                "strategy": "composite",
                "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5}},
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
            }
        )
        result = run_factor_analysis(spec)
        self.assertIn("momentum_12_1", result["component_ic"])
        self.assertIn("low_vol_60d", result["component_ic"])

    def test_composite_factor_analysis_runs(self) -> None:
        spec = parse_spec(
            {
                "strategy": "composite",
                "params": {"factors": {"momentum_12_1": 0.5, "low_vol_60d": 0.5}},
                "universe": "synthetic_40",
                "start": "2020-01-02",
                "end": "2021-12-31",
            }
        )
        result = run_factor_analysis(spec)
        self.assertEqual(result["strategy"], "composite")
        self.assertIn("ic_mean", result)


if __name__ == "__main__":
    unittest.main()
