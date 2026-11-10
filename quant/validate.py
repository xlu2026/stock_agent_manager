"""策略静态校验：在花时间跑回测之前，先指出 spec 里会毁掉结论的问题。

返回值是给 Agent 消费的诊断清单，不是异常：调用方能拿到 fail/warn 逐条原因，
再决定是否修改研究指令。
"""
from __future__ import annotations

from .data import load_panel
from .factors import MIN_HISTORY
from .spec import FACTORS, Spec, SpecError, parse_spec


def _check(check_id: str, status: str, detail: str, hint: str | None = None) -> dict:
    out = {"id": check_id, "status": status, "detail": detail}
    if hint:
        out["hint"] = hint
    return out


def validate_strategy(raw: dict | str | Spec) -> dict:
    checks: list[dict] = []

    if isinstance(raw, Spec):
        spec = raw
    else:
        try:
            spec = parse_spec(raw)
        except SpecError as exc:
            return {
                "ok": False,
                "verdict": "rejected",
                "checks": [_check("spec.parse", "fail", str(exc), "按 spec 字段表重写研究指令")],
            }

    checks.append(_check("spec.parse", "pass", f"spec 合法，因子={spec.factor}"))

    panel = load_panel()

    # 数据区间覆盖
    if spec.start < panel.dates[0] or spec.end > panel.dates[-1]:
        checks.append(
            _check(
                "data.range",
                "fail",
                f"回测区间 {spec.start}..{spec.end} 超出数据快照 "
                f"{panel.dates[0]}..{panel.dates[-1]}",
                "调整 start/end",
            )
        )
    else:
        checks.append(_check("data.range", "pass", "回测区间落在数据快照内"))

    # 数据版本固定
    if spec.data_version is None:
        checks.append(
            _check(
                "data.pinned",
                "warn",
                f"未显式固定 data_version；本次将使用 {panel.data_version}",
                f'建议加 "data_version": "{panel.data_version}" 以便跨机复现',
            )
        )
    elif spec.data_version != panel.data_version:
        checks.append(
            _check("data.pinned", "fail", f"spec 固定 {spec.data_version}，当前快照为 {panel.data_version}")
        )
    else:
        checks.append(_check("data.pinned", "pass", f"数据版本已固定为 {panel.data_version}"))

    # 因子预热窗口：start 之前是否够算因子（唯一来源：factors.MIN_HISTORY）
    start_idx = panel.index_of(spec.start)
    need = MIN_HISTORY.get(spec.factor, 1)
    if start_idx < need:
        checks.append(
            _check(
                "factor.warmup",
                "fail",
                f"{spec.factor} 需要 {need} 个交易日预热，start={spec.start} 之前只有 {start_idx} 天",
                "把 start 往后推",
            )
        )
    else:
        checks.append(_check("factor.warmup", "pass", f"预热充足（{start_idx} >= {need}）"))

    # 分散度
    if spec.top_k >= len(panel.assets):
        checks.append(
            _check("portfolio.diversification", "warn", f"top_k={spec.top_k} 已覆盖全池，等价于等权基准")
        )
    elif spec.top_k < 3:
        checks.append(
            _check("portfolio.diversification", "warn", f"top_k={spec.top_k} 过于集中，结论对个别标的敏感")
        )
    else:
        checks.append(_check("portfolio.diversification", "pass", f"top_k={spec.top_k}"))

    # 成本
    if spec.cost_bps <= 0:
        checks.append(
            _check("cost.nonzero", "fail", "cost_bps=0 会系统性高估收益", "设为 >= 5")
        )
    elif spec.cost_bps < 5:
        checks.append(_check("cost.nonzero", "warn", f"cost_bps={spec.cost_bps} 偏低"))
    else:
        checks.append(_check("cost.nonzero", "pass", f"cost_bps={spec.cost_bps}"))

    # 前视偏差与实盘能力：结构性保证，不是运行时检查
    checks.append(
        _check(
            "lookahead.guard",
            "pass",
            "引擎固定用 t-1 日信号在 t 日建仓，因子函数看不到 t 日之后的数据",
        )
    )
    checks.append(
        _check(
            "compliance.no_live_path",
            "pass",
            "该 spec 不含任何下单字段；引擎只产出净值和指标，不具备实盘下单能力",
        )
    )

    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    ok = not fails
    return {
        "ok": ok,
        "verdict": "accepted" if ok else "rejected",
        "fail_count": len(fails),
        "warn_count": len(warns),
        "checks": checks,
        "spec": spec.canonical(),
        "available_factors": FACTORS,
    }
