"""研究模式工具面 + run_research_instruction 校验 + 失败信封落盘。"""
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

from agents.agent1 import run as run_agent1  # noqa: E402
from quant.mcp_server import build_server  # noqa: E402

EXPERIMENTS = os.path.join(ROOT, "experiments")
BASE = {
    "question": "动量是否延续",
    "universe": "synthetic_40",
    "period": "2020-01-02~2024-12-31",
    "factor_logic": "过去 12 个月的动量：涨幅靠前的标的在接下来一个月是否延续强势",
}


class ToolsetTests(unittest.TestCase):
    def test_research_mode_hides_raw_spec_tools(self) -> None:
        names = {t["name"] for t in build_server("research").tools}
        self.assertIn("run_research_instruction", names)
        self.assertIn("run_research_factor_analysis", names)
        self.assertIn("run_research_paper_session", names)
        self.assertIn("get_experiment_holdings", names)
        self.assertNotIn("run_backtest", names)
        self.assertNotIn("validate_strategy", names)

    def test_full_mode_keeps_everything(self) -> None:
        names = {t["name"] for t in build_server("full").tools}
        self.assertIn("run_backtest", names)
        self.assertIn("validate_strategy", names)
        self.assertEqual(len(names), 14)

    def test_spec_schema_lists_real_universes(self) -> None:
        tool = next(t for t in build_server("full").tools if t["name"] == "run_backtest")
        enum = tool["inputSchema"]["properties"]["spec"]["properties"]["universe"]["enum"]
        self.assertIn("synthetic_40", enum)
        self.assertIn("hs300_40_pit", enum)

    def test_research_factor_analysis_accepts_quantiles(self) -> None:
        result = build_server("research").tool_map["run_research_factor_analysis"](
            {**BASE, "quantiles": 5}
        )
        self.assertEqual(result["factor"], "momentum_12_1")
        self.assertIn("ic_mean", result)


class ResearchValidationTests(unittest.TestCase):
    def test_insufficient_warmup_is_rejected_without_experiment(self) -> None:
        before = set(os.listdir(EXPERIMENTS))
        instruction = dict(BASE, period="2019-01-02~2024-12-31")
        result = build_server("research").tool_map["run_research_instruction"](instruction)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "validation")
        self.assertTrue(result["failures"])
        self.assertEqual(set(os.listdir(EXPERIMENTS)), before)


class RejectEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-a1-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_contract_error_writes_envelope(self) -> None:
        out = os.path.join(self.dir, "reject.json")
        body = run_agent1({"question": "缺字段"}, out)
        self.assertEqual(body["status"], "rejected")
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["status"], "rejected")
        self.assertTrue(body.get("written_to"))

    def test_validation_error_writes_envelope(self) -> None:
        out = os.path.join(self.dir, "validation.json")
        body = run_agent1(dict(BASE, period="2019-01-02~2024-12-31"), out)
        self.assertEqual(body["status"], "rejected")
        self.assertEqual(body["summary"]["code"], "VALIDATION_FAILED")
        self.assertTrue(os.path.exists(out))


class InternalSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-internal-")
        self.old = os.environ.get("NFR_EXPERIMENTS_DIR")
        os.environ["NFR_EXPERIMENTS_DIR"] = os.path.join(self.dir, "experiments")

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("NFR_EXPERIMENTS_DIR", None)
        else:
            os.environ["NFR_EXPERIMENTS_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_raw_spec_rejected_without_flag(self) -> None:
        spec = {
            "factor": "momentum_12_1",
            "universe": "synthetic_40",
            "start": "2020-01-02",
            "end": "2024-12-31",
            "rebalance": "M",
            "top_k": 8,
            "cost_bps": 10,
        }
        out = os.path.join(self.dir, "rejected.json")
        body = run_agent1(spec, out)
        self.assertEqual(body["status"], "rejected")
        self.assertTrue(os.path.exists(out))

    def test_raw_spec_allowed_with_explicit_flag(self) -> None:
        spec = {
            "factor": "momentum_12_1",
            "universe": "synthetic_40",
            "start": "2020-01-02",
            "end": "2024-12-31",
            "rebalance": "M",
            "top_k": 8,
            "cost_bps": 10,
        }
        out = os.path.join(self.dir, "internal.json")
        body = run_agent1(spec, out, internal_spec=True)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["summary"]["contract"]["kind"], "internal_spec")


if __name__ == "__main__":
    unittest.main()
