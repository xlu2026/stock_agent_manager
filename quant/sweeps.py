"""参数网格与多重检验：把"扫一遍参数"变成可复现的确定性流程。

只做两件事：
1. 把 base spec + axes 展开成一组 spec；
2. 对结果做 Bonferroni / Benjamini-Hochberg 校正，提醒"最好看的那个"可能只是
   在 N 次试验里挑出来的。

实际执行仍走 Agent 1（登记实验、固定数据版本），这里不直接调 engine。
"""
from __future__ import annotations

import copy
import math
from typing import Any


def _set_path(target: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def expand_grid(base: dict, axes: dict[str, list]) -> list[dict]:
    """axes 的 key 支持点路径，例如 params.lookback。"""
    specs = [copy.deepcopy(base)]
    for path, values in axes.items():
        next_specs = []
        for spec in specs:
            for value in values:
                clone = copy.deepcopy(spec)
                _set_path(clone, path, value)
                next_specs.append(clone)
        specs = next_specs
    return specs


def _normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def sharpe_pvalue(sharpe: float, years: float) -> float:
    """近似：t = Sharpe * sqrt(years)，按正态双侧。"""
    if years <= 0:
        return 1.0
    return _normal_two_sided_p(sharpe * math.sqrt(years))


def bh_qvalues(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg q-value，保持输入顺序。"""
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvalues[i])
    q = [1.0] * n
    prev = 1.0
    for rank in range(n, 0, -1):
        idx = order[rank - 1]
        val = min(prev, pvalues[idx] * n / rank)
        q[idx] = max(0.0, min(1.0, val))
        prev = q[idx]
    return q


def summarize(results: list[dict]) -> dict:
    """results: [{name, experiment_id, metrics}]；返回排序、p/q、显著性。"""
    rows = []
    for item in results:
        m = item.get("metrics") or {}
        years = float(m.get("trading_days") or 0) / 252.0
        sharpe = float(m.get("sharpe") or 0.0)
        rows.append(
            {
                "name": item.get("name"),
                "experiment_id": item.get("experiment_id"),
                "cagr": m.get("cagr"),
                "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "excess_cagr": m.get("excess_cagr"),
                "p_value": round(sharpe_pvalue(sharpe, years), 6),
            }
        )
    qs = bh_qvalues([r["p_value"] for r in rows])
    for row, q in zip(rows, qs):
        row["bh_q"] = round(q, 6)
        row["bonferroni_alpha"] = round(0.05 / max(len(rows), 1), 6)
        row["significant_after_bh"] = q <= 0.05
    rows.sort(key=lambda r: (r.get("cagr") is None, -(r.get("cagr") or 0)))
    return {
        "n_trials": len(rows),
        "best": rows[0] if rows else None,
        "rows": rows,
        "warning": "N 次试验后的最优结果需要多重检验校正；BH 显著也不等于可实盘",
    }
