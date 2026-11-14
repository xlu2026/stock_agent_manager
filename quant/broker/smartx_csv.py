r"""把本地提案生成 SmartX `startCSV` 用的订单 CSV。

只生成文件，不提交、不调用 CLI、不碰券商。生成后仍由人：
`startCSV <csv>` → 在确认框核对 → 点「下单」。

格式（官方样例 `doc\order_csv_sample.csv`）：

    1,<账号>,<代码.SH/SZ>,<价格>,<数量>,1,<买卖>,0,<rowId>,
    2,<账号>,<orderXtpId>,
    0

- 价格类型 `1`=限价；买卖 `1`=买、`2`=卖；业务类型 `0`=普通
- 行尾 CRLF，UTF-8 无 BOM
- `rowId` 用提案 id，导出对账时按它匹配
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_IN_DIR = r"C:\AI_workspace\smartx_client\in"
SYMBOL_RE = re.compile(r"^(?P<code>\d{6})\.(?P<market>SH|SZ|BJ)$")


class SmartxCsvError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


def _broker_dir() -> str:
    return os.environ.get("NFR_BROKER_DIR") or os.path.join(ROOT, "output", "broker")


def _audit_dir() -> str:
    return os.path.join(_broker_dir(), "smartx_csv")


def _index_path() -> str:
    return os.path.join(_audit_dir(), "index.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_symbol(raw: str) -> str:
    """接受 600000 / 600000.SH / sh.600000 / SH600000，统一成 600000.SH。"""
    value = str(raw or "").strip().upper().replace(" ", "")
    if not value:
        raise SmartxCsvError("BAD_SYMBOL", "证券代码为空")
    match = SYMBOL_RE.match(value)
    if match:
        return f"{match.group('code')}.{match.group('market')}"
    match = re.match(r"^(SH|SZ|BJ)\.?(\d{6})$", value)
    if match:
        return f"{match.group(2)}.{match.group(1)}"
    match = re.match(r"^(\d{6})$", value)
    if match:
        code = match.group(1)
        if code[0] in "48":
            market = "BJ"
        elif code[0] in "569":
            market = "SH"
        else:
            market = "SZ"
        return f"{code}.{market}"
    raise SmartxCsvError("BAD_SYMBOL", f"无法识别的证券代码：{raw!r}")


def _price_text(price: float) -> str:
    text = f"{float(price):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _side_code(side: str) -> int:
    text = str(side or "").strip().upper()
    if text in ("BUY", "B", "1", "买"):
        return 1
    if text in ("SELL", "S", "2", "卖"):
        return 2
    raise SmartxCsvError("BAD_SIDE", f"无法识别的方向：{side!r}")


def proposal_to_order(proposal: dict, quotes: dict | None = None, allow_unchecked: bool = False) -> dict:
    pid = str(proposal.get("proposal_id") or "").strip()
    if not pid:
        raise SmartxCsvError("BAD_PROPOSAL", "提案缺少 proposal_id")
    symbol = normalize_symbol(str(proposal.get("symbol") or ""))
    quantity = int(proposal.get("quantity") or 0)
    if quantity <= 0:
        raise SmartxCsvError("BAD_QUANTITY", f"提案 {pid} 的数量必须大于 0：{quantity}")
    order_type = str(proposal.get("order_type") or "MARKET").upper()
    quote = (quotes or {}).get(symbol) or {}
    warnings: list[str] = []
    if quote:
        last = quote.get("last")
        if last is None:
            raise SmartxCsvError("QUOTES_REQUIRED", f"quotes 里没有 {symbol} 的 last（不复权价）")
        if order_type == "LIMIT" and proposal.get("limit_price"):
            price = float(proposal["limit_price"])
        else:
            price = float(last)
    else:
        if not allow_unchecked:
            raise SmartxCsvError(
                "QUOTES_REQUIRED",
                f"没有 {symbol} 的不复权报价；请先用 scripts\\fetch_quotes.py 生成 quotes.json，"
                "或显式加 --allow-unchecked 用快照价（后复权，可能被拒单）",
            )
        price = proposal.get("limit_price") or proposal.get("price_snapshot")
        warnings.append(f"{pid}: 未提供 quotes，使用快照价（可能是后复权），可能被拒单")
    if not price or float(price) <= 0:
        raise SmartxCsvError("BAD_PRICE", f"提案 {pid} 没有可用的限价/价格快照")
    side = _side_code(str(proposal.get("side") or ""))
    if quantity < 100 and symbol.startswith("6") and symbol.endswith(".SH") and not symbol.startswith("688"):
        warnings.append(f"{pid}: 买入 {quantity} 股低于 100 股，可能被交易所拒单")
    if side == 1 and quantity % 100 != 0:
        warnings.append(f"{pid}: 买入数量 {quantity} 不是 100 的整数倍")
    if "," in pid or "\n" in pid:
        raise SmartxCsvError("BAD_PROPOSAL", "proposal_id 不能包含逗号或换行")
    return {
        "proposal_id": pid,
        "symbol": symbol,
        "side": side,
        "price": float(price),
        "quantity": quantity,
        "warnings": warnings,
    }


def check_limits(order: dict, quotes: dict | None) -> list[str]:
    """有报价时校验涨跌停；缺报价的告警由 proposal_to_order 负责。"""
    if not quotes:
        return []
    quote = quotes.get(order["symbol"]) or {}
    low = quote.get("limit_down")
    high = quote.get("limit_up")
    warnings = []
    if low is None or high is None:
        warnings.append(f"{order['proposal_id']}: quotes 里没有 {order['symbol']} 的涨跌停")
        return warnings
    if not (float(low) <= order["price"] <= float(high)):
        raise SmartxCsvError(
            "PRICE_OUT_OF_LIMIT",
            f"{order['proposal_id']}: 价格 {order['price']} 超出涨跌停 [{low}, {high}]",
        )
    return warnings


def order_line(order: dict, account: str) -> str:
    return (
        f"1,{account},{order['symbol']},{_price_text(order['price'])},"
        f"{order['quantity']},1,{order['side']},0,{order['proposal_id']},"
    )


def cancel_line(order_xtp_id: str, account: str) -> str:
    value = str(order_xtp_id or "").strip()
    if not value.isdigit():
        raise SmartxCsvError("BAD_ORDER_ID", f"orderXtpId 必须是数字：{order_xtp_id!r}")
    return f"2,{account},{value},"


def build_lines(orders: list[dict], account: str, cancels: list[str] | None = None) -> list[str]:
    if not str(account or "").strip().isdigit():
        raise SmartxCsvError("BAD_ACCOUNT", f"资金账号必须是数字：{account!r}")
    lines = [order_line(order, account) for order in orders]
    lines.extend(cancel_line(order_id, account) for order_id in (cancels or []))
    return lines


def _load_index() -> list[dict]:
    path = _index_path()
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _check_duplicates(proposal_ids: list[str], allow_repeat: bool) -> None:
    if allow_repeat:
        return
    used = {pid for row in _load_index() for pid in row.get("proposal_ids", [])}
    repeated = sorted(set(proposal_ids) & used)
    if repeated:
        raise SmartxCsvError(
            "DUPLICATE_PROPOSAL",
            f"这些提案已经生成过 CSV：{repeated}；确需重做请加 --allow-repeat",
        )


def write_batch(
    proposals: list[dict],
    account: str,
    *,
    out_dir: str = DEFAULT_IN_DIR,
    cancels: list[str] | None = None,
    quotes: dict | None = None,
    strict: bool = False,
    allow_repeat: bool = False,
    allow_unchecked: bool = False,
    dry_run: bool = False,
) -> dict:
    orders = [proposal_to_order(p, quotes, allow_unchecked) for p in proposals]
    _check_duplicates([order["proposal_id"] for order in orders], allow_repeat)
    warnings: list[str] = []
    for order in orders:
        warnings.extend(order.pop("warnings", []))
        warnings.extend(check_limits(order, quotes))
    if strict and warnings:
        raise SmartxCsvError("STRICT_WARNINGS", "严格模式下存在告警：\n" + "\n".join(warnings))

    lines = build_lines(orders, account, cancels)
    text = "\r\n".join(lines + ["0"]) + "\r\n"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"orders_{stamp}.csv"
    path = os.path.join(out_dir, filename)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    result = {
        "batch_id": f"smartx-{stamp}",
        "path": os.path.abspath(path),
        "account": str(account),
        "proposal_ids": [order["proposal_id"] for order in orders],
        "orders": orders,
        "cancels": list(cancels or []),
        "warnings": warnings,
        "sha256": digest,
        "created_utc": _now(),
        "dry_run": dry_run,
    }
    if dry_run:
        result["csv"] = text
        return result

    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    audit_path = path + ".json"
    with open(audit_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    os.makedirs(_audit_dir(), exist_ok=True)
    with open(_index_path(), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(
            json.dumps(
                {
                    "batch_id": result["batch_id"],
                    "path": result["path"],
                    "account": str(account),
                    "proposal_ids": result["proposal_ids"],
                    "sha256": digest,
                    "created_utc": result["created_utc"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    result["audit_path"] = audit_path
    return result
