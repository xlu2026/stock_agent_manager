"""模拟盘（Paper Session）：用历史数据回放一次"如果今天上线会怎样"。

这是 Agent 1 的"部署验证"技能：只产出模拟成交台账，**没有任何实盘下单路径**。
本模块不 import 任何券商/交易网关，也不存在 live_submit_order 之类的函数。
"""
from __future__ import annotations

from .data import load_panel
from .engine import run_backtest
from .spec import Spec


def run_paper_session(spec: Spec, sessions: int = 6, capital: float = 100_000.0) -> dict:
    panel = load_panel()
    bt = run_backtest(spec)
    recent = bt.holdings[-max(1, min(sessions, len(bt.holdings))) :]

    nav_by_date = dict(zip(bt.dates, bt.nav))
    ledger: list[dict] = []
    prev: dict[str, float] = {}

    for h in recent:
        names = h["names"]
        weight = 1.0 / len(names) if names else 0.0
        target = {a: weight for a in names}
        i = panel.dates.index(h["date"])
        fill_idx = min(i, len(panel.dates) - 1)
        # 当日净值 × 假设本金 = 当日组合市值（真金白银口径）
        portfolio_value = nav_by_date.get(h["date"], 1.0) * capital

        for a in sorted(set(target) | set(prev)):
            delta = target.get(a, 0.0) - prev.get(a, 0.0)
            if abs(delta) < 1e-9:
                continue
            px = panel.open[a][fill_idx]
            ledger.append(
                {
                    "session_date": h["date"],
                    "symbol": a,
                    "side": "BUY" if delta > 0 else "SELL",
                    "delta_weight": round(delta, 6),
                    "fill_price": round(px, 4),
                    "notional": round(abs(delta) * portfolio_value, 2),
                    "shares": int(round(abs(delta) * portfolio_value / px)) if px else 0,
                    "fill_model": "historical_open",
                }
            )
        prev = target

    return {
        "mode": "PAPER",
        "broker": "SIMULATED",
        "assumed_capital": capital,
        "live_orders": False,
        "live_submit_order": "unavailable_by_design",
        "sessions_replayed": len(recent),
        "experiment_id": bt.experiment_id,
        "fills": ledger,
        "fill_count": len(ledger),
        "notional_total": round(sum(x["notional"] for x in ledger), 4),
        "replay_window": {
            "first": recent[0]["date"] if recent else None,
            "last": recent[-1]["date"] if recent else None,
        },
        "caveat": "历史回放模拟，不含滑点与流动性冲击，不代表未来可实现收益。",
    }
