"""实验记录持仓脱敏：公开记录不含代码，私有文件保留。"""
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

from quant import experiments as exp_store  # noqa: E402
from quant.engine import run_backtest  # noqa: E402
from quant.spec import parse_spec  # noqa: E402

SPEC = {
    "factor": "momentum_12_1",
    "universe": "synthetic_40",
    "start": "2020-01-02",
    "end": "2024-12-31",
    "rebalance": "M",
    "top_k": 8,
    "cost_bps": 10,
}


class RedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-redact-")
        self.old = os.environ.get("NFR_EXPERIMENTS_DIR")
        os.environ["NFR_EXPERIMENTS_DIR"] = self.dir

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("NFR_EXPERIMENTS_DIR", None)
        else:
            os.environ["NFR_EXPERIMENTS_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_public_record_has_no_symbols(self) -> None:
        bt = run_backtest(parse_spec(SPEC))
        exp_store.save(bt)
        public_path = os.path.join(self.dir, f"{bt.experiment_id}.json")
        with open(public_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn('"names"', text)
        self.assertNotIn("SYN", text)
        record = json.loads(text)
        self.assertTrue(record["holdings_redacted"])
        self.assertTrue(record["holdings"])
        self.assertNotIn("names", record["holdings"][0])

    def test_private_holdings_keep_symbols_and_are_readable(self) -> None:
        bt = run_backtest(parse_spec(SPEC))
        exp_store.save(bt)
        private_path = os.path.join(self.dir, ".private", f"{bt.experiment_id}.json")
        self.assertTrue(os.path.exists(private_path))
        with open(private_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertTrue(payload["holdings"][0]["names"])
        got = exp_store.get_experiment_holdings(bt.experiment_id)
        self.assertGreater(got["count"], 0)
        self.assertTrue(got["holdings"][0]["names"])
        one_day = exp_store.get_experiment_holdings(bt.experiment_id, bt.holdings[0]["date"])
        self.assertEqual(one_day["count"], 1)

    def test_public_get_experiment_omits_names(self) -> None:
        bt = run_backtest(parse_spec(SPEC))
        exp_store.save(bt)
        rec = exp_store.get_experiment(bt.experiment_id, include_series=True)
        self.assertNotIn("names", rec["holdings"][0])


if __name__ == "__main__":
    unittest.main()
