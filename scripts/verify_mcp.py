"""MCP 协议级自检：真的 spawn 一个 stdio 服务端，走完整 JSON-RPC 握手。

回答简报里的问题 2/3：工具面是否可发现、返回格式是否适合 Agent 消费。
    python scripts/verify_mcp.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SPEC = {
    "factor": "momentum_12_1",
    "universe": "synthetic_40",
    "start": "2020-01-02",
    "end": "2024-12-31",
    "rebalance": "M",
    "top_k": 8,
    "cost_bps": 10,
    "seed": 42,
    "data_version": "dv-572bafec2a92",
}


class StdioClient:
    def __init__(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        env["PYTHONIOENCODING"] = "utf-8"
        # 自检不应污染真实实验登记簿
        env["NFR_EXPERIMENTS_DIR"] = tempfile.mkdtemp(prefix="nfr-verify-")
        env["NFR_BROKER_DIR"] = tempfile.mkdtemp(prefix="nfr-verify-broker-")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "quant.cli", "mcp", "serve"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self._id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"服务端无响应，stderr:\n{err}")
        return json.loads(line)

    def notify(self, method: str, params: dict | None = None) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=30)


def text_of(resp: dict) -> str:
    blocks = resp.get("result", {}).get("content") or []
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def main() -> int:
    from quant.console import force_utf8

    force_utf8()
    checks: list[dict] = []
    client = StdioClient()
    try:
        init = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "verify-mcp", "version": "1.0"},
            },
        )
        info = init.get("result", {}).get("serverInfo", {})
        checks.append(
            {
                "step": "initialize",
                "ok": bool(info),
                "protocol": init.get("result", {}).get("protocolVersion"),
                "server": info,
            }
        )
        client.notify("notifications/initialized")

        listed = client.request("tools/list")
        tools = listed.get("result", {}).get("tools", [])
        names = [t["name"] for t in tools]
        expected = [
            "run_research_instruction",
            "run_backtest",
            "validate_strategy",
            "list_experiments",
            "get_experiment",
            "run_factor_analysis",
            "run_paper_session",
            "broker_account",
            "broker_orders",
            "broker_propose_order",
            "broker_submit_order",
        ]
        checks.append(
            {
                "step": "tools/list",
                "ok": set(expected) <= set(names),
                "count": len(names),
                "tools": names,
                "missing": sorted(set(expected) - set(names)),
                "all_have_schema": all("inputSchema" in t and t.get("description") for t in tools),
            }
        )

        def call(name: str, args: dict) -> dict:
            r = client.request("tools/call", {"name": name, "arguments": args})
            res = r.get("result", {})
            return {
                "name": name,
                "isError": res.get("isError"),
                "has_structured": isinstance(res.get("structuredContent"), dict),
                "text_head": text_of(r)[:160],
                "structured": res.get("structuredContent"),
            }

        v = call("validate_strategy", {"spec": SPEC})
        checks.append({"step": "validate_strategy", "ok": v["isError"] is False, "result": v["structured"]})

        # 四字段契约：模型只能填这四项，因子由服务端关键词表决定
        research = call(
            "run_research_instruction",
            {
                "question": "过去一年涨得多的标的是否会继续走强",
                "universe": "synthetic_40",
                "period": "2020-01-02~2024-12-31",
                "factor_logic": "过去一年涨幅靠前的标的，接下来一个月是否继续走强（动量/趋势延续）",
            },
        )
        rc = research.get("structured") or {}
        checks.append(
            {
                "step": "run_research_instruction",
                "ok": research["isError"] is False
                and bool(rc.get("experiment_id"))
                and (rc.get("spec") or {}).get("factor") == "momentum_12_1"
                and (rc.get("contract") or {}).get("mapping", {}).get("matched") == ["momentum_12_1"],
                "experiment_id": rc.get("experiment_id"),
                "mapped_factor": (rc.get("spec") or {}).get("factor"),
                "mapping_source": (rc.get("contract") or {}).get("mapping", {}).get("source"),
            }
        )

        bt = call("run_backtest", {"spec": SPEC})
        metrics = (bt.get("structured") or {}).get("metrics", {})
        checks.append(
            {
                "step": "run_backtest",
                "ok": bt["isError"] is False and bool(metrics.get("nav_hash")) and bt["has_structured"],
                "experiment_id": (bt.get("structured") or {}).get("experiment_id"),
                "metric_keys": sorted(metrics),
                "has_structuredContent": bt["has_structured"],
            }
        )

        exps = call("list_experiments", {"limit": 5})
        checks.append(
            {
                "step": "list_experiments",
                "ok": (exps.get("structured") or {}).get("count", 0) >= 1,
                "count": (exps.get("structured") or {}).get("count"),
            }
        )

        eid = (bt.get("structured") or {}).get("experiment_id")
        got = call("get_experiment", {"experiment_id": eid, "include_series": False})
        checks.append(
            {
                "step": "get_experiment",
                "ok": (got.get("structured") or {}).get("experiment_id") == eid,
                "metrics_present": "metrics" in (got.get("structured") or {}),
            }
        )

        fa = call("run_factor_analysis", {"spec": SPEC, "quantiles": 5})
        checks.append(
            {
                "step": "run_factor_analysis",
                "ok": fa["isError"] is False and "ic_mean" in (fa.get("structured") or {}),
                "ic_mean": (fa.get("structured") or {}).get("ic_mean"),
            }
        )

        ps = call("run_paper_session", {"spec": SPEC, "sessions": 3})
        paper = ps.get("structured") or {}
        checks.append(
            {
                "step": "run_paper_session",
                "ok": ps["isError"] is False and paper.get("live_orders") is False,
                "fills": paper.get("fill_count"),
                "live_orders": paper.get("live_orders"),
            }
        )

        # 下单闸门：未经人工批准的提案，提交必须失败
        prop = call("broker_propose_order", {"symbol": "SYN001", "side": "BUY", "quantity": 10})
        pid = ((prop.get("structured") or {}).get("proposal") or {}).get("proposal_id")
        submit = client.request("tools/call", {"name": "broker_submit_order", "arguments": {"proposal_id": pid}})
        submit_text = text_of(submit)
        checks.append(
            {
                "step": "broker_requires_human_approval",
                "ok": submit.get("result", {}).get("isError") is True and "NOT_APPROVED" in submit_text,
                "proposal_id": pid,
                "approve_command": (prop.get("structured") or {}).get("approve_command"),
                "text_head": submit_text[:120],
            }
        )

        # 错误路径：未知工具必须失败得可见，不能伪装成功
        bad = call("live_submit_order", {"symbol": "SYN001"})
        checks.append(
            {
                "step": "unknown_tool_rejected",
                "ok": bad["isError"] is True,
                "detail": "live_submit_order 不存在，调用被显式拒绝",
            }
        )

        bad2 = client.request(
            "tools/call",
            {"name": "run_backtest", "arguments": {"spec": {**SPEC, "factor": "no_such_factor"}}},
        )
        checks.append(
            {
                "step": "invalid_spec_rejected",
                "ok": bad2.get("result", {}).get("isError") is True,
                "text_head": text_of(bad2)[:120],
            }
        )
    finally:
        client.close()

    ok = all(c["ok"] for c in checks)
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
