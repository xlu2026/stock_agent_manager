"""模拟券商通道：按给定的参考价成交，只记账，不接触任何真实资金。

它是 ``Broker`` 契约的第一个实现，用途有两个：

1. 让调用方（组合构建、部署验证）**先对着接口写**，而不是对着某家券商的 SDK 写；
2. 把人工确认闸门、风控上限、审计落盘这三件事在"没有风险的环境"里先跑顺，
   等换真通道时，这套检查已经是既成事实，而不是后来补的。

成交模型是确定性的：给定参考价与参数，同样的输入永远得到同样的结果。
"""
from __future__ import annotations

import os
from typing import Callable

from . import ledger
from .base import (
    AccountSnapshot,
    OrderRecord,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    RejectReason,
    RiskLimits,
    Side,
)


class PaperBroker:
    """内存 + 追加账本。没有网络，没有券商凭据，不会碰到真钱。"""

    name = "paper"

    def __init__(
        self,
        *,
        price_of: Callable[[str], float | None],
        cash: float = 100_000.0,
        limits: RiskLimits | None = None,
        commission_bps: float = 2.5,
        min_commission: float = 5.0,
        stamp_duty_bps: float = 10.0,
        ledger_name: str = "paper_orders",
        enabled: bool = True,
    ) -> None:
        self._price_of = price_of
        self._cash = float(cash)
        self._limits = limits or RiskLimits()
        self._commission_bps = commission_bps
        self._min_commission = min_commission
        self._stamp_duty_bps = stamp_duty_bps
        self._ledger_name = ledger_name
        self._enabled = enabled
        self._positions: dict[str, tuple[int, float]] = {}  # symbol -> (qty, avg_cost)
        self._orders: dict[str, OrderRecord] = {}
        self._daily_counts: dict[str, int] = {}

    # ---------------------------------------------------------------- 查询

    def account(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self._cash, positions=self.positions())

    def positions(self) -> list[Position]:
        out: list[Position] = []
        for symbol, (qty, avg_cost) in sorted(self._positions.items()):
            if qty == 0:
                continue
            out.append(
                Position(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=round(avg_cost, 4),
                    last_price=round(self._price_of(symbol) or avg_cost, 4),
                )
            )
        return out

    def order(self, client_order_id: str) -> OrderRecord | None:
        return self._orders.get(client_order_id)

    def quote(self, symbol: str) -> float | None:
        """当前参考价；没有就返回 None，不猜。"""
        price = self._price_of(symbol)
        return float(price) if price and price > 0 else None

    # ---------------------------------------------------------------- 下单

    def submit(self, order: OrderRequest) -> OrderRecord:
        if not self._enabled:
            return self._reject(order, RejectReason.BROKER_DISABLED)

        if not order.human_confirmed:
            return self._reject(order, RejectReason.NOT_CONFIRMED)

        if order.client_order_id in self._orders:
            return self._reject(order, RejectReason.DUP_ORDER_ID)

        if not isinstance(order.quantity, int) or order.quantity <= 0:
            return self._reject(order, RejectReason.BAD_QUANTITY)

        if order.order_type is OrderType.LIMIT and not order.limit_price:
            return self._reject(order, RejectReason.MISSING_LIMIT_PRICE)

        price = self._reference_price(order)
        if price is None:
            return self._reject(order, RejectReason.NO_PRICE)

        # 风控按"最坏成交价"估值：限价单用限价，市价单用参考价
        valuation = price if order.order_type is OrderType.MARKET else float(order.limit_price)
        notional = valuation * order.quantity
        if notional > self._limits.max_order_notional:
            return self._reject(order, RejectReason.ORDER_NOTIONAL)

        today = ledger.utc_now()[:10]
        if self._daily_counts.get(today, 0) >= self._limits.max_daily_orders:
            return self._reject(order, RejectReason.DAILY_ORDER_COUNT)

        fee = self._fee(order, price)

        if order.side is Side.BUY:
            if notional + fee > self._cash:
                return self._reject(order, RejectReason.INSUFFICIENT_CASH)
            current = self._positions.get(order.symbol, (0, 0.0))
            new_value = (current[0] + order.quantity) * price
            if new_value > self._limits.max_position_value:
                return self._reject(order, RejectReason.POSITION_LIMIT)
        else:
            held = self._positions.get(order.symbol, (0, 0.0))[0]
            if order.quantity > held:
                return self._reject(order, RejectReason.INSUFFICIENT_POSITION)

        # LIMIT 未触价 -> 挂单，不动资金
        if order.order_type is OrderType.LIMIT:
            crossed = (order.side is Side.BUY and price <= order.limit_price) or (
                order.side is Side.SELL and price >= order.limit_price
            )
            if not crossed:
                record = self._record(order, OrderStatus.PENDING, 0, None, 0.0)
                self._daily_counts[today] = self._daily_counts.get(today, 0) + 1
                return self._persist(record)

        self._fill(order, price, fee)
        self._daily_counts[today] = self._daily_counts.get(today, 0) + 1
        return self._persist(self._record(order, OrderStatus.FILLED, order.quantity, price, fee))

    def cancel(self, client_order_id: str) -> OrderRecord | None:
        record = self._orders.get(client_order_id)
        if record is None or record.status is not OrderStatus.PENDING:
            return None
        cancelled = self._record(
            OrderRequest(
                client_order_id=record.client_order_id,
                symbol=record.symbol,
                side=record.side,
                quantity=record.quantity,
                order_type=record.order_type,
                limit_price=record.limit_price,
                experiment_id=record.experiment_id,
                human_confirmed=record.human_confirmed,
                note=record.note,
            ),
            OrderStatus.CANCELLED,
            0,
            None,
            0.0,
        )
        return self._persist(cancelled)

    # ---------------------------------------------------------------- 状态持久化

    def dump_state(self) -> dict:
        """进程重启后恢复用。订单本身以账本为准，这里只存账户与内存索引。"""
        return {
            "cash": self._cash,
            "positions": {s: [q, c] for s, (q, c) in self._positions.items()},
            "daily_counts": dict(self._daily_counts),
            "orders": {k: v.as_dict() for k, v in self._orders.items()},
        }

    def apply_state(self, state: dict) -> None:
        self._cash = float(state.get("cash", self._cash))
        self._positions = {s: (int(q), float(c)) for s, (q, c) in state.get("positions", {}).items()}
        self._daily_counts = dict(state.get("daily_counts", {}))
        self._orders = {}
        for key, row in state.get("orders", {}).items():
            self._orders[key] = _record_from_dict(row)

    # ---------------------------------------------------------------- 内部

    def _reference_price(self, order: OrderRequest) -> float | None:
        """参考价永远取市场价；限价只做"是否触价"的闸，不用它当成交价。"""
        price = self._price_of(order.symbol)
        return float(price) if price and price > 0 else None

    def _fee(self, order: OrderRequest, price: float) -> float:
        notional = price * order.quantity
        commission = max(notional * self._commission_bps / 10_000.0, self._min_commission)
        stamp = notional * self._stamp_duty_bps / 10_000.0 if order.side is Side.SELL else 0.0
        return commission + stamp

    def _fill(self, order: OrderRequest, price: float, fee: float) -> None:
        qty, avg = self._positions.get(order.symbol, (0, 0.0))
        if order.side is Side.BUY:
            new_qty = qty + order.quantity
            new_avg = (qty * avg + order.quantity * price) / new_qty
            self._positions[order.symbol] = (new_qty, new_avg)
            self._cash -= price * order.quantity + fee
        else:
            self._positions[order.symbol] = (qty - order.quantity, avg)
            self._cash += price * order.quantity - fee

    def _record(
        self,
        order: OrderRequest,
        status: OrderStatus,
        filled_qty: int,
        filled_price: float | None,
        fee: float,
        reason: RejectReason | None = None,
    ) -> OrderRecord:
        return OrderRecord(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            status=status,
            filled_quantity=filled_qty,
            filled_price=round(filled_price, 4) if filled_price else None,
            fee=fee,
            created_utc=ledger.utc_now(),
            experiment_id=order.experiment_id,
            human_confirmed=order.human_confirmed,
            reject_reason=reason,
            note=order.note,
        )

    def _reject(self, order: OrderRequest, reason: RejectReason) -> OrderRecord:
        return self._persist(self._record(order, OrderStatus.REJECTED, 0, None, 0.0, reason))

    def _persist(self, record: OrderRecord) -> OrderRecord:
        self._orders[record.client_order_id] = record
        ledger.append(record, self._ledger_name)
        return record


def _record_from_dict(row: dict) -> OrderRecord:
    return OrderRecord(
        client_order_id=row["client_order_id"],
        symbol=row["symbol"],
        side=Side(row["side"]),
        quantity=int(row["quantity"]),
        order_type=OrderType(row["order_type"]),
        limit_price=row.get("limit_price"),
        status=OrderStatus(row["status"]),
        filled_quantity=int(row.get("filled_quantity", 0)),
        filled_price=row.get("filled_price"),
        fee=float(row.get("fee", 0.0)),
        created_utc=row.get("created_utc", ""),
        experiment_id=row.get("experiment_id"),
        human_confirmed=bool(row.get("human_confirmed")),
        reject_reason=RejectReason(row["reject_reason"]) if row.get("reject_reason") else None,
        note=row.get("note", ""),
    )


def price_from_panel(panel, date: str) -> Callable[[str], float | None]:
    """用数据快照的收盘价做参考价，方便在历史上回放。"""
    idx = panel.dates.index(date) if date in panel.dates else -1

    def _price(symbol: str) -> float | None:
        series = panel.close.get(symbol)
        if not series or idx < 0:
            return None
        return series[idx]

    return _price
