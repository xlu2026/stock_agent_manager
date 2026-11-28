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
from quant.data import DATA_DIR_ENV
from quant.instruction import looks_like_internal_spec

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


def _finish(body: dict, out_path: str | None) -> dict:
    """成功和拒绝都要落盘：失败实验也要能追溯。"""
    if out_path:
        write_json(out_path, body)
        body["written_to"] = rel(out_path)
    return body


def run(
    instruction: dict,
    out_path: str | None = None,
    data_dir: str | None = None,
    internal_spec: bool = False,
) -> dict:
    """跑一次完整回测闭环，返回统一信封。

    ``data_dir`` 指向快照目录（等价于设 ``NFR_DATA_DIR``）；不传就用仓库默认的合成样本。
    正常路径把四字段指令原样交给 MCP 的 ``run_research_instruction``，契约解析、因子映射、
    静态校验全在服务端完成；``internal_spec=True`` 才允许直接传内部 spec（诊断用，需显式开启）。
    """
    spec = None
    contract = None
    validation = {"verdict": "accepted", "checks": []}

    if internal_spec:
        if not looks_like_internal_spec(instruction):
            return _finish(
                _rejected("INTERNAL_SPEC_REQUIRED", "internal_spec=True 需要包含 factor 的原始 spec"),
                out_path,
            )
        spec = instruction
        contract = {
            "kind": "internal_spec",
            "note": "直接使用内部 spec；未经四字段契约，复现时请确认来源",
        }
        mode = "internal"
    else:
        mode = "research"

    # 工具层：只能通过 MCP 拿结果
    previous_data_dir = os.environ.get(DATA_DIR_ENV)
    if data_dir:
        os.environ[DATA_DIR_ENV] = os.path.abspath(data_dir)
    try:
        with McpClient() as client:
            tools = [t["name"] for t in client.list_tools()]
            if mode == "internal":
                for required in ("validate_strategy", "run_backtest"):
                    if required not in tools:
                        raise McpError(f"MCP 服务端缺少必需工具 {required}；实际工具：{tools}")
                validation = client.call("validate_strategy", {"spec": spec})
                if not validation.get("ok"):
                    reasons = [c for c in validation["checks"] if c["status"] == "fail"]
                    body = _rejected("VALIDATION_FAILED", "研究指令未通过静态校验", {"failures": reasons})
                    body["summary"]["contract"] = contract
                    return _finish(body, out_path)
                result = client.call("run_backtest", {"spec": spec})
            else:
                if "run_research_instruction" not in tools:
                    raise McpError(f"MCP 服务端缺少必需工具 run_research_instruction；实际工具：{tools}")
                result = client.call("run_research_instruction", instruction)
                if result.get("ok") is False:
                    if result.get("stage") == "contract":
                        body = _rejected(
                            result.get("code", "INSTRUCTION_ERROR"),
                            result.get("message", "研究指令不合法"),
                            result.get("extra"),
                        )
                    else:
                        body = _rejected(
                            "VALIDATION_FAILED",
                            "研究指令未通过静态校验",
                            {"failures": result.get("failures", [])},
                        )
                        body["summary"]["contract"] = result.get("contract")
                    return _finish(body, out_path)
                contract = result.get("contract") or {}
                validation = contract.get("validation") or {"verdict": "accepted", "checks": []}
    except McpError as exc:
        # 池名与快照不匹配、数据版本不一致等，都会以工具错误的形式回来
        return _finish(_rejected("MCP_TOOL_ERROR", str(exc)), out_path)
    finally:
        if data_dir:
            if previous_data_dir is None:
                os.environ.pop(DATA_DIR_ENV, None)
            else:
                os.environ[DATA_DIR_ENV] = previous_data_dir

    experiment_id = result["experiment_id"]
    record_path = os.path.join(ROOT, "experiments", f"{experiment_id}.json")

    data_source = str((result.get("provenance") or {}).get("data_source") or "unknown")
    if "synthetic" in data_source.lower():
        data_note = "数据为合成样本，非真实行情"
    else:
        data_note = f"数据来源 {data_source}；真实数据仍受样本与口径限制"

    body = envelope(
        agent=AGENT,
        kind="quant.backtest",
        status="ok",
        id_=experiment_id,
        summary={
            "stage": "completed",
            "contract": contract,
            "strategy": result["spec"].get("strategy", "single_factor"),
            "params": result["spec"].get("params", {}),
            "factor": result["spec"].get("factor"),
            "window": f"{result['spec']['start']}..{result['spec']['end']}",
            "rebalance": result["spec"]["rebalance"],
            "top_k": result["spec"]["top_k"],
            "cost_bps": result["spec"]["cost_bps"],
            "metrics": result["metrics"],
            "data_version": result["data_version"],
            "nav_hash": result["metrics"]["nav_hash"],
            "provenance": result["provenance"],
            "validation": {
                "verdict": validation.get("verdict", "accepted"),
                "warns": [c for c in validation.get("checks", []) if c.get("status") == "warn"],
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
                data_note,
            ],
        },
    )
    body["summary"]["handoff_eligible"] = True  # 只标记资格；Phase 1 不触发任何下游
    return _finish(body, out_path)


def main(argv: list[str] | None = None) -> int:
    from quant.console import force_utf8

    force_utf8()
    ap = argparse.ArgumentParser(prog="agent1", description="Agent 1 手动触发回测闭环")
    ap.add_argument("--instruction", required=True, help="四字段研究指令 JSON 文件")
    ap.add_argument("--data-dir", help="快照目录（真实数据）；不传则用仓库默认合成样本")
    ap.add_argument("--internal-spec", action="store_true", help="诊断用：允许直接传内部 spec")
    ap.add_argument("--out", help="信封输出路径")
    ap.add_argument("--json", action="store_true", help="只打印信封 JSON")
    args = ap.parse_args(argv)

    with open(args.instruction, encoding="utf-8-sig") as fh:
        instruction = json.load(fh)

    out = args.out or os.path.join(REPORT_DIR, "agent1-latest.json")
    env = run(instruction, out, data_dir=args.data_dir, internal_spec=args.internal_spec)
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0 if env["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
