"""券商通道的抽象层：只定义契约，不接任何真实券商。

设计目标：**先把下单路径的形状定死**，等选定券商时只写一个适配器，
而不是到时候再改调用方。三条硬约束在这一层就焊住，适配器绕不过去：

1. **人工确认闸门**：`OrderRequest.human_confirmed` 为假一律拒单；
2. **风险上限**：单笔名义金额、单日单数、单标的持仓上限；
3. **审计落盘**：每笔订单的时间、标的、方向、数量、价格、实验 ID、确认标记。

本模块不含任何网络调用，也不含券商凭据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"      # 已受理，未成交
    FILLED = "FILLED"
    REJECTED = "REJECTED"    # 风控或参数拒绝
    CANCELLED = "CANCELLED"


class RejectReason(str, Enum):
    NOT_CONFIRMED = "NOT_CONFIRMED"          # 未经人工确认
    BAD_QUANTITY = "BAD_QUANTITY"
    MISSING_LIMIT_PRICE = "MISSING_LIMIT_PRICE"
    NO_PRICE = "NO_PRICE"                    # 拿不到参考价
    DUP_ORDER_ID = "DUP_ORDER_ID"            # 幂等：同一 client_order_id 不可重复提交
    ORDER_NOTIONAL = "ORDER_NOTIONAL"        # 超过单笔上限
    DAILY_ORDER_COUNT = "DAILY_ORDER_COUNT"  # 超过单日单数
    POSITION_LIMIT = "POSITION_LIMIT"        # 超过单标的持仓上限
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    BROKER_DISABLED = "BROKER_DISABLED"      # 通道未启用


@dataclass(frozen=True)
class RiskLimits:
    """风控上限。默认值刻意保守——它们的作用是拦住手滑，不是拦住策略。"""

    max_order_notional: float = 20_000.0
    max_daily_orders: int = 20
    max_position_value: float = 100_000.0


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    experiment_id: str | None = None
    human_confirmed: bool = False
    note: str = ""


@dataclass(frozen=True)
class OrderRecord:
    """订单的完整审计记录。落盘的就是这些字段。"""

    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: float | None
    status: OrderStatus
    filled_quantity: int
    filled_price: float | None
    fee: float
    created_utc: str
    experiment_id: str | None
    human_confirmed: bool
    reject_reason: RejectReason | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "fee": round(self.fee, 6),
            "created_utc": self.created_utc,
            "experiment_id": self.experiment_id,
            "human_confirmed": self.human_confirmed,
            "reject_reason": self.reject_reason.value if self.reject_reason else None,
            "note": self.note,
        }


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    last_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    positions: list[Position] = field(default_factory=list)

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def equity(self) -> float:
        return self.cash + self.market_value


@runtime_checkable
class Broker(Protocol):
    """券商通道契约。真实适配器、模拟盘都实现它，调用方只认这个。"""

    name: str

    def account(self) -> AccountSnapshot: ...

    def positions(self) -> list[Position]: ...

    def submit(self, order: OrderRequest) -> OrderRecord: ...

    def cancel(self, client_order_id: str) -> OrderRecord | None: ...

    def order(self, client_order_id: str) -> OrderRecord | None: ...
