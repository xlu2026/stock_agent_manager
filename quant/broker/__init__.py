"""券商通道抽象层。

对外的名字只有 `Broker` 契约和 `PaperBroker` 实现。真实券商适配器将来放在
本包内（例如 ``ib.py`` / ``qmt.py``），实现同一套契约，调用方不改。
"""
from .base import (
    AccountSnapshot,
    Broker,
    OrderRecord,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    RejectReason,
    RiskLimits,
    Side,
)
from .paper import PaperBroker, price_from_panel

__all__ = [
    "AccountSnapshot",
    "Broker",
    "OrderRecord",
    "OrderRequest",
    "OrderStatus",
    "OrderType",
    "Position",
    "RejectReason",
    "RiskLimits",
    "Side",
    "PaperBroker",
    "price_from_panel",
]
