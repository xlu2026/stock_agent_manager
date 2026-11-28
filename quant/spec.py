"""研究指令（spec）的解析、校验与规范化。

一份 spec 是 Agent 1 与回测引擎之间唯一的契约：Agent 只能填字段，
不能自定义计算规则；任何未知字段都会被拒绝，避免把"提示词里的想法"
偷偷变成引擎行为。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SPEC_VERSION = "1.0"

FACTORS = {
    "momentum_12_1": "12 个月动量剔除最近 1 个月，抑制短期反转",
    "value_proxy": "账面价值 / 收盘价（B/P），越高表示越便宜",
    "low_vol_60d": "过去 60 个交易日日收益波动率，取负值，越低越好",
    "quality_proxy": "ROE 代理：TTM 盈利 / 账面价值，越高越好",
}

REBALANCE = {"M": "月末", "W": "周末", "Q": "季末"}
WEIGHTING = {
    "equal": "等权",
    "score": "按得分加权",
    "inverse_vol": "按 60 日波动倒数加权（单票上限 25%）",
    "vol_target": "等权后按 15% 年化目标波动缩放（不加杠杆）",
}

REQUIRED = ("universe", "start", "end")
OPTIONAL: dict[str, Any] = {
    "rebalance": "M",
    "top_k": 10,
    "weighting": "equal",
    "cost_bps": 10,
    "seed": 42,
    "data_version": None,
    "spec_version": SPEC_VERSION,
}
KNOWN = set(REQUIRED) | set(OPTIONAL) | {"factor", "strategy", "params"}


class SpecError(ValueError):
    """spec 不合法；message 直接面向人和 Agent，用于自我修正。"""


@dataclass(frozen=True)
class Spec:
    factor: str
    universe: str
    start: str
    end: str
    rebalance: str = "M"
    top_k: int = 10
    weighting: str = "equal"
    cost_bps: float = 10.0
    seed: int = 42
    data_version: str | None = None
    spec_version: str = SPEC_VERSION
    strategy: str = "single_factor"
    params: dict[str, Any] = field(default_factory=dict, compare=False)
    strategy_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    def canonical(self) -> dict[str, Any]:
        """去掉未参与计算的字段后排序，用于计算可复现指纹。

        旧 spec（只有 factor、没有额外参数）必须保持原来的字段集，
        否则已有实验 ID 会全部漂移；新策略才加 strategy/params/version。
        """
        legacy = self.strategy == "single_factor" and (
            not self.params or self.params == {"factor": self.factor}
        )
        if legacy:
            return {
                "spec_version": self.spec_version,
                "factor": self.factor,
                "universe": self.universe,
                "start": self.start,
                "end": self.end,
                "rebalance": self.rebalance,
                "top_k": self.top_k,
                "weighting": self.weighting,
                "cost_bps": self.cost_bps,
                "seed": self.seed,
                "data_version": self.data_version,
            }
        return {
            "spec_version": self.spec_version,
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "params": self.params,
            "universe": self.universe,
            "start": self.start,
            "end": self.end,
            "rebalance": self.rebalance,
            "top_k": self.top_k,
            "weighting": self.weighting,
            "cost_bps": self.cost_bps,
            "seed": self.seed,
            "data_version": self.data_version,
        }

    def is_legacy_single_factor(self) -> bool:
        return self.strategy == "single_factor" and (
            not self.params or self.params == {"factor": self.factor}
        )

    def fingerprint(self, data_sha256: str) -> str:
        payload = json.dumps(
            {"spec": self.canonical(), "data_sha256": data_sha256},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_str(raw: dict[str, Any], key: str) -> str:
    val = raw.get(key)
    if not isinstance(val, str) or not val.strip():
        raise SpecError(f"字段 {key} 必须是非空字符串，收到 {val!r}")
    return val.strip()


def parse_spec(raw: dict[str, Any] | str) -> Spec:
    """把外部 JSON（dict 或字符串）解析为 Spec，未知字段一律报错。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SpecError(f"spec 不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise SpecError("spec 必须是 JSON 对象")

    known = KNOWN
    unknown = sorted(set(raw) - known)
    if unknown:
        raise SpecError(f"出现未知字段 {unknown}；可用字段：{sorted(known)}")

    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise SpecError(f"缺少必填字段 {missing}")

    merged = dict(OPTIONAL)
    merged.update({k: raw[k] for k in known if k in raw and k not in ("factor", "strategy", "params")})

    from .strategies import StrategyError, get as get_strategy, validate_params

    if "strategy" in raw:
        if "factor" in raw:
            raise SpecError("strategy 与 factor 只能给一个；旧写法用 factor，新写法用 strategy + params")
        strategy = _require_str(raw, "strategy")
        try:
            params = validate_params(strategy, raw.get("params", {}))
        except StrategyError as exc:
            raise SpecError(str(exc)) from exc
        info = get_strategy(strategy)
        factor = str(params.get("factor") or "") if strategy == "single_factor" else ""
    else:
        factor = _require_str(raw, "factor")
        strategy = "single_factor"
        try:
            params = validate_params(strategy, {"factor": factor})
        except StrategyError as exc:
            raise SpecError(str(exc)) from exc
        info = get_strategy(strategy)

    universe = _require_str(merged, "universe")
    start = _require_str(merged, "start")
    end = _require_str(merged, "end")
    for name, val in (("start", start), ("end", end)):
        if len(val) != 10 or val[4] != "-" or val[7] != "-":
            raise SpecError(f"{name} 必须是 YYYY-MM-DD，收到 {val!r}")
    if start >= end:
        raise SpecError(f"start({start}) 必须早于 end({end})")

    rebalance = str(merged["rebalance"]).upper()
    if rebalance not in REBALANCE:
        raise SpecError(f"未知调仓频率 {rebalance!r}；可用：{sorted(REBALANCE)}")

    try:
        top_k = int(merged["top_k"])
        seed = int(merged["seed"])
        cost_bps = float(merged["cost_bps"])
    except (TypeError, ValueError) as exc:
        raise SpecError(f"top_k/seed 必须是整数，cost_bps 必须是数字：{exc}") from exc

    if not 1 <= top_k <= 40:
        raise SpecError(f"top_k 必须在 1..40，收到 {top_k}")
    if cost_bps < 0:
        raise SpecError(f"cost_bps 不能为负，收到 {cost_bps}")
    if seed < 0:
        raise SpecError(f"seed 必须为非负整数，收到 {seed}")

    weighting = str(merged["weighting"]).lower()
    if weighting not in WEIGHTING:
        raise SpecError(f"未知权重方案 {weighting!r}；可用：{sorted(WEIGHTING)}")

    spec_version = str(merged["spec_version"])
    if spec_version != SPEC_VERSION:
        raise SpecError(f"不支持的 spec_version {spec_version!r}；当前只接受 {SPEC_VERSION}")

    return Spec(
        factor=factor,
        universe=universe,
        start=start,
        end=end,
        rebalance=rebalance,
        top_k=top_k,
        weighting=weighting,
        cost_bps=cost_bps,
        seed=seed,
        data_version=merged["data_version"],
        spec_version=spec_version,
        strategy=strategy,
        params=params,
        strategy_version=info.version,
    )
