"""四字段研究指令契约的测试（任务书 3.2 的输入格式）。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.instruction import (  # noqa: E402
    InstructionError,
    parse_instruction,
    parse_period,
    resolve_factor,
)

BASE = {
    "question": "过去一年涨得多的标的是否会继续走强",
    "universe": "synthetic_40",
    "period": "2020-01-02~2024-12-31",
    "factor_logic": "过去一年涨幅靠前的标的，接下来一个月是否继续走强（动量延续）",
}


class PeriodTests(unittest.TestCase):
    def test_variants(self) -> None:
        for period in (
            "2020-01-02~2024-12-31",
            "2020-01-02 至 2024-12-31",
            "2020/01/02..2024/12/31",
            "2020.01.02 - 2024.12.31",
        ):
            self.assertEqual(parse_period(period), ("2020-01-02", "2024-12-31"), period)

    def test_single_date_rejected(self) -> None:
        with self.assertRaises(InstructionError) as ctx:
            parse_period("2020-01-02")
        self.assertEqual(ctx.exception.code, "BAD_PERIOD")


class FactorMappingTests(unittest.TestCase):
    def test_keyword_mapping(self) -> None:
        cases = {
            "动量延续": "momentum_12_1",
            "估值便宜、账面价值高": "value_proxy",
            "波动低、回撤小": "low_vol_60d",
            "盈利质量高、ROE 稳定": "quality_proxy",
        }
        for text, factor in cases.items():
            got, detail = resolve_factor(text)
            self.assertEqual(got, factor, text)
            self.assertEqual(detail["source"], "keyword_table")

    def test_ambiguous_rejected(self) -> None:
        with self.assertRaises(InstructionError) as ctx:
            resolve_factor("低波动且估值便宜")
        self.assertEqual(ctx.exception.code, "FACTOR_AMBIGUOUS")

    def test_unmapped_rejected(self) -> None:
        with self.assertRaises(InstructionError) as ctx:
            resolve_factor("看图形像不像一只蝴蝶")
        self.assertEqual(ctx.exception.code, "FACTOR_UNMAPPED")


class ContractTests(unittest.TestCase):
    def test_valid_instruction(self) -> None:
        ins = parse_instruction(BASE)
        self.assertEqual(ins.factor, "momentum_12_1")
        self.assertEqual(ins.start, "2020-01-02")
        self.assertEqual(ins.universe, "synthetic_40")
        spec = ins.to_spec()
        self.assertEqual(set(spec), {"factor", "universe", "start", "end"})

    def test_overrides_allowed(self) -> None:
        spec = parse_instruction({**BASE, "top_k": 5, "cost_bps": 20}).to_spec()
        self.assertEqual(spec["top_k"], 5)
        self.assertEqual(spec["cost_bps"], 20)

    def test_missing_field(self) -> None:
        raw = dict(BASE)
        raw.pop("factor_logic")
        with self.assertRaises(InstructionError) as ctx:
            parse_instruction(raw)
        self.assertEqual(ctx.exception.code, "MISSING_FIELDS")

    def test_unknown_field(self) -> None:
        with self.assertRaises(InstructionError) as ctx:
            parse_instruction({**BASE, "live_submit_order": True})
        self.assertEqual(ctx.exception.code, "UNKNOWN_FIELDS")

    def test_universe_unavailable_is_honest(self) -> None:
        with self.assertRaises(InstructionError) as ctx:
            parse_instruction({**BASE, "universe": "沪深300"})
        self.assertEqual(ctx.exception.code, "UNIVERSE_UNAVAILABLE")
        self.assertIn("synthetic_40", ctx.exception.extra["available"])


if __name__ == "__main__":
    unittest.main()
