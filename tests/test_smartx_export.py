"""SmartX 自动导出 CSV 的解析与对账测试。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker.smartx_export import (  # noqa: E402
    SmartxExportError,
    archive,
    load_export,
    load_proposals,
    reconcile,
    status_class,
)

ORDER_HEADER = [
    "资金账号", "方向", "证券代码", "证券名称", "市场", "报单状态", "价格条件", "委托价格",
    "委托数量", "成交数量", "剩余数量", "成交金额", "委托时间", "撤销时间", "错误原因",
    "错误ID", "ID", "柜台委托编号", "OrderClientId", "渠道", "rowId", "业务类型",
    "开平标志", "runtimeId",
]
TRADE_HEADER = [
    "资金账号", "ID", "代码", "证券名称", "市场", "成交编号", "方向", "成交价格",
    "成交数量", "成交序号", "成交时间", "成交金额", "成交类型", "业务类型", "交易员代码",
    "OrderClientId", "渠道", "rowId", "开平标志", "runtimeId",
]
POSITION_HEADER = [
    "资金账号", "证券代码", "证券名称", "总持仓", "可卖持仓", "参考市值", "现价", "涨幅",
    "当日盈亏", "参考盈亏", "参考盈亏率", "参考持仓成本", "参考成本价", "可申赎数量",
    "持仓方向", "市场",
]
ASSET_HEADER = [
    "资金账号", "总资产(含市值)", "可用资金", "净资产", "总市值", "回购总市值",
    "预扣资金", "买入资金", "买入费用", "卖出资金", "卖出费用",
]

ORDER_ROWS = [
    [
        "\tTEST", "1", "600000", "测试股", "XTP_MKT_SH_A", "已成交", "限价", "10.00",
        "100", "100", "0", "1000.00", "2026-11-12 09:31:00", "", "", "", "111",
        "C1", "CL1", "csv", "prop-aaa", "0", "0", "r1",
    ],
    [
        "\tTEST", "2", "000001", "测试二", "XTP_MKT_SZ_A", "已拒绝", "限价", "11.00",
        "200", "0", "200", "0.00", "2026-11-12 09:32:00", "", "价格超出涨跌停范围",
        "E100", "112", "C2", "CL2", "csv", "prop-bbb", "0", "0", "r2",
    ],
]
TRADE_ROWS = [
    ["\tTEST", "111", "600000", "测试股", "XTP_MKT_SH_A", "T1", "1", "10.00", "100",
     "1", "2026-11-12 09:31:05", "1000.00", "成交", "0", "", "CL1", "csv", "prop-aaa", "0", "r1"],
]
POSITION_ROWS = [
    ["\tTEST", "600000", "测试股", "100", "100", "1000.00", "10.00", "1.00%",
     "0.00", "0.00", "0.00%", "1000.00", "10.00", "100", "净", "XTP_MKT_SH_A"],
]
ASSET_ROWS = [
    ["\tTEST", "100000.00", "50000.00", "100000.00", "1000.00", "0.00", "0.00",
     "0.00", "0.00", "0.00", "0.00"],
]


def _write(path: str, header: list[str], rows: list[list[str]], bom: bool = False) -> None:
    text = "\n".join([",".join(header)] + [",".join(row) for row in rows]) + "\n"
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as fh:
        fh.write(data)


def _fixture(directory: str, account: str = "TEST") -> None:
    _write(os.path.join(directory, f"xtp_{account}_Order.csv"), ORDER_HEADER, ORDER_ROWS, bom=True)
    _write(os.path.join(directory, f"xtp_{account}_Trade.csv"), TRADE_HEADER, TRADE_ROWS)
    _write(os.path.join(directory, f"xtp_{account}_Position.csv"), POSITION_HEADER, POSITION_ROWS)
    _write(os.path.join(directory, f"xtp_{account}_Asset.csv"), ASSET_HEADER, ASSET_ROWS)


class StatusTests(unittest.TestCase):
    def test_status_class(self) -> None:
        self.assertEqual(status_class("已成交"), "filled")
        self.assertEqual(status_class("部分成交"), "partial")
        self.assertEqual(status_class("已撤"), "cancelled")
        self.assertEqual(status_class("已拒绝"), "rejected")
        self.assertEqual(status_class("未成交"), "open")
        self.assertEqual(status_class("奇怪的"), "unknown")


class LoadExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="smartx-export-")
        _fixture(self.dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_parses_all_tables(self) -> None:
        export = load_export(self.dir)
        self.assertEqual(export.account, "TEST")
        self.assertEqual(len(export.orders), 2)
        self.assertEqual(len(export.trades), 1)
        self.assertEqual(len(export.positions), 1)
        self.assertEqual(export.asset["available"], 50000.0)
        first = export.orders[0]
        self.assertEqual(first["id"], "111")
        self.assertEqual(first["status_class"], "filled")
        self.assertEqual(first["quantity"], 100)
        self.assertEqual(first["row_id"], "prop-aaa")
        self.assertEqual(export.positions[0]["symbol"], "600000")

    def test_summary_reports_rejections(self) -> None:
        summary = load_export(self.dir).summary()
        self.assertEqual(summary["orders"], 2)
        self.assertEqual(summary["by_status"], {"filled": 1, "rejected": 1})
        self.assertEqual(summary["rejected"][0]["error"], "价格超出涨跌停范围")
        self.assertEqual(summary["filled_amount"], 1000.0)

    def test_missing_directory_raises(self) -> None:
        with self.assertRaises(SmartxExportError):
            load_export(os.path.join(self.dir, "nope"))

    def test_archive_copies_files(self) -> None:
        target = archive(self.dir)
        self.assertTrue(os.path.isdir(target))
        self.assertTrue(os.path.exists(os.path.join(target, "xtp_TEST_Order.csv")))


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="smartx-rec-")
        _fixture(self.dir)
        self.props = os.path.join(self.dir, "proposals")
        os.makedirs(self.props)
        for pid, symbol in (("prop-aaa", "600000"), ("prop-zzz", "000002")):
            with open(os.path.join(self.props, f"{pid}.json"), "w", encoding="utf-8") as fh:
                json.dump({"proposal_id": pid, "symbol": symbol, "side": "BUY", "quantity": 100}, fh)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reconcile_matches_by_row_id(self) -> None:
        result = reconcile(load_export(self.dir), load_proposals(self.props))
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["unmatched_proposals"], 1)
        self.assertEqual(result["items"][0]["status_class"], "filled")
        self.assertEqual(len(result["unmatched_orders"]), 1)
        self.assertEqual(result["unmatched_orders"][0]["id"], "112")


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="smartx-cli-")
        _fixture(self.dir)
        self.out = os.path.join(self.dir, "out.json")
        self.proposals = os.path.join(self.dir, "proposals")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cli_writes_json(self) -> None:
        from scripts.reconcile_smartx import main

        code = main(["--dir", self.dir, "--proposals", self.proposals, "--out", self.out])
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as fh:
            result = json.load(fh)
        self.assertEqual(result["summary"]["orders"], 2)


if __name__ == "__main__":
    unittest.main()
