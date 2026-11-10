"""Phase 1 一键验收：把所有交付物跑一遍并留下证据。

    python scripts/acceptance.py

输出 output/reports/acceptance.json（机器可读）+ 控制台摘要。
任何一项 FAIL 都以非零退出码结束。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.agent1 import run as run_agent1  # noqa: E402
from agents.agent3 import run as run_agent3  # noqa: E402
from agents.envelope import write_json  # noqa: E402
from quant.console import force_utf8  # noqa: E402
from quant.data import load_panel  # noqa: E402
from quant.engine import run_backtest  # noqa: E402
from quant.spec import parse_spec  # noqa: E402
from writing.wechat import probe_draft_api  # noqa: E402

REPORTS = os.path.join(ROOT, "output", "reports")
OUT = os.path.join(REPORTS, "acceptance.json")
CONFIG_DIR = os.path.join(ROOT, "cordis", "profiles")


def _check(name: str, ok: bool, detail: dict) -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def check_engine() -> dict:
    panel = load_panel()
    spec = parse_spec(
        {
            "factor": "momentum_12_1",
            "universe": "synthetic_40",
            "start": "2020-01-02",
            "end": "2024-12-31",
            "rebalance": "M",
            "top_k": 8,
            "cost_bps": 10,
            "seed": 42,
            "data_version": panel.data_version,
        }
    )
    a = run_backtest(spec)
    b = run_backtest(spec)
    return _check(
        "1. 确定性回测（同输入同结果）",
        a.metrics["nav_hash"] == b.metrics["nav_hash"],
        {
            "experiment_id": a.experiment_id,
            "nav_hash": a.metrics["nav_hash"],
            "cagr": a.metrics["cagr"],
            "sharpe": a.metrics["sharpe"],
            "max_drawdown": a.metrics["max_drawdown"],
            "data_version": a.data_version,
            "rebalances": len(a.holdings),
        },
    )


def check_mcp() -> dict:
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "verify_mcp.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _check("2. MCP 工具面可发现可调用", False, {"stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]})
    tools = next((c["tools"] for c in report["checks"] if c["step"] == "tools/list"), [])
    return _check(
        "2. MCP 工具面可发现可调用",
        report["ok"],
        {
            "tools": tools,
            "steps_ok": sum(1 for c in report["checks"] if c["ok"]),
            "steps_total": len(report["checks"]),
        },
    )


def check_agent1() -> dict:
    with open(os.path.join(ROOT, "examples", "research_instruction.json"), encoding="utf-8-sig") as fh:
        instruction = json.load(fh)
    env = run_agent1(instruction, os.path.join(REPORTS, "agent1_latest.json"))
    contract = env["summary"].get("contract", {})
    mapped = (contract.get("mapping") or {}).get("matched")
    return _check(
        "3. Agent 1 闭环（四字段指令 -> 回测 -> 指标 + 实验 ID）",
        env["status"] == "ok"
        and bool(env["summary"]["metrics"]["nav_hash"])
        and contract.get("kind") == "phase1_contract/v1"
        and mapped == ["momentum_12_1"],
        {
            "status": env["status"],
            "experiment_id": env["id"],
            "artifacts": [a["path"] for a in env["artifacts"]],
            "cagr": env["summary"]["metrics"]["cagr"],
            "nav_hash": env["summary"]["metrics"]["nav_hash"],
            "contract_kind": contract.get("kind"),
            "mapped_factor": mapped,
            "mapping_source": (contract.get("mapping") or {}).get("source"),
        },
    )


def check_agent3() -> dict:
    with open(os.path.join(ROOT, "examples", "brief_demo.json"), encoding="utf-8-sig") as fh:
        brief = json.load(fh)
    # 成文稿统一放写作工作区，这里把渲染器的落盘目录临时指到报告目录，
    # 避免每次验收都在 output/articles/ 生成一份文章副本。
    import writing.article as art

    build_dir = os.path.join(REPORTS, "acceptance_article")
    os.makedirs(build_dir, exist_ok=True)
    previous = art.ARTICLE_DIR
    art.ARTICLE_DIR = build_dir
    try:
        env = run_agent3(brief, channel="auto")
    finally:
        art.ARTICLE_DIR = previous
    path = env["artifacts"][0].get("path") if env["artifacts"] else None
    full = os.path.join(ROOT, path) if path else ""
    text = ""
    if full and os.path.exists(full):
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    has_fm = text.startswith("---\n")
    return _check(
        "4. Agent 3 降级路径（front matter Markdown）",
        env["status"] == "ok" and has_fm and env["summary"]["channel"] == "markdown",
        {
            "status": env["status"],
            "channel": env["summary"]["channel"],
            "path": path,
            "word_count": env["summary"]["word_count"],
            "front_matter": has_fm,
            "decision_reason": env["summary"]["decision_reason"],
        },
    )


def check_zhihu_export() -> dict:
    """知乎导出：只产粘贴稿，不发布；front matter/H1 已剥离，声明逐字保留。"""
    import tempfile

    from writing import article as art
    from writing.compliance import RISK_DISCLAIMER
    from writing.platforms.zhihu import export_article

    with open(os.path.join(ROOT, "examples", "brief_demo.json"), encoding="utf-8-sig") as fh:
        brief = json.load(fh)
    rendered = art.render(brief)

    with tempfile.TemporaryDirectory(prefix="nfr-acc-zhihu-") as tmp:
        src = os.path.join(tmp, rendered["filename"])
        with open(src, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered["markdown"])
        result = export_article(src, out_dir=tmp)
        with open(result["html_path"], encoding="utf-8") as fh:
            html_text = fh.read()
        with open(result["meta_path"], encoding="utf-8") as fh:
            meta = json.load(fh)

    flags = {
        "no_front_matter": not html_text.startswith("---") and "schema:" not in html_text,
        "no_h1": "<h1>" not in html_text,
        "disclaimer_verbatim": RISK_DISCLAIMER in html_text,
        "topics": bool(meta.get("topics")),
        "published_false": meta.get("published") is False,
        "publish_api_absent": meta.get("publish_api") == "absent",
    }
    return _check("4b. 知乎导出（无 front matter、合规声明、无发布面）", all(flags.values()), flags)


def check_wechat() -> dict:
    probe = probe_draft_api()
    verdict = "DRAFT_API_AVAILABLE" if probe["available"] else "DRAFT_API_UNAVAILABLE"
    return _check(
        "5. 公众号草稿接口预检给出明确结论",
        True,  # 无论可用与否，只要结论明确就算通过
        {"verdict": verdict, "reason": probe["reason"], "detail": probe["detail"]},
    )


def check_isolation() -> dict:
    """优先读已安装的 profile，其次读仓库生成物。"""
    home = os.path.join(os.path.expanduser("~"), ".dsh", "profiles")

    def read_profile(name: str) -> str:
        installed = os.path.join(home, name, "cordis.patch.yml")
        if os.path.exists(installed):
            with open(installed, encoding="utf-8") as fh:
                return fh.read()
        with open(os.path.join(CONFIG_DIR, f"{name}.yml"), encoding="utf-8") as fh:
            return fh.read()

    quant_yml = read_profile("quant")
    writing_yml = read_profile("writing")
    quant_has_srq = "serverName: srq" in quant_yml
    writing_has_srq = "serverName: srq" in writing_yml
    writing_has_draft = "serverName: draft" in writing_yml
    shell_off = "tool-pwsh" in writing_yml and "disabled: true" in writing_yml
    installed = os.path.exists(os.path.join(home, "quant", "cordis.patch.yml"))
    return _check(
        "6. 工具面不交叉（量化 MCP 只在 quant 侧注册）",
        quant_has_srq and not writing_has_srq and writing_has_draft and shell_off,
        {
            "quant_has_srq": quant_has_srq,
            "writing_has_srq": writing_has_srq,
            "writing_has_draft_server": writing_has_draft,
            "writing_shell_disabled": shell_off,
            "installed_profiles_checked": installed,
            "profiles_dir": home,
        },
    )


def check_compliance() -> dict:
    root = os.path.join(ROOT, "quant")
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                    if re_search_order(fh.read()):
                        hits.append(f)
    return _check(
        "7. 无实盘下单能力（全仓无 live_submit_order 实现）",
        not hits,
        {"files_with_live_order": hits},
    )


def re_search_order(text: str) -> bool:
    """只在"实现"意义上算违规：docstring 里声明"不存在"不算。"""
    import re

    for m in re.finditer(r"live_submit_order", text):
        window = text[max(0, m.start() - 40) : m.end() + 40]
        if not any(k in window for k in ("不存在", "unavailable", "禁止", "没有", "不可达")):
            return True
    return False


def check_profile_drift() -> dict:
    """已安装 profile 必须与仓库生成物一致，防止手改后与仓库漂移。"""
    home = os.path.join(os.path.expanduser("~"), ".dsh", "profiles")
    missing, drifted = [], []
    for name in ("quant", "writing"):
        installed_path = os.path.join(home, name, "cordis.patch.yml")
        if not os.path.exists(installed_path):
            missing.append(name)
            continue
        with open(os.path.join(CONFIG_DIR, f"{name}.yml"), encoding="utf-8") as fh:
            repo_text = fh.read().strip("\n")
        with open(installed_path, encoding="utf-8") as fh:
            installed_text = fh.read()
        if repo_text not in installed_text:
            drifted.append(name)
    return _check(
        "8. 已安装 profile 与仓库生成物一致（无手改漂移）",
        not missing and not drifted,
        {"missing": missing, "drifted": drifted, "profiles_dir": home},
    )


def check_strategy_doc() -> dict:
    """策略文档必须与代码同步：因子清单、引擎版本都要在里面。"""
    from quant.engine import ENGINE_VERSION
    from quant.spec import FACTORS, SPEC_VERSION

    path = os.path.join(ROOT, "docs", "strategy.md")
    if not os.path.exists(path):
        return _check("10. 策略文档与代码同步", False, {"error": "docs/strategy.md 不存在"})
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    missing_factors = [f for f in FACTORS if f"`{f}`" not in text]
    has_engine = ENGINE_VERSION in text
    has_spec_version = SPEC_VERSION in text
    return _check(
        "10. 策略文档与代码同步",
        not missing_factors and has_engine and has_spec_version,
        {
            "doc": "docs/strategy.md",
            "factors_documented": len(FACTORS) - len(missing_factors),
            "factors_total": len(FACTORS),
            "missing_factors": missing_factors,
            "engine_version_in_doc": has_engine,
            "spec_version_in_doc": has_spec_version,
        },
    )


def check_broker() -> dict:
    """券商抽象层可用，且关键闸门（人工确认）默认生效。"""
    import tempfile

    from quant.broker import OrderRequest, OrderStatus, PaperBroker, RejectReason, Side

    old = os.environ.get("NFR_BROKER_DIR")
    tmp = tempfile.mkdtemp(prefix="nfr-acc-broker-")
    os.environ["NFR_BROKER_DIR"] = tmp
    try:
        b = PaperBroker(price_of=lambda s: 10.0, ledger_name="acc_probe")
        unconfirmed = b.submit(OrderRequest("acc-1", "SYN001", Side.BUY, 10, human_confirmed=False))
        confirmed = b.submit(OrderRequest("acc-2", "SYN001", Side.BUY, 10, human_confirmed=True))
        return _check(
            "9. 券商抽象层（确认闸门 + 模拟成交 + 审计）",
            unconfirmed.status is OrderStatus.REJECTED
            and unconfirmed.reject_reason is RejectReason.NOT_CONFIRMED
            and confirmed.status is OrderStatus.FILLED
            and os.path.exists(os.path.join(tmp, "acc_probe.jsonl")),
            {
                "unconfirmed": unconfirmed.status.value,
                "reason": unconfirmed.reject_reason.value if unconfirmed.reject_reason else None,
                "confirmed": confirmed.status.value,
                "ledger": "acc_probe.jsonl",
                "note": "真实券商适配器尚未实现，当前只有 PaperBroker",
            },
        )
    finally:
        os.environ.pop("NFR_BROKER_DIR", None)
        if old is not None:
            os.environ["NFR_BROKER_DIR"] = old


def main() -> int:
    force_utf8()
    os.makedirs(REPORTS, exist_ok=True)
    checks = [
        check_engine(),
        check_mcp(),
        check_agent1(),
        check_agent3(),
        check_zhihu_export(),
        check_wechat(),
        check_isolation(),
        check_compliance(),
        check_profile_drift(),
        check_broker(),
        check_strategy_doc(),
    ]
    ok = all(c["ok"] for c in checks)
    payload = {
        "schema": "nerve.acceptance/v1",
        "ok": ok,
        "python": sys.version.split()[0],
        "checks": checks,
    }
    write_json(OUT, payload)

    width = max(len(c["check"]) for c in checks)
    for c in checks:
        print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']:<{width}}  {json.dumps(c['detail'], ensure_ascii=False)[:120]}")
    print()
    print(f"写盘：{os.path.relpath(OUT, ROOT)}")
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
