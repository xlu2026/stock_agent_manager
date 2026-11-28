"""多因子合成：按权重把多个因子的截面 z-score 相加。"""
from __future__ import annotations

import math

from ..factors import FACTOR_FUNCS, MIN_HISTORY, scores
from .base import StrategyError, StrategyInfo, register

PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "factors": {"type": "object"},
        "normalize": {"type": "string", "enum": ["zscore", "rank"], "default": "zscore"},
        "winsorize": {"type": "number", "minimum": 0, "maximum": 0.2, "default": 0.0},
        "neutralize": {"type": "string", "enum": ["none", "demean"], "default": "none"},
    },
    "required": ["factors"],
    "additionalProperties": False,
}


def _check(params: dict) -> None:
    factors = params["factors"]
    if not isinstance(factors, dict) or not 2 <= len(factors) <= len(FACTOR_FUNCS):
        raise StrategyError("BAD_PARAM", f"factors 需要 2~{len(FACTOR_FUNCS)} 个因子及权重")
    for name, weight in factors.items():
        if name not in FACTOR_FUNCS:
            raise StrategyError("BAD_PARAM", f"未知因子 {name!r}")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight == 0:
            raise StrategyError("BAD_PARAM", f"因子 {name} 的权重必须是非零数字")
    if abs(sum(float(w) for w in factors.values())) < 1e-9:
        raise StrategyError("BAD_PARAM", "因子权重之和不能为 0（否则合成分数恒为 0）")


def _warmup(params: dict) -> int:
    return max(MIN_HISTORY[name] for name in params["factors"])


def _required(params: dict) -> tuple[str, ...]:
    fundamental = {"value_proxy", "quality_proxy"}
    need = {"price"}
    if fundamental & set(params["factors"]):
        need.add("fundamentals")
    return tuple(sorted(need))


def _score(panel, i: int, params: dict) -> dict[str, float]:
    raw = {name: scores(panel, name, i) for name in params["factors"]}
    common = set(raw[next(iter(raw))])
    for series in raw.values():
        common &= set(series)
    if not common:
        return {}
    assets = sorted(common)
    zs: dict[str, dict[str, float]] = {}
    winsor = float(params.get("winsorize") or 0.0)
    normalize = params.get("normalize") or "zscore"
    for name, series in raw.items():
        values = [series[a] for a in assets]
        if winsor > 0 and len(values) >= 5:
            ordered = sorted(values)
            k = int(len(values) * winsor)
            if k > 0:
                low, high = ordered[k], ordered[-k - 1]
                values = [min(max(v, low), high) for v in values]
        if normalize == "rank":
            order = sorted(range(len(assets)), key=lambda j: (values[j], assets[j]))
            n = len(assets)
            ranks = {j: (pos / (n - 1) - 0.5 if n > 1 else 0.0) for pos, j in enumerate(order)}
            zs[name] = {a: ranks[j] for j, a in enumerate(assets)}
        else:
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
            std = math.sqrt(var)
            zs[name] = {a: ((v - mean) / std if std > 1e-12 else 0.0) for a, v in zip(assets, values)}
        if params.get("neutralize") == "demean":
            mu = sum(zs[name].values()) / len(zs[name])
            zs[name] = {a: v - mu for a, v in zs[name].items()}
    total_abs = sum(abs(float(w)) for w in params["factors"].values())
    out = {a: 0.0 for a in assets}
    for name, weight in params["factors"].items():
        w = float(weight) / total_abs
        for a in assets:
            out[a] += w * zs[name][a]
    return out


register(
    StrategyInfo(
        id="composite",
        version="1.0",
        description="多因子合成：各因子先做截面 z-score，再按权重相加。",
        params_schema=PARAMS_SCHEMA,
        warmup=_warmup,
        score=_score,
        check=_check,
        required_data=_required,
    )
)
