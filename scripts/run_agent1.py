"""Agent 1 的 Python 入口脚本（任务书 3.2 要求的"入口脚本"）。

    python scripts/run_agent1.py --instruction research.json
    python scripts/run_agent1.py --question "..." --universe synthetic_40 \
        --period "2020-01-02~2024-12-31" --factor_logic "过去一年涨得多的标的会继续走强吗"

研究指令契约（Phase 1）：
    question      研究问题描述（只做记录与追溯，不参与计算）
    universe      标的池
    period        起止日期
    factor_logic  待检验的因子逻辑（自然语言，由关键词表映射为引擎因子）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.agent1 import run  # noqa: E402
from agents.envelope import rel, write_json  # noqa: E402
from quant.console import force_utf8  # noqa: E402

REPORTS = os.path.join(ROOT, "output", "reports")


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="Agent 1：结构化研究指令 -> 回测 -> 指标 + 实验 ID")
    ap.add_argument("--instruction", help="四字段研究指令 JSON 文件")
    ap.add_argument("--question")
    ap.add_argument("--universe")
    ap.add_argument("--period")
    ap.add_argument("--factor_logic", "--factor-logic", dest="factor_logic")
    ap.add_argument("--out", help="信封输出路径")
    args = ap.parse_args(argv)

    if args.instruction:
        with open(args.instruction, encoding="utf-8-sig") as fh:
            instruction = json.load(fh)
    else:
        missing = [k for k in ("question", "universe", "period", "factor_logic") if not getattr(args, k)]
        if missing:
            ap.error(f"缺少参数 {missing}；也可以直接用 --instruction 传 JSON 文件")
        instruction = {
            "question": args.question,
            "universe": args.universe,
            "period": args.period,
            "factor_logic": args.factor_logic,
        }

    out = args.out or os.path.join(REPORTS, "agent1_latest.json")
    env = run(instruction, out)
    print(json.dumps(env, ensure_ascii=False, indent=2))
    print(f"\n信封已写入 {rel(out)}" if out else "", file=sys.stderr)
    return 0 if env["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
