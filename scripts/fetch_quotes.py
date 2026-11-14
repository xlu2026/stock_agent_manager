"""抓不复权收盘价和涨跌停，生成 SmartX 下单用的 quotes.json。

用法（必须用装了 baostock 的 Python，例如 SmartX 自带的）：

    python scripts\\fetch_quotes.py --symbols 601939.SH --out output\\broker\\quotes.json
    python scripts\\fetch_quotes.py --proposal prop-937f03065b --out output\\broker\\quotes.json

输出：

    {"601939.SH": {"last": 11.92, "preclose": 11.92, "limit_up": 13.11,
                   "limit_down": 10.73, "date": "2026-11-11", "limit_pct": 0.1}}

注意：`last` 是不复权收盘价，专门给下单用；回测快照是后复权，两者不能混用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker.smartx_csv import normalize_symbol  # noqa: E402


def limit_pct(symbol: str) -> float:
    """按板块给默认涨跌幅；ST 需要人工用 --limit-pct 覆盖。"""
    code = normalize_symbol(symbol).split(".")[0]
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "920")):
        return 0.30
    return 0.10


def limit_prices(preclose: float, pct: float) -> tuple[float, float]:
    base = Decimal(str(preclose))
    step = Decimal("0.01")
    up = (base * (Decimal("1") + Decimal(str(pct)))).quantize(step, rounding=ROUND_HALF_UP)
    down = (base * (Decimal("1") - Decimal(str(pct)))).quantize(step, rounding=ROUND_HALF_UP)
    return float(down), float(up)


def _baostock_code(symbol: str) -> str:
    normal = normalize_symbol(symbol)
    number, market = normal.split(".")
    return f"{market.lower()}.{number}"


def _import_baostock():
    try:
        import baostock as bs  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("找不到 baostock，请用 SmartX 自带的 Python 运行") from exc
    return bs


def fetch(symbols: list[str], limit_pct_override: float | None = None, timeout: float = 15.0) -> dict:
    import socket

    socket.setdefaulttimeout(timeout)
    bs = _import_baostock()
    login = bs.login()
    if login.error_code != "0":
        raise SystemExit(f"baostock 登录失败：{login.error_code} {login.error_msg}")
    quotes: dict[str, dict] = {}
    try:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=20)).isoformat()
        for raw in symbols:
            symbol = normalize_symbol(raw)
            code = _baostock_code(symbol)
            rs = bs.query_history_k_data_plus(
                code, "date,close", start_date=start, end_date=end, frequency="d", adjustflag="3"
            )
            if rs.error_code != "0":
                print(f"  {symbol}: 查询失败 {rs.error_code} {rs.error_msg}", file=sys.stderr)
                continue
            rows = []
            while rs.next():
                row = rs.get_row_data()
                if row[1]:
                    rows.append(row)
            if not rows:
                print(f"  {symbol}: 没有不复权行情", file=sys.stderr)
                continue
            last_date, last_close = rows[-1][0], float(rows[-1][1])
            # 次日涨跌停以“最新收盘价”为基准；今天收盘后运行时，last 就是今天。
            preclose = last_close
            pct = limit_pct_override if limit_pct_override is not None else limit_pct(symbol)
            low, high = limit_prices(preclose, pct)
            quotes[symbol] = {
                "last": last_close,
                "preclose": preclose,
                "limit_up": high,
                "limit_down": low,
                "date": last_date,
                "limit_pct": pct,
            }
            print(f"  {symbol}: {last_date} close={last_close} 涨跌停=[{low}, {high}]")
    finally:
        bs.logout()
    return quotes


def _symbols_from_proposals(directory: str) -> list[str]:
    symbols = []
    if not os.path.isdir(directory):
        return symbols
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.endswith(".approved.json") or name.endswith(".submitted.json"):
            continue
        with open(os.path.join(directory, name), encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        if payload.get("symbol"):
            symbols.append(payload["symbol"])
    return symbols


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抓不复权收盘价与涨跌停，生成 quotes.json")
    ap.add_argument("--symbols", help="逗号分隔，如 601939.SH,600000.SH")
    ap.add_argument("--proposal", action="append", default=[], help="提案 id，可重复")
    ap.add_argument("--from-proposals", default=os.path.join(ROOT, "output", "broker", "proposals"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "broker", "quotes.json"))
    ap.add_argument("--limit-pct", type=float, default=None, help="强制统一涨跌幅（ST 用 0.05）")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args(argv)

    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    for pid in args.proposal:
        path = os.path.join(args.from_proposals, f"{pid}.json")
        if not os.path.exists(path):
            print(f"提案不存在：{path}", file=sys.stderr)
            return 2
        with open(path, encoding="utf-8-sig") as fh:
            symbols.append(json.load(fh)["symbol"])
    if not symbols:
        print("给 --symbols 或 --proposal", file=sys.stderr)
        return 2

    quotes = fetch(symbols, args.limit_pct, args.timeout)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(quotes, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"写入 {args.out}（{len(quotes)} 个标的）")
    return 0 if quotes else 2


if __name__ == "__main__":
    raise SystemExit(main())
