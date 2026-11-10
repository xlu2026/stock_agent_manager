"""Agent 1：量化策略研究与回测（手动触发、单次、不常驻）。

输入是任务书规定的四字段研究指令：

    {"question": "...", "universe": "沪深300", "period": "2020-01-02~2024-12-31",
     "factor_logic": "过去一年涨幅靠前的标的接下来一个月是否继续走强"}

链路：研究指令 -> 契约校验 -> 关键词表映射到因子 -> validate_strategy -> run_backtest
      -> 指标 + 实验 ID。

全部计算发生在 srq MCP 服务端的确定性引擎里，本模块只负责编排与落盘。
不含实盘下单能力：本文件不 import 任何券商客户端，也不存在下单函数。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .envelope import ROOT, envelope, rel, utc_now, write_json
from .mcp_client import McpClient, McpError
from quant.instruction import (
    InstructionError,
    looks_like_internal_spec,
    parse_instruction,
)

AGENT = "agent1-quant-research"
REPORT_DIR = os.path.join(ROOT, "output", "reports")


def _rejected(code: str, message: str, extra: dict | None = None) -> dict:
    return envelope(
        agent=AGENT,
        kind="quant.backtest",
        status="rejected",
        id_="rejected-" + utc_now().replace(":", ""),
        summary={"stage": "instruction_contract", "code": code, "message": message, **(extra or {})},
        compliance={"checked": True, "violations": [], "notes": ["拒绝执行，未产生任何回测"]},
        error=message,
    )


def run(instruction: dict, out_path: str | None = None) -> dict:
    """跑一次完整回测闭环，返回统一信封。"""
    # 1) 契约层：把自然语言研究意图翻译成 spec（映射表在代码里，不在提示词里）
    try:
        if looks_like_internal_spec(instruction):
            spec = instruction
            contract = {
                "kind": "internal_spec",
                "note": "直接使用内部 spec；未经四字段契约，复现时请确认来源",
            }
        else:
            parsed = parse_instruction(instruction)
            spec = parsed.to_spec()
            contract = {
                "kind": "phase1_contract/v1",
                "instruction": {
                    "question": parsed.question,
                    "universe_raw": instruction["universe"],
                    "period_raw": instruction["period"],
                    "factor_logic": parsed.factor_logic,
                },
                "mapping": parsed.mapping,
                "resolved": {"universe": parsed.universe, "start": parsed.start, "end": parsed.end, "factor": parsed.factor},
            }
    except InstructionError as exc:
        return _rejected(exc.code, str(exc), exc.extra)

    # 2) 工具层：只能通过 MCP 拿结果
    with McpClient() as client:
        tools = [t["name"] for t in client.list_tools()]
        for required in ("validate_strategy", "run_backtest"):
            if required not in tools:
                raise McpError(f"MCP 服务端缺少必需工具 {required}；实际工具：{tools}")

        validation = client.call("validate_strategy", {"spec": spec})
        if not validation.get("ok"):
            reasons = [c for c in validation["checks"] if c["status"] == "fail"]
            body = _rejected("VALIDATION_FAILED", "研究指令未通过静态校验", {"failures": reasons})
            body["summary"]["contract"] = contract
            return body

        result = client.call("run_backtest", {"spec": spec})

    experiment_id = result["experiment_id"]
    record_path = os.path.join(ROOT, "experiments", f"{experiment_id}.json")

    body = envelope(
        agent=AGENT,
        kind="quant.backtest",
        status="ok",
        id_=experiment_id,
        summary={
            "stage": "completed",
            "contract": contract,
            "factor": result["spec"]["factor"],
            "window": f"{result['spec']['start']}..{result['spec']['end']}",
            "rebalance": result["spec"]["rebalance"],
            "top_k": result["spec"]["top_k"],
            "cost_bps": result["spec"]["cost_bps"],
            "metrics": result["metrics"],
            "data_version": result["data_version"],
            "nav_hash": result["metrics"]["nav_hash"],
            "provenance": result["provenance"],
            "validation": {
                "verdict": validation["verdict"],
                "warns": [c for c in validation["checks"] if c["status"] == "warn"],
            },
        },
        artifacts=[
            {
                "type": "experiment_record",
                "path": rel(record_path),
                "exists": os.path.exists(record_path),
                "channel": "file",
                "media_id": None,
            }
        ],
        compliance={
            "checked": True,
            "violations": [],
            "notes": [
                "未产出个股推荐或买卖信号",
                "净值由确定性引擎计算，LLM 不参与盈亏",
                "因子选择由关键词映射表决定，不由模型决定",
                "数据为合成样本，非真实行情",
            ],
        },
    )
    body["summary"]["handoff_eligible"] = True  # 只标记资格；Phase 1 不触发任何下游

    if out_path:
        write_json(out_path, body)
        body["written_to"] = rel(out_path)
    return body


def main(argv: list[str] | None = None) -> int:
    from quant.console import force_utf8

    force_utf8()
    ap = argparse.ArgumentParser(prog="agent1", description="Agent 1 手动触发回测闭环")
    ap.add_argument("--instruction", required=True, help="四字段研究指令 JSON 文件")
    ap.add_argument("--out", help="信封输出路径")
    ap.add_argument("--json", action="store_true", help="只打印信封 JSON")
    args = ap.parse_args(argv)

    with open(args.instruction, encoding="utf-8-sig") as fh:
        instruction = json.load(fh)

    out = args.out or os.path.join(REPORT_DIR, "agent1-latest.json")
    env = run(instruction, out)
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0 if env["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
