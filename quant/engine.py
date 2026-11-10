"""确定性回测引擎。

关键不变量（对应简报第 4 节）：
1. 前视偏差：建仓日 t 的因子只用 ``t-1`` 及以前的数据计算；
2. 确定性：不使用 wall clock、不用随机数，同 spec + 同数据快照 => 同 nav_hash；
3. LLM 不进入盈亏回路：本模块不接收任何自然语言输入，只接收 Spec；
4. 交易成本显式建模，换手按单边计。
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date

from . import factors
from .data import Panel, assert_universe, load_panel
from .spec import Spec

ENGINE_VERSION = "engine-0.1.0"
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------- 时间与小工具


def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


def _period_key(d: str, rebalance: str) -> tuple[int, int]:
    dt = _parse(d)
    if rebalance == "W":
        iso = dt.isocalendar()
        return (iso[0], iso[1])
    if rebalance == "M":
        return (dt.year, dt.month)
    if rebalance == "Q":
        return (dt.year, (dt.month - 1) // 3 + 1)
    raise ValueError(f"unknown rebalance {rebalance}")


def _rebalance_indices(panel: Panel, start_idx: int, end_idx: int, rebalance: str) -> list[int]:
    """区间内每个周期最后一个交易日。"""
    out: list[int] = []
    for i in range(start_idx, end_idx + 1):
        if i == end_idx:
            out.append(i)
            break
        if _period_key(panel.dates[i], rebalance) != _period_key(panel.dates[i + 1], rebalance):
            out.append(i)
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def _max_drawdown(nav: list[float]) -> float:
    peak = nav[0] if nav else 1.0
    mdd = 0.0
    for v in nav:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def _nav_hash(dates: list[str], nav: list[float]) -> str:
    h = hashlib.sha256()
    for d, v in zip(dates, nav):
        h.update(f"{d},{v:.10f}\n".encode("utf-8"))
    return h.hexdigest()


def _scores_on(panel: Panel, factor: str, i: int) -> dict[str, float]:
    """只给"第 i 日仍在池内"的标的打分。

    没有 universe.csv 时（v1 合成数据）等价于全池打分，结果逐位不变；
    有 universe.csv 时，还没上市/已经退出的标的不会进入当日排名——这正是
    时点成分股存在的意义。
    """
    scored = factors.scores(panel, factor, i)
    allowed = panel.allowed_at(i)
    if allowed is None:
        return scored
    return {a: v for a, v in scored.items() if a in allowed}


# ------------------------------------------------------------------- 回测主体


@dataclass
class Backtest:
    spec: Spec
    experiment_id: str
    data_version: str
    dates: list[str]
    nav: list[float]
    benchmark_nav: list[float]
    metrics: dict
    holdings: list[dict]
    rebalance_days: list[str]
    provenance: dict

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "spec": self.spec.canonical(),
            "data_version": self.data_version,
            "metrics": self.metrics,
            "holdings_count": len(self.holdings),
            "rebalances": len(self.rebalance_days),
            "provenance": self.provenance,
            "nav_series": {"dates": self.dates, "nav": self.nav},
            "benchmark_series": {"dates": self.dates, "nav": self.benchmark_nav},
        }


def experiment_id_for(spec: Spec, panel: Panel) -> str:
    """实验 ID 由 spec + 数据快照确定：同样输入永远得到同一个 ID。"""
    return "exp-" + spec.fingerprint(panel.data_sha256)[:12]


def run_backtest(spec: Spec) -> Backtest:
    panel = load_panel()
    assert_universe(panel, spec.universe)

    if spec.data_version and spec.data_version != panel.data_version:
        raise ValueError(
            f"spec 指定的 data_version={spec.data_version} 与当前快照 "
            f"{panel.data_version} 不一致；拒绝在未固定的数据上回测"
        )

    start_idx = panel.index_of(spec.start)
    end_idx = panel.index_of(spec.end)
    if end_idx == -1 or panel.dates[end_idx] > spec.end:
        end_idx -= 1
    if start_idx >= end_idx:
        raise ValueError(f"回测区间 {spec.start}..{spec.end} 内交易日不足")

    dates = panel.dates[start_idx : end_idx + 1]
    n = len(dates)
    assets = panel.assets

    reb_idx = _rebalance_indices(panel, start_idx, end_idx, spec.rebalance)

    # ---- 逐日净值：t 日收盘后的收益用 t-1 已持有的权重计算；
    # 调仓发生在 t 日收盘（信号来 t-1 日），成本在 t 日一次性扣除。
    nav = [1.0] * n
    weights: dict[str, float] = {}
    holdings: list[dict] = []
    total_turnover = 0.0
    gross_exposure_sum = 0.0

    reb_set = {i - start_idx for i in reb_idx}

    for j in range(1, n):
        prev_weights = weights
        i = start_idx + j

        # 1) 用上一交易日持有的权重吃当日涨跌
        if prev_weights:
            r = 0.0
            for a, w in prev_weights.items():
                prev_close = panel.close[a][i - 1]
                if prev_close > 0:
                    r += w * (panel.close[a][i] / prev_close - 1.0)
            nav[j] = nav[j - 1] * (1.0 + r)
        else:
            nav[j] = nav[j - 1]

        # 2) 若今天是调仓日，按 t-1 信号换仓并扣成本
        if j in reb_set:
            sig_idx = i - 1
            sc = _scores_on(panel, spec.factor, sig_idx)
            if len(sc) >= spec.top_k:
                picked = factors.rank_desc(sc)[: spec.top_k]
                new_w = {a: 1.0 / len(picked) for a in picked}
                turnover = 0.5 * sum(
                    abs(new_w.get(a, 0.0) - prev_weights.get(a, 0.0))
                    for a in set(new_w) | set(prev_weights)
                )
                cost = turnover * spec.cost_bps / 1e4
                nav[j] *= 1.0 - cost
                total_turnover += turnover
                weights = new_w
                holdings.append(
                    {
                        "date": panel.dates[i],
                        "signal_date": panel.dates[sig_idx],
                        "fill_price": "next_open",
                        "turnover": round(turnover, 6),
                        "cost_bps": spec.cost_bps,
                        "names": picked,
                        "count": len(picked),
                    }
                )
        gross_exposure_sum += sum(weights.values())

    # ---- 基准：当日有效池等权、每日再平衡、零成本
    bench = [1.0] * n
    for j in range(1, n):
        i = start_idx + j
        allowed = panel.allowed_at(i)
        rs = []
        for a in assets:
            if allowed is not None and a not in allowed:
                continue
            pc = panel.close[a][i - 1]
            if pc > 0:
                rs.append(panel.close[a][i] / pc - 1.0)
        bench[j] = bench[j - 1] * (1.0 + _mean(rs))

    daily = [nav[j] / nav[j - 1] - 1.0 for j in range(1, n)]
    years = max((_parse(dates[-1]) - _parse(dates[0])).days / 365.25, 1e-9)
    cagr = nav[-1] ** (1.0 / years) - 1.0 if nav[-1] > 0 else -1.0
    b_cagr = bench[-1] ** (1.0 / years) - 1.0 if bench[-1] > 0 else -1.0
    vol = _stdev(daily) * math.sqrt(TRADING_DAYS_PER_YEAR)
    mdd = _max_drawdown(nav)

    month_rets: dict[str, list[float]] = {}
    for j in range(1, n):
        month_rets.setdefault(dates[j][:7], []).append(daily[j - 1])
    monthly = [math.prod([1.0 + x for x in v]) - 1.0 for v in month_rets.values()]
    win_rate = (sum(1 for x in monthly if x > 0) / len(monthly)) if monthly else 0.0

    metrics = {
        "total_return": round(nav[-1] - 1.0, 6),
        "cagr": round(cagr, 6),
        "annual_volatility": round(vol, 6),
        "sharpe": round((_mean(daily) / _stdev(daily) * math.sqrt(TRADING_DAYS_PER_YEAR))
                        if _stdev(daily) else 0.0, 4),
        "max_drawdown": round(mdd, 6),
        "calmar": round((cagr / abs(mdd)) if mdd else 0.0, 4),
        "monthly_win_rate": round(win_rate, 4),
        "annual_turnover": round(total_turnover / years, 4),
        "avg_exposure": round(gross_exposure_sum / max(n - 1, 1), 4),
        "trading_days": n,
        "n_rebalances": len(holdings),
        "benchmark_total_return": round(bench[-1] - 1.0, 6),
        "benchmark_cagr": round(b_cagr, 6),
        "excess_cagr": round(cagr - b_cagr, 6),
        "nav_hash": _nav_hash(dates, nav),
    }

    return Backtest(
        spec=spec,
        experiment_id=experiment_id_for(spec, panel),
        data_version=panel.data_version,
        dates=dates,
        nav=[round(v, 10) for v in nav],
        benchmark_nav=[round(v, 10) for v in bench],
        metrics=metrics,
        holdings=holdings,
        rebalance_days=[h["date"] for h in holdings],
        provenance={
            "engine_version": ENGINE_VERSION,
            "data_version": panel.data_version,
            "data_sha256": panel.data_sha256,
            "spec_fingerprint": spec.fingerprint(panel.data_sha256),
            "lookahead_guard": "signal_date = fill_date - 1 trading day",
            "cost_model": "one-way turnover * cost_bps",
            "deterministic": True,
            # 数据来源不能由调用方口述，只能来自快照自己的 manifest：
            # 合成数据和真实数据的区别必须随实验记录一起落盘。
            "data_source": panel.source,
            "data_provider": panel.provider,
            "data_schema_version": panel.schema_version,
            "data_adjust_mode": panel.adjust_mode,
            "data_universe_point_in_time": panel.has_point_in_time_universe(),
            "data_filled_rows": panel.filled_rows,
            "data_notes": panel.notes,
        },
    )


# --------------------------------------------------------------- 因子分析


def run_factor_analysis(spec: Spec, quantiles: int = 5) -> dict:
    """IC 与分位收益：衡量因子截面预测力，不做任何组合优化。"""
    panel = load_panel()
    assert_universe(panel, spec.universe)

    start_idx = panel.index_of(spec.start)
    end_idx = panel.index_of(spec.end)
    if end_idx == -1 or panel.dates[end_idx] > spec.end:
        end_idx -= 1
    reb_idx = _rebalance_indices(panel, start_idx, end_idx, spec.rebalance)

    ic_series: list[dict] = []
    buckets: list[list[float]] = [[] for _ in range(quantiles)]

    for k in range(len(reb_idx) - 1):
        t, nxt = reb_idx[k], reb_idx[k + 1]
        sig = _scores_on(panel, spec.factor, t)
        allowed = panel.allowed_at(t)
        fwd = {}
        for a in panel.assets:
            if allowed is not None and a not in allowed:
                continue
            p0, p1 = panel.close[a][t], panel.close[a][nxt]
            if p0 > 0:
                fwd[a] = p1 / p0 - 1.0
        rho = factors.spearman(sig, fwd)
        if rho is not None:
            ic_series.append({"date": panel.dates[t], "rank_ic": round(rho, 6)})

        common = sorted(set(sig) & set(fwd))
        if len(common) >= quantiles:
            ordered = sorted(common, key=lambda a: (sig[a], a))
            size = len(ordered) / quantiles
            for qi in range(quantiles):
                lo = int(round(qi * size))
                hi = int(round((qi + 1) * size)) if qi < quantiles - 1 else len(ordered)
                members = ordered[lo:hi]
                if members:
                    buckets[qi].append(_mean([fwd[a] for a in members]))

    ics = [x["rank_ic"] for x in ic_series]
    ic_mean = _mean(ics)
    ic_std = _stdev(ics)
    icir = (ic_mean / ic_std) if ic_std else 0.0
    t_stat = (ic_mean / (ic_std / math.sqrt(len(ics)))) if ic_std and ics else 0.0

    q_means = [_mean(b) for b in buckets]
    spread = (q_means[-1] - q_means[0]) if len(q_means) >= 2 else 0.0
    monotonic = all(q_means[i] <= q_means[i + 1] for i in range(len(q_means) - 1))

    return {
        "spec": spec.canonical(),
        "data_version": panel.data_version,
        "factor": spec.factor,
        "periods": len(ic_series),
        "ic_mean": round(ic_mean, 6),
        "ic_std": round(ic_std, 6),
        "ic_ir": round(icir, 4),
        "ic_t_stat": round(t_stat, 4),
        "ic_positive_ratio": round(
            sum(1 for x in ics if x > 0) / len(ics) if ics else 0.0, 4
        ),
        "quantile_forward_returns": [round(x, 6) for x in q_means],
        "top_minus_bottom": round(spread, 6),
        "monotonic": monotonic,
        "ic_series": ic_series[-24:],
        "note": "IC 基于合成样本数据，仅用于验证分析链路，不代表真实预测力。",
    }
