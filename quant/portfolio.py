"""组合构造器：把"选中哪些标的"变成"各给多少权重"。

引擎只负责选股和净值循环；权重逻辑放这里，新增方案不再改回测主循环。
`equal` 必须保持逐位不变，旧实验的 nav_hash 不能被这次抽象改掉。
"""
from __future__ import annotations

import math

from .data import Panel

TRADING_DAYS = 252
TARGET_VOL = 0.15
VOL_WINDOW = 60


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def _returns(panel: Panel, asset: str, end: int, window: int = VOL_WINDOW) -> list[float]:
    start = max(1, end - window + 1)
    out = []
    for j in range(start, end + 1):
        prev = panel.close[asset][j - 1]
        if prev > 0:
            out.append(panel.close[asset][j] / prev - 1.0)
    return out


def _vol(panel: Panel, asset: str, end: int) -> float:
    rets = _returns(panel, asset, end)
    return _stdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) >= 2 else 0.0


def _equal(picked: list[str]) -> dict[str, float]:
    return {a: 1.0 / len(picked) for a in picked}


def _score_weighted(picked: list[str], scores: dict[str, float]) -> dict[str, float]:
    vals = {a: scores[a] for a in picked if a in scores}
    if len(vals) != len(picked):
        return _equal(picked)
    low = min(vals.values())
    raw = {a: vals[a] - low + 1e-9 for a in picked}
    total = sum(raw.values())
    if total <= 0:
        return _equal(picked)
    return {a: raw[a] / total for a in picked}


def _inverse_vol(panel: Panel, picked: list[str], end: int) -> dict[str, float]:
    vols = {}
    for a in picked:
        v = _vol(panel, a, end)
        vols[a] = v if v > 1e-6 else None
    known = [v for v in vols.values() if v is not None]
    fallback = _mean(known) if known else 0.02
    raw = {a: 1.0 / (vols[a] if vols[a] is not None else fallback) for a in picked}
    total = sum(raw.values())
    weights = {a: raw[a] / total for a in picked} if total > 0 else _equal(picked)
    # 单票上限 25%：把超限部分按比例分给未超限的标的
    for _ in range(10):
        over = {a: w - 0.25 for a, w in weights.items() if w > 0.25 + 1e-12}
        if not over:
            break
        excess = sum(over.values())
        for a in over:
            weights[a] = 0.25
        under = [a for a, w in weights.items() if w < 0.25 - 1e-12]
        pool = sum(weights[a] for a in under)
        if pool <= 0:
            break
        for a in under:
            weights[a] += excess * weights[a] / pool
    return weights


def _vol_target(panel: Panel, picked: list[str], end: int) -> dict[str, float]:
    base = _equal(picked)
    series = []
    for j in range(max(1, end - VOL_WINDOW + 1), end + 1):
        r = 0.0
        for a, w in base.items():
            prev = panel.close[a][j - 1]
            if prev > 0:
                r += w * (panel.close[a][j] / prev - 1.0)
        series.append(r)
    vol = _stdev(series) * math.sqrt(TRADING_DAYS) if len(series) >= 2 else 0.0
    scale = 1.0 if vol <= 1e-9 else min(1.0, TARGET_VOL / vol)
    return {a: w * scale for a, w in base.items()}


def construct(
    panel: Panel, picked: list[str], scores: dict[str, float], end: int, weighting: str
) -> dict[str, float]:
    if not picked:
        return {}
    if weighting == "equal":
        return _equal(picked)
    if weighting == "score":
        return _score_weighted(picked, scores)
    if weighting == "inverse_vol":
        return _inverse_vol(panel, picked, end)
    if weighting == "vol_target":
        return _vol_target(panel, picked, end)
    raise ValueError(f"未知权重方案 {weighting!r}")
