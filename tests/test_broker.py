"""券商抽象层的测试：确认闸门、风控上限、幂等、审计落盘。

这里全部对着 PaperBroker 跑——它是契约的第一个实现，
真实适配器接入时，这些断言应该保持成立（换一个 broker 实现即可）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker import (  # noqa: E402
    Broker,
    OrderRequest,
    OrderStatus,
    OrderType,
    PaperBroker,
    RejectReason,
    RiskLimits,
    Side,
    ledger,
)


def make_broker(**kw) -> PaperBroker:
    prices = {"SYN001": 10.0, "SYN002": 50.0}
    defaults = dict(
        price_of=lambda s: prices.get(s),
        cash=100_000.0,
        limits=RiskLimits(max_order_notional=20_000, max_daily_orders=5, max_position_value=50_000),
        ledger_name="test_orders",
    )
    defaults.update(kw)
    return PaperBroker(**defaults)


class BrokerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="nfr-broker-")
        cls._old = os.environ.get("NFR_BROKER_DIR")
        os.environ["NFR_BROKER_DIR"] = cls._tmp

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old is None:
            os.environ.pop("NFR_BROKER_DIR", None)
        else:
            os.environ["NFR_BROKER_DIR"] = cls._old
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        for f in os.listdir(self._tmp):
            os.remove(os.path.join(self._tmp, f))


class ConfirmationGateTests(BrokerTestBase):
    def test_unconfirmed_is_rejected(self) -> None:
        b = make_broker()
        rec = b.submit(OrderRequest("o-1", "SYN001", Side.BUY, 100, human_confirmed=False))
        self.assertIs(rec.status, OrderStatus.REJECTED)
        self.assertIs(rec.reject_reason, RejectReason.NOT_CONFIRMED)
        self.assertEqual(b.account().positions, [])

    def test_confirmed_fills(self) -> None:
        b = make_broker()
        rec = b.submit(OrderRequest("o-2", "SYN001", Side.BUY, 100, human_confirmed=True))
        self.assertIs(rec.status, OrderStatus.FILLED)
        self.assertEqual(rec.filled_price, 10.0)
        self.assertEqual(rec.filled_quantity, 100)
        self.assertGreater(rec.fee, 0)
        self.assertEqual(b.positions()[0].quantity, 100)
        self.assertLess(b.account().cash, 100_000)

    def test_disabled_broker_rejects(self) -> None:
        b = make_broker(enabled=False)
        rec = b.submit(OrderRequest("o-3", "SYN001", Side.BUY, 100, human_confirmed=True))
        self.assertIs(rec.reject_reason, RejectReason.BROKER_DISABLED)


class RiskLimitTests(BrokerTestBase):
    def test_order_notional_cap(self) -> None:
        b = make_broker()
        # 50 元的标的买 500 股 = 25000，超过 20000 上限
        rec = b.submit(OrderRequest("o-4", "SYN002", Side.BUY, 500, human_confirmed=True))
        self.assertIs(rec.status, OrderStatus.REJECTED)
        self.assertIs(rec.reject_reason, RejectReason.ORDER_NOTIONAL)

    def test_daily_order_count_cap(self) -> None:
        b = make_broker()
        for i in range(5):
            b.submit(OrderRequest(f"o-d{i}", "SYN001", Side.BUY, 10, human_confirmed=True))
        rec = b.submit(OrderRequest("o-d99", "SYN001", Side.BUY, 10, human_confirmed=True))
        self.assertIs(rec.reject_reason, RejectReason.DAILY_ORDER_COUNT)

    def test_insufficient_cash(self) -> None:
        b = make_broker(cash=100.0)
        rec = b.submit(OrderRequest("o-5", "SYN001", Side.BUY, 100, human_confirmed=True))
        self.assertIs(rec.reject_reason, RejectReason.INSUFFICIENT_CASH)

    def test_oversell_rejected(self) -> None:
        b = make_broker()
        rec = b.submit(OrderRequest("o-6", "SYN001", Side.SELL, 100, human_confirmed=True))
        self.assertIs(rec.reject_reason, RejectReason.INSUFFICIENT_POSITION)


class IdempotencyTests(BrokerTestBase):
    def test_duplicate_client_order_id(self) -> None:
        b = make_broker()
        first = b.submit(OrderRequest("dup-1", "SYN001", Side.BUY, 10, human_confirmed=True))
        second = b.submit(OrderRequest("dup-1", "SYN001", Side.BUY, 10, human_confirmed=True))
        self.assertIs(first.status, OrderStatus.FILLED)
        self.assertIs(second.reject_reason, RejectReason.DUP_ORDER_ID)


class LimitOrderTests(BrokerTestBase):
    def test_unfilled_limit_stays_pending_then_cancels(self) -> None:
        b = make_broker()
        # 限价 9 元买 10 元的东西——不该成交
        rec = b.submit(
            OrderRequest("lim-1", "SYN001", Side.BUY, 10, OrderType.LIMIT, limit_price=9.0, human_confirmed=True)
        )
        self.assertIs(rec.status, OrderStatus.PENDING)
        self.assertEqual(b.positions(), [])
        cancelled = b.cancel("lim-1")
        self.assertIsNotNone(cancelled)
        self.assertIs(cancelled.status, OrderStatus.CANCELLED)

    def test_limit_without_price_rejected(self) -> None:
        b = make_broker()
        rec = b.submit(
            OrderRequest("lim-2", "SYN001", Side.BUY, 10, OrderType.LIMIT, limit_price=None, human_confirmed=True)
        )
        self.assertIs(rec.reject_reason, RejectReason.MISSING_LIMIT_PRICE)


class AuditTests(BrokerTestBase):
    def test_ledger_has_audit_fields(self) -> None:
        b = make_broker()
        b.submit(
            OrderRequest(
                "audit-1", "SYN001", Side.BUY, 100, experiment_id="exp-abc123def456", human_confirmed=True
            )
        )
        rows = ledger.read_all("test_orders")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for key in (
            "client_order_id",
            "symbol",
            "side",
            "quantity",
            "filled_price",
            "fee",
            "created_utc",
            "experiment_id",
            "human_confirmed",
        ):
            self.assertIn(key, row)
        self.assertEqual(row["experiment_id"], "exp-abc123def456")
        self.assertTrue(row["human_confirmed"])

    def test_rejected_orders_are_also_audited(self) -> None:
        b = make_broker()
        b.submit(OrderRequest("audit-2", "SYN001", Side.BUY, 100, human_confirmed=False))
        rows = ledger.read_all("test_orders")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "REJECTED")
        self.assertEqual(rows[0]["reject_reason"], "NOT_CONFIRMED")


class ContractTests(BrokerTestBase):
    def test_paper_broker_implements_protocol(self) -> None:
        self.assertIsInstance(make_broker(), Broker)
