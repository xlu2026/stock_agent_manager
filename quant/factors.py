"""因子库：每个因子只在给定下标 i 的信息集内取值。

约定：调用方传入的 ``i`` 是"信号可用日"，引擎保证它不晚于建仓日的前一日，
因此因子函数内部不得再向后取任何数据，从结构上排除前视偏差。
"""
from __future__ import annotations

import math

from .data import Panel

# 各因子所需的最少历史长度（交易日）
MIN_HISTORY = {
    "momentum_12_1": 252,
    "value_proxy": 1,
    "low_vol_60d": 60,
    "quality_proxy": 1,
}


def _ret(panel: Panel, a: str, i: int, lag: int = 1) -> float:
    if i - lag < 0:
        return 0.0
    prev = panel.close[a][i - lag]
    return panel.close[a][i] / prev - 1.0 if prev else 0.0


def momentum_12_1(panel: Panel, a: str, i: int) -> float | None:
    """t-252 到 t-21 的累计收益（跳过最近 21 个交易日）。"""
    if i < 252:
        return None
    start = panel.close[a][i - 252]
    end = panel.close[a][i - 21]
    if start <= 0:
        return None
    return end / start - 1.0


def value_proxy(panel: Panel, a: str, i: int) -> float | None:
    """B/P：账面价值 / 收盘价，数值越大越"便宜"。"""
    px = panel.close[a][i]
    if px <= 0:
        return None
    return panel.book[a][i] / px


def low_vol_60d(panel: Panel, a: str, i: int) -> float | None:
    """过去 60 个交易日日收益标准差，取负号（低波动得分更高）。"""
    if i < 60:
        return None
    rets = [_ret(panel, a, j) for j in range(i - 59, i + 1)]
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return -math.sqrt(var)


def quality_proxy(panel: Panel, a: str, i: int) -> float | None:
    """ROE 代理：TTM 盈利 / 账面价值。"""
    bv = panel.book[a][i]
    if bv <= 0:
        return None
    return panel.earnings[a][i] / bv


FACTOR_FUNCS = {
    "momentum_12_1": momentum_12_1,
    "value_proxy": value_proxy,
    "low_vol_60d": low_vol_60d,
    "quality_proxy": quality_proxy,
}


def _check_registry() -> None:
    """三处登记必须一致：函数表、预热表、spec.FACTORS。

    加因子最容易漏的就是其中一处——漏了不会报错，只会让校验/枚举悄悄失真。
    这里在导入时就炸掉，把问题挡在第一次回测之前。
    """
    from .spec import FACTORS as SPEC_FACTORS

    missing_history = sorted(set(FACTOR_FUNCS) - set(MIN_HISTORY))
    missing_func = sorted(set(MIN_HISTORY) - set(FACTOR_FUNCS))
    missing_spec = sorted(set(FACTOR_FUNCS) - set(SPEC_FACTORS))
    extra_spec = sorted(set(SPEC_FACTORS) - set(FACTOR_FUNCS))
    problems = []
    if missing_history:
        problems.append(f"缺少 MIN_HISTORY 登记：{missing_history}")
    if missing_func:
        problems.append(f"MIN_HISTORY 里有未实现的因子：{missing_func}")
    if missing_spec:
        problems.append(f"spec.FACTORS 里缺少：{missing_spec}")
    if extra_spec:
        problems.append(f"spec.FACTORS 里有未实现的因子：{extra_spec}")
    if problems:
        raise RuntimeError("因子登记不一致：" + "；".join(problems))


_check_registry()


def scores(panel: Panel, factor: str, i: int) -> dict[str, float]:
    """返回 {asset: score}；历史不足的资产直接缺席（不参与当日排名）。"""
    fn = FACTOR_FUNCS[factor]
    out: dict[str, float] = {}
    for a in panel.assets:
        val = fn(panel, a, i)
        if val is not None and math.isfinite(val):
            out[a] = val
    return out


def rank_desc(series: dict[str, float]) -> list[str]:
    """按得分降序排名；同分用代码升序打破，保证确定性。"""
    return [a for a, _ in sorted(series.items(), key=lambda kv: (-kv[1], kv[0]))]


def _ranks(series: dict[str, float]) -> dict[str, float]:
    """平均秩（并列取平均），用于 Spearman 相关。"""
    order = sorted(series.items(), key=lambda kv: (kv[1], kv[0]))
    ranks: dict[str, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k][0]] = avg
        i = j + 1
    return ranks


def spearman(x: dict[str, float], y: dict[str, float]) -> float | None:
    """两个打分字典在同一批资产上的 Spearman 秩相关。"""
    common = sorted(set(x) & set(y))
    if len(common) < 3:
        return None
    rx = _ranks({a: x[a] for a in common})
    ry = _ranks({a: y[a] for a in common})
    n = len(common)
    mx = sum(rx.values()) / n
    my = sum(ry.values()) / n
    num = sum((rx[a] - mx) * (ry[a] - my) for a in common)
    dx = math.sqrt(sum((rx[a] - mx) ** 2 for a in common))
    dy = math.sqrt(sum((ry[a] - my) ** 2 for a in common))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)
