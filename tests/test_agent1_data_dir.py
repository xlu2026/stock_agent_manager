"""Agent 1 的 data_dir 传递与环境恢复（不真的起 MCP 服务端）。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import agents.agent1 as agent1  # noqa: E402
from quant.data import DATA_DIR_ENV  # noqa: E402

INSTRUCTION = {
    "question": "动量是否延续",
    "universe": "synthetic_40",
    "period": "2020-01-02~2024-12-31",
    "factor_logic": "过去一年动量靠前的标的，接下来一个月是否继续走强",
}

BACKTEST_RESULT = {
    "experiment_id": "exp-test0000000",
    "status": "completed",
    "spec": {
        "factor": "momentum_12_1",
        "start": "2020-01-02",
        "end": "2024-12-31",
        "rebalance": "M",
        "top_k": 8,
        "cost_bps": 10.0,
    },
    "metrics": {"nav_hash": "x" * 64, "cagr": 0.1, "sharpe": 1.0},
    "data_version": "dv-test",
    "provenance": {"data_source": "baostock via SmartX python"},
}


class FakeClient:
    captured: dict = {}

    def __enter__(self):
        FakeClient.captured["data_dir"] = os.environ.get(DATA_DIR_ENV)
        return self

    def __exit__(self, *exc):
        return False

    def list_tools(self):
        return [
            {"name": "run_research_instruction"},
            {"name": "validate_strategy"},
            {"name": "run_backtest"},
        ]

    def call(self, name, args):
        if name == "validate_strategy":
            return {"ok": True, "verdict": "accepted", "checks": []}
        if name == "run_research_instruction":
            return {
                "ok": True,
                "contract": {
                    "kind": "phase1_contract/v1",
                    "mapping": {"matched": ["momentum_12_1"], "source": "keyword_table"},
                    "validation": {"verdict": "accepted", "checks": []},
                },
                **BACKTEST_RESULT,
            }
        return dict(BACKTEST_RESULT)


class Agent1DataDirTests(unittest.TestCase):
    def _run(self, data_dir):
        FakeClient.captured = {}
        with mock.patch.object(agent1, "McpClient", lambda: FakeClient()):
            return agent1.run(INSTRUCTION, data_dir=data_dir)

    def test_data_dir_is_passed_to_mcp_process(self) -> None:
        previous = os.environ.get(DATA_DIR_ENV)
        try:
            body = self._run(r"C:\data\real40_pit")
            self.assertEqual(body["status"], "ok")
            self.assertEqual(FakeClient.captured["data_dir"], os.path.abspath(r"C:\data\real40_pit"))
            self.assertEqual(os.environ.get(DATA_DIR_ENV), previous)
        finally:
            if previous is None:
                os.environ.pop(DATA_DIR_ENV, None)
            else:
                os.environ[DATA_DIR_ENV] = previous

    def test_without_data_dir_env_is_untouched(self) -> None:
        previous = os.environ.get(DATA_DIR_ENV)
        try:
            body = self._run(None)
            self.assertEqual(body["status"], "ok")
            self.assertIsNone(FakeClient.captured["data_dir"])
        finally:
            if previous is None:
                os.environ.pop(DATA_DIR_ENV, None)
            else:
                os.environ[DATA_DIR_ENV] = previous


if __name__ == "__main__":
    unittest.main()
