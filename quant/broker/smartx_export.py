"""解析 SmartX 自动导出的交易数据 CSV（只读对账，不产生任何订单）。

SmartX「自动导出设置」每 N 秒把 6 个 CSV 覆盖写到同一个目录：

    xtp_<账号>_Order.csv       委托
    xtp_<账号>_Trade.csv       成交
    xtp_<账号>_Position.csv    持仓
    xtp_<账号>_Asset.csv       资产
    xtp_<账号>_algoList.csv    算法母单
    xtp_<账号>_algoTickerList.csv

它们都是“当前全量快照”，文件名不带日期；对账时要按 `ID`（orderXtpId）合并状态，
按 `成交编号` 合并成交，不能靠“来了一个新文件”判断。
"""
from __future__ import annotations

import csv
import glob
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class SmartxExportError(RuntimeError):
    pass


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(value: Any) -> str:
    return str(value or "").replace("\ufeff", "").strip().strip("\t").strip()


def _rows(path: str) -> list[dict[str, str]]:
    with open(path, "rb") as fh:
        text = _decode(fh.read())
    reader = csv.reader(io.StringIO(text))
    try:
        header = [_clean(cell) for cell in next(reader)]
    except StopIteration:
        return []
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not any(_clean(cell) for cell in raw):
            continue
        rows.append({header[i]: _clean(raw[i]) if i < len(raw) else "" for i in range(len(header))})
    return rows


def _num(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None else None


STATUS_CLASS = {
    "rejected": ("拒绝", "废单"),
    "cancelled": ("已撤", "撤单"),
    "filled": ("已成交", "全部成交"),
    "partial": ("部分成交",),
    "open": ("未成交", "已报", "待报", "正在申报"),
}


def status_class(status: str) -> str:
    text = _clean(status)
    for name, keywords in STATUS_CLASS.items():
        if any(keyword in text for keyword in keywords):
            return name
    return "unknown"


@dataclass
class SmartxExport:
    directory: str
    account: str = ""
    orders: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)
    asset: dict = field(default_factory=dict)
    algo_orders: list[dict] = field(default_factory=list)
    algo_tickers: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for order in self.orders:
            cls = order["status_class"]
            by_status[cls] = by_status.get(cls, 0) + 1
        rejected = [
            {
                "id": order["id"],
                "symbol": order["symbol"],
                "status": order["status"],
                "error": order["error"],
                "error_id": order["error_id"],
                "row_id": order["row_id"],
            }
            for order in self.orders
            if order["status_class"] == "rejected"
        ]
        filled_amount = sum((trade["amount"] or 0.0) for trade in self.trades)
        return {
            "directory": self.directory,
            "account": self.account,
            "orders": len(self.orders),
            "trades": len(self.trades),
            "positions": len(self.positions),
            "by_status": by_status,
            "rejected": rejected,
            "filled_amount": round(filled_amount, 2),
            "asset": self.asset,
            "files": self.files,
        }


def _first_file(directory: str, suffix: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(directory, f"*_{suffix}.csv")))
    return matches[0] if matches else None


def _account_from_name(path: str | None) -> str:
    if not path:
        return ""
    name = os.path.basename(path)
    parts = name.split("_")
    return parts[1] if len(parts) > 1 else ""


def _parse_orders(rows: list[dict[str, str]]) -> list[dict]:
    parsed = []
    for row in rows:
        status = row.get("报单状态", "")
        parsed.append(
            {
                "id": row.get("ID", ""),
                "symbol": row.get("证券代码", ""),
                "name": row.get("证券名称", ""),
                "market": row.get("市场", ""),
                "side": row.get("方向", ""),
                "status": status,
                "status_class": status_class(status),
                "price": _num(row.get("委托价格")),
                "quantity": _int(row.get("委托数量")),
                "filled": _int(row.get("成交数量")),
                "remaining": _int(row.get("剩余数量")),
                "amount": _num(row.get("成交金额")),
                "order_time": row.get("委托时间", ""),
                "cancel_time": row.get("撤销时间", ""),
                "error": row.get("错误原因", ""),
                "error_id": row.get("错误ID", ""),
                "row_id": row.get("rowId", ""),
                "channel": row.get("渠道", ""),
                "client_id": row.get("OrderClientId", ""),
                "business": row.get("业务类型", ""),
            }
        )
    return parsed


def _parse_trades(rows: list[dict[str, str]]) -> list[dict]:
    parsed = []
    for row in rows:
        parsed.append(
            {
                "trade_id": row.get("成交编号", ""),
                "order_id": row.get("ID", ""),
                "symbol": row.get("代码", ""),
                "name": row.get("证券名称", ""),
                "side": row.get("方向", ""),
                "price": _num(row.get("成交价格")),
                "quantity": _int(row.get("成交数量")),
                "amount": _num(row.get("成交金额")),
                "time": row.get("成交时间", ""),
                "row_id": row.get("rowId", ""),
                "channel": row.get("渠道", ""),
            }
        )
    return parsed


def _parse_positions(rows: list[dict[str, str]]) -> list[dict]:
    parsed = []
    for row in rows:
        parsed.append(
            {
                "symbol": row.get("证券代码", ""),
                "name": row.get("证券名称", ""),
                "total": _int(row.get("总持仓")),
                "sellable": _int(row.get("可卖持仓")),
                "market_value": _num(row.get("参考市值")),
                "price": _num(row.get("现价")),
                "pnl": _num(row.get("参考盈亏")),
                "cost_price": _num(row.get("参考成本价")),
            }
        )
    return parsed


def _parse_asset(rows: list[dict[str, str]]) -> dict:
    if not rows:
        return {}
    row = rows[0]
    return {
        "account": row.get("资金账号", ""),
        "total_asset": _num(row.get("总资产(含市值)")),
        "available": _num(row.get("可用资金")),
        "net_asset": _num(row.get("净资产")),
        "market_value": _num(row.get("总市值")),
        "buy_frozen": _num(row.get("买入资金")),
        "sell_proceeds": _num(row.get("卖出资金")),
    }


def load_export(directory: str) -> SmartxExport:
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        raise SmartxExportError(f"导出目录不存在：{directory}")
    paths = {
        "Order": _first_file(directory, "Order"),
        "Trade": _first_file(directory, "Trade"),
        "Position": _first_file(directory, "Position"),
        "Asset": _first_file(directory, "Asset"),
        "algoList": _first_file(directory, "algoList"),
        "algoTickerList": _first_file(directory, "algoTickerList"),
    }
    if not paths["Order"] and not paths["Trade"]:
        raise SmartxExportError(f"没有找到 Order/Trade CSV：{directory}")
    export = SmartxExport(
        directory=directory,
        account=_account_from_name(paths["Order"] or paths["Trade"]),
        files={name: path for name, path in paths.items() if path},
    )
    if paths["Order"]:
        export.orders = _parse_orders(_rows(paths["Order"]))
    if paths["Trade"]:
        export.trades = _parse_trades(_rows(paths["Trade"]))
    if paths["Position"]:
        export.positions = _parse_positions(_rows(paths["Position"]))
    if paths["Asset"]:
        export.asset = _parse_asset(_rows(paths["Asset"]))
        export.account = export.account or str(export.asset.get("account") or "")
    if paths["algoList"]:
        export.algo_orders = _rows(paths["algoList"])
    if paths["algoTickerList"]:
        export.algo_tickers = _rows(paths["algoTickerList"])
    return export


def load_proposals(directory: str) -> list[dict]:
    if not os.path.isdir(directory):
        return []
    proposals = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        name = os.path.basename(path)
        if name.endswith(".approved.json") or name.endswith(".submitted.json"):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("proposal_id"):
            proposals.append(payload)
    return proposals


def reconcile(export: SmartxExport, proposals: list[dict]) -> dict:
    """把本地提案与导出委托按 rowId 对上；只读比对，不改变任何状态。"""
    proposals_by_id = {str(p.get("proposal_id")): p for p in proposals}
    orders_by_row = {order["row_id"]: order for order in export.orders if order["row_id"]}
    items = []
    matched_rows: set[str] = set()
    for pid, proposal in proposals_by_id.items():
        order = orders_by_row.get(pid)
        if order:
            matched_rows.add(pid)
        items.append(
            {
                "proposal_id": pid,
                "symbol": proposal.get("symbol"),
                "side": proposal.get("side"),
                "quantity": proposal.get("quantity"),
                "matched": bool(order),
                "order_id": order["id"] if order else None,
                "status": order["status"] if order else None,
                "status_class": order["status_class"] if order else None,
                "filled": order["filled"] if order else None,
                "remaining": order["remaining"] if order else None,
                "error": order["error"] if order else None,
            }
        )
    unmatched_orders = [order for order in export.orders if order["row_id"] not in matched_rows]
    return {
        "account": export.account,
        "summary": export.summary(),
        "items": items,
        "unmatched_orders": unmatched_orders,
        "matched": sum(1 for item in items if item["matched"]),
        "unmatched_proposals": sum(1 for item in items if not item["matched"]),
    }


def archive(directory: str, dest_root: str | None = None) -> str:
    """把当前 6 个 CSV 复制到带时间戳的目录，避免被下一次覆盖。"""
    import shutil

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = os.path.join(dest_root or os.path.join(directory, "archive"), stamp)
    os.makedirs(target, exist_ok=True)
    copied = []
    for suffix in ("Order", "Trade", "Position", "Asset", "algoList", "algoTickerList"):
        path = _first_file(directory, suffix)
        if path:
            shutil.copy2(path, os.path.join(target, os.path.basename(path)))
            copied.append(os.path.basename(path))
    with open(os.path.join(target, "_archive.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(
            {"archived_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": copied},
            fh,
            ensure_ascii=False,
            indent=2,
        )
        fh.write("\n")
    return target
