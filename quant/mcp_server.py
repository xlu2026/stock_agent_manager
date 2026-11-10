"""SolidRockQuant 兼容的 MCP stdio 服务端（量化侧）。

背景：Phase 1 环境里 ``srq`` 可执行文件与 SolidRockQuant 包均不存在
（PyPI 不可达，机器上没有该程序），因此这里按项目简报约定的工具面
自建一个确定性实现，命令行为 ``srq mcp serve``，暴露：

    run_backtest, validate_strategy, list_experiments, get_experiment,
    run_factor_analysis, run_paper_session

协议实现复用 ``shared.mcp_stdio``；本文件只定义量化工具。
"""
from __future__ import annotations

import json
import os
from typing import Any

from shared.mcp_stdio import McpServer

from . import experiments as exp_store
from .broker import OrderRequest, OrderType, PaperBroker, Side, price_from_panel
from .broker import proposals as broker_proposals
from .engine import run_backtest, run_factor_analysis
from .instruction import parse_instruction
from .paper import run_paper_session
from .spec import FACTORS, REBALANCE, SpecError, parse_spec
from .validate import validate_strategy

SERVER_NAME = "srq-compat"
SERVER_VERSION = "0.1.0"

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "结构化研究指令（引擎 spec）",
    "properties": {
        "factor": {"type": "string", "enum": sorted(FACTORS)},
        "universe": {"type": "string", "enum": ["synthetic_40"]},
        "start": {"type": "string", "description": "YYYY-MM-DD"},
        "end": {"type": "string", "description": "YYYY-MM-DD"},
        "rebalance": {"type": "string", "enum": sorted(REBALANCE)},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 40},
        "weighting": {"type": "string", "enum": ["equal"]},
        "cost_bps": {"type": "number", "minimum": 0},
        "seed": {"type": "integer", "minimum": 0},
        "data_version": {"type": "string"},
    },
    "required": ["factor", "universe", "start", "end"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ 工具实现


def _tool_run_backtest(args: dict) -> dict:
    return _run_spec(args.get("spec", args))


def _tool_validate(args: dict) -> dict:
    return validate_strategy(args.get("spec", args))


def _tool_list(args: dict) -> dict:
    return exp_store.list_experiments(int(args.get("limit", 20)))


def _tool_get(args: dict) -> dict:
    eid = args.get("experiment_id")
    if not isinstance(eid, str):
        raise SpecError("experiment_id 必须是字符串")
    return exp_store.get_experiment(eid, bool(args.get("include_series", False)))


def _tool_factor(args: dict) -> dict:
    spec = parse_spec(args.get("spec", args))
    return run_factor_analysis(spec, int(args.get("quantiles", 5)))


def _tool_research(args: dict) -> dict:
    """四字段研究指令入口：契约解析与因子映射都在服务端确定性地完成。"""
    instruction = parse_instruction(args)
    return _run_spec(instruction.to_spec(), contract={
        "instruction": {
            "question": instruction.question,
            "universe_raw": args["universe"],
            "period_raw": instruction.period,
            "factor_logic": instruction.factor_logic,
        },
        "mapping": instruction.mapping,
    })


def _run_spec(spec_dict: dict, contract: dict | None = None) -> dict:
    spec = parse_spec(spec_dict)
    bt = run_backtest(spec)
    rec = exp_store.save(bt)
    out = {
        "experiment_id": bt.experiment_id,
        "status": "completed",
        "metrics": bt.metrics,
        "spec": bt.spec.canonical(),
        "data_version": bt.data_version,
        "provenance": bt.provenance,
        "nav_points": len(bt.dates),
        "first_run_utc": rec["first_recorded_utc"],
        "runs": rec["runs"],
    }
    if contract is not None:
        out["contract"] = contract
    return out


def _tool_paper(args: dict) -> dict:
    spec = parse_spec(args.get("spec", args))
    return run_paper_session(spec, int(args.get("sessions", 6)))


def _spec_arg(description: str) -> dict:
    return {
        "type": "object",
        "properties": {"spec": SPEC_SCHEMA},
        "required": ["spec"],
        "additionalProperties": False,
        "description": description,
    }


# ------------------------------------------------------------------ 券商通道


_BROKER: PaperBroker | None = None
_BROKER_PRICE_DATE: str | None = None


def _state_path() -> str:
    base = os.environ.get("NFR_BROKER_DIR") or os.path.join(exp_store.ROOT, "output", "broker")
    return os.path.join(base, "paper_state.json")


def _get_broker() -> PaperBroker:
    """进程内单例；跨进程用状态文件恢复，避免每次调用都从零开始。"""
    global _BROKER, _BROKER_PRICE_DATE
    if _BROKER is None:
        from .data import load_panel

        panel = load_panel()
        _BROKER_PRICE_DATE = panel.dates[-1]
        cash = float(os.environ.get("NFR_PAPER_CASH", "100000"))
        broker = PaperBroker(
            price_of=price_from_panel(panel, _BROKER_PRICE_DATE),
            cash=cash,
            ledger_name="paper_orders",
        )
        path = _state_path()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                broker.apply_state(json.load(fh))
        _BROKER = broker
    return _BROKER


def _save_broker(broker: PaperBroker) -> None:
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(broker.dump_state(), fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _tool_broker_account(args: dict) -> dict:
    broker = _get_broker()
    acct = broker.account()
    return {
        "broker": broker.name,
        "mode": "PAPER",
        "price_date": _BROKER_PRICE_DATE,
        "cash": round(acct.cash, 2),
        "market_value": round(acct.market_value, 2),
        "equity": round(acct.equity, 2),
        "positions": [
            {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost, "market_value": round(p.market_value, 2)}
            for p in acct.positions
        ],
        "live_orders": False,
    }


def _tool_broker_orders(args: dict) -> dict:
    from .broker import ledger

    rows = ledger.read_all("paper_orders")
    limit = int(args.get("limit", 20))
    return {"count": len(rows), "orders": rows[-limit:]}


def _tool_broker_propose(args: dict) -> dict:
    side = str(args.get("side", "")).upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side 必须是 BUY 或 SELL")
    order_type = str(args.get("order_type", "MARKET")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        raise ValueError("order_type 必须是 MARKET 或 LIMIT")
    quantity = args.get("quantity")
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity 必须是正整数")
    limit_price = args.get("limit_price")
    if order_type == "LIMIT" and not limit_price:
        raise ValueError("限价单必须提供 limit_price")

    broker = _get_broker()
    price = broker.quote(str(args["symbol"]))  # 快照价，供人工判断与风控估值
    prop = broker_proposals.create(
        symbol=str(args["symbol"]),
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        experiment_id=args.get("experiment_id"),
        note=str(args.get("note", "")),
        price_snapshot=price,
    )
    return {
        "status": "pending_approval",
        "proposal": prop.as_dict(),
        "sha256": prop.sha256,
        "approve_command": broker_proposals.approve_command(prop.id),
        "next_step": "必须由人工在终端执行 approve_command；Agent 无法自行批准。",
        "live_orders": False,
    }


def _tool_broker_submit(args: dict) -> dict:
    pid = str(args.get("proposal_id", "")).strip()
    if not pid:
        raise ValueError("proposal_id 不能为空")

    payload = broker_proposals.verify_for_submit(pid)  # 未批准/过期/被改过都会在这里抛错
    broker = _get_broker()
    order = OrderRequest(
        client_order_id=pid,
        symbol=payload["symbol"],
        side=Side(payload["side"]),
        quantity=int(payload["quantity"]),
        order_type=OrderType(payload["order_type"]),
        limit_price=payload.get("limit_price"),
        experiment_id=payload.get("experiment_id"),
        human_confirmed=True,  # 人工批准已由文件校验过，不是模型自填
        note=payload.get("note", ""),
    )
    record = broker.submit(order)
    _save_broker(broker)
    broker_proposals.mark_submitted(pid, record.as_dict())

    return {
        "status": record.status.value,
        "reject_reason": record.reject_reason.value if record.reject_reason else None,
        "order": record.as_dict(),
        "account": _tool_broker_account({}),
        "live_orders": False,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_research_instruction",
        "description": (
            "按 Phase 1 的四字段研究指令跑一次回测：question / universe / period / factor_logic。"
            "factor_logic 是自然语言，由服务端的关键词映射表确定性地翻译成引擎因子，"
            "模型不能自行指定因子。返回指标、实验 ID 与映射明细。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "研究问题描述"},
                "universe": {"type": "string", "description": "标的池，如 synthetic_40"},
                "period": {"type": "string", "description": "起止日期，如 2020-01-02~2024-12-31"},
                "factor_logic": {"type": "string", "description": "待检验的因子逻辑（自然语言）"},
                "rebalance": {"type": "string", "enum": sorted(REBALANCE)},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 40},
                "cost_bps": {"type": "number", "minimum": 0},
                "seed": {"type": "integer", "minimum": 0},
                "data_version": {"type": "string"},
            },
            "required": ["question", "universe", "period", "factor_logic"],
            "additionalProperties": False,
        },
        "handler": _tool_research,
    },
    {
        "name": "run_backtest",
        "description": (
            "按结构化研究指令运行一次确定性因子回测，返回指标、实验 ID 与数据指纹。"
            "净值由本地引擎计算，不接受自然语言输入。"
        ),
        "inputSchema": _spec_arg("run_backtest 参数"),
        "handler": _tool_run_backtest,
    },
    {
        "name": "validate_strategy",
        "description": "在回测前静态校验研究指令（区间、预热、成本、数据版本固定），返回逐条诊断。",
        "inputSchema": _spec_arg("validate_strategy 参数"),
        "handler": _tool_validate,
    },
    {
        "name": "list_experiments",
        "description": "列出已登记的实验摘要（按时间倒序）。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            "additionalProperties": False,
        },
        "handler": _tool_list,
    },
    {
        "name": "get_experiment",
        "description": "按实验 ID 读取完整实验记录；include_series=true 时包含净值序列与持仓。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
                "include_series": {"type": "boolean"},
            },
            "required": ["experiment_id"],
            "additionalProperties": False,
        },
        "handler": _tool_get,
    },
    {
        "name": "run_factor_analysis",
        "description": "计算因子的 Rank IC 序列、IC_IR、分位收益与单调性。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": SPEC_SCHEMA,
                "quantiles": {"type": "integer", "minimum": 2, "maximum": 10},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
        "handler": _tool_factor,
    },
    {
        "name": "run_paper_session",
        "description": (
            "在历史数据上回放模拟盘成交台账（PAPER/SIMULATED）。"
            "只产出模拟记录，不具备任何实盘下单能力。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": SPEC_SCHEMA,
                "sessions": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
        "handler": _tool_paper,
    },
    {
        "name": "broker_account",
        "description": "查看模拟券商账户：现金、持仓、权益。只读，不产生订单。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_broker_account,
    },
    {
        "name": "broker_orders",
        "description": "读取订单审计账本（含被拒的订单）。只读。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            "additionalProperties": False,
        },
        "handler": _tool_broker_orders,
    },
    {
        "name": "broker_propose_order",
        "description": (
            "生成一笔下单提案。只写提案文件，不产生任何订单。"
            "提案必须由人工在终端执行 approve 命令后才能提交；Agent 无法自行批准。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                "quantity": {"type": "integer", "minimum": 1},
                "order_type": {"type": "string", "enum": ["MARKET", "LIMIT"]},
                "limit_price": {"type": "number", "minimum": 0},
                "experiment_id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["symbol", "side", "quantity"],
            "additionalProperties": False,
        },
        "handler": _tool_broker_propose,
    },
    {
        "name": "broker_submit_order",
        "description": (
            "提交已获批的下单提案。会校验人工批准记录、内容哈希、有效期与是否已提交；"
            "任何一项不过都会被拒绝。没有批准记录时拒单，并提示人工执行 approve 命令。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"proposal_id": {"type": "string"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
        "handler": _tool_broker_submit,
    },
]

INSTRUCTIONS = (
    "SolidRockQuant 兼容层：所有收益与风险指标由本地确定性引擎计算。"
    "调用方只能提交结构化 spec，不能提交自然语言策略描述。"
    "下单走 broker_* 工具：先 propose 生成提案，必须由人工在终端批准后才能 submit。"
)

def build_server() -> McpServer:
    return McpServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
        tools=TOOLS,
    )


def serve() -> int:
    return build_server().serve()


if __name__ == "__main__":
    raise SystemExit(serve())
