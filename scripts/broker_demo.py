"""券商抽象层的演示：走一遍"下单 -> 成交 -> 持仓 -> 审计"的完整链路。

    python scripts/broker_demo.py

用的是 `PaperBroker`：按数据快照的收盘价成交，只记账，不接触任何真实资金。
真实券商适配器接入后，调用代码不需要改——只换 broker 实例。

注意：演示里 `human_confirmed=True` 是脚本代填的，只为了让链路走通。
真实使用时这个标记必须来自人的确认动作，不能由模型自己填。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker import OrderRequest, OrderType, PaperBroker, Side, price_from_panel  # noqa: E402
from quant.broker import ledger  # noqa: E402
from quant.console import force_utf8  # noqa: E402
from quant.data import load_panel  # noqa: E402


def main() -> int:
    force_utf8()
    panel = load_panel()
    as_of = panel.dates[-1]
    price_of = price_from_panel(panel, as_of)
    broker = PaperBroker(price_of=price_of, cash=100_000.0, ledger_name="demo_orders")

    # 演示用账本每次清空，避免上一次运行的记录混进来。
    # 真实账本只追加、不重置——这一点由 ledger.append 的写法保证。
    demo_path = ledger.ledger_path("demo_orders")
    if os.path.exists(demo_path):
        os.remove(demo_path)

    print(f"账户初始权益：{broker.account().equity:.2f}（现金 100000.00）")
    print(f"参考价日期：{as_of}\n")

    def qty_for(symbol: str, target_notional: float = 10_000.0) -> int:
        px = price_of(symbol)
        return max(1, int(target_notional / px)) if px else 1

    orders = [
        OrderRequest("demo-001", "SYN001", Side.BUY, qty_for("SYN001"), experiment_id="exp-a359c2d77697", human_confirmed=True),
        OrderRequest("demo-002", "SYN002", Side.BUY, qty_for("SYN002"), experiment_id="exp-a359c2d77697", human_confirmed=True),
        # 未确认的一笔：应当被拒
        OrderRequest("demo-003", "SYN003", Side.BUY, qty_for("SYN003"), human_confirmed=False),
        # 限价单：故意挂低，应当保持挂单
        OrderRequest(
            "demo-004", "SYN004", Side.BUY, 100, OrderType.LIMIT, limit_price=0.01, human_confirmed=True
        ),
    ]

    for order in orders:
        rec = broker.submit(order)
        reason = rec.reject_reason.value if rec.reject_reason else "-"
        notional = (rec.filled_price or price_of(order.symbol) or 0) * order.quantity
        print(
            f"{rec.client_order_id:>9}  {rec.symbol:<7} {rec.side.value:<4} {rec.quantity:>4} 股 "
            f"约 {notional:>10.0f} 元 -> {rec.status.value:<8} 原因={reason:<16} 成交价={rec.filled_price}"
        )

    # 卖出一半 SYN001，演示 SELL 路径（含印花税）
    held = next((p.quantity for p in broker.positions() if p.symbol == "SYN001"), 0)
    if held >= 2:
        sell = broker.submit(
            OrderRequest("demo-005", "SYN001", Side.SELL, held // 2, experiment_id="exp-a359c2d77697", human_confirmed=True)
        )
        print(
            f"{sell.client_order_id:>9}  {sell.symbol:<7} {sell.side.value:<4} {sell.quantity:>4} 股 "
            f"约 {(sell.filled_price or 0) * sell.quantity:>10.0f} 元 -> {sell.status.value:<8} 手续费={sell.fee:.2f}"
        )

    acct = broker.account()
    print(f"\n账户权益：{acct.equity:.2f}  现金：{acct.cash:.2f}")
    print("持仓：")
    for pos in acct.positions:
        print(f"  {pos.symbol:<7} {pos.quantity:>4} 股  成本 {pos.avg_cost:.4f}  市值 {pos.market_value:.2f}")

    rows = ledger.read_all("demo_orders")
    print(f"\n审计账本：{os.path.relpath(ledger.ledger_path('demo_orders'), ROOT)}  共 {len(rows)} 条")
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
