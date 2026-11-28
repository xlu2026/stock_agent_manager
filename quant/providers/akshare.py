"""AkShare 数据源：把 A 股日线（后复权）翻译成 v2 快照。

只在装了 akshare 的 Python 里运行（本机是 SmartX 自带的 3.9）；仓库本身仍纯标准库。
这里不做复权计算，直接用 AkShare 的 `adjust="hfq"`，与 baostock 的 `adjustflag=1` 语义对齐；
两边复权基准可能不同，所以交叉验证脚本会同时看“价格比”和“日收益差”。
"""
from __future__ import annotations

import math
import time
from datetime import date

from .contract import Snapshot


class AkshareError(RuntimeError):
    pass


def _import_akshare():
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise AkshareError("找不到 akshare；请用 SmartX 自带的 Python 运行") from exc
    return ak


def _code(symbol: str) -> str:
    value = str(symbol).strip()
    if "." in value:
        value = value.split(".")[0]
    return value.zfill(6)


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sina_symbol(symbol: str) -> str:
    normal = str(symbol).strip().upper()
    if normal.endswith(".SH"):
        return "sh" + normal[:-3]
    if normal.endswith(".SZ"):
        return "sz" + normal[:-3]
    return normal.lower()


def _frame_rows(df, symbol: str) -> tuple[list[dict], bool]:
    """不复权 OHLC + 官方涨跌幅 -> 连续总收益价；返回 (rows, used_pct)。"""
    if "日期" in df.columns:
        mapping = {"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量", "pct": "涨跌幅"}
    else:
        mapping = {"date": "date", "open": "open", "close": "close", "high": "high", "low": "low", "volume": "volume"}
    has_pct = "pct" in mapping and mapping["pct"] in df.columns
    rows = []
    adj = None
    prev_close = None
    for _, row in df.iterrows():
        day = str(row[mapping["date"]])[:10]
        close = _num(row[mapping["close"]])
        open_ = _num(row[mapping["open"]])
        high = _num(row[mapping["high"]])
        low = _num(row[mapping["low"]])
        volume = _num(row[mapping["volume"]])
        if not day or min(open_ or 0, high or 0, low or 0, close or 0) <= 0:
            continue
        if adj is None:
            adj = close
        else:
            pct = _num(row[mapping["pct"]]) if has_pct else None
            if pct is not None:
                adj *= 1.0 + pct / 100.0
            elif prev_close and prev_close > 0:
                adj *= close / prev_close
        factor = adj / close
        # 缩放后重新夹紧，避免 float 舍入让 high < open 一点点
        so = open_ * factor
        sh = max(high, open_, close) * factor
        sl = min(low, open_, close) * factor
        sh = max(sh, so, adj)
        sl = min(sl, so, adj)
        rows.append(
            {
                "date": day,
                "asset": symbol,
                "open": so,
                "high": sh,
                "low": sl,
                "close": adj,
                "volume": int(volume or 0),
                "adj_factor": 1.0,
            }
        )
        prev_close = close
    return rows, has_pct


def fetch_prices(
    symbols: list[str], start: str, end: str, retries: int = 3, delay: float = 0.5
) -> tuple[list[dict], list[str]]:
    """返回 (price rows, warnings)；东财失败时回退到 Sina，单只失败不影响其他标的。"""
    ak = _import_akshare()
    rows: list[dict] = []
    warnings: list[str] = []
    start_fmt = start.replace("-", "")
    end_fmt = end.replace("-", "")
    for index, symbol in enumerate(symbols, 1):
        code = _code(symbol)
        df = None
        last_error = None
        for attempt in range(max(1, retries)):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily", start_date=start_fmt, end_date=end_fmt, adjust="hfq"
                )
                if df is not None and len(df) > 0:
                    last_error = None
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(1.0 + attempt * 2.0)
        if df is None or len(df) == 0:
            try:
                df = ak.stock_zh_a_daily(
                    symbol=_sina_symbol(symbol), start_date=start_fmt, end_date=end_fmt, adjust="hfq"
                )
                if df is not None and len(df) > 0:
                    last_error = None
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error is not None or df is None or len(df) == 0:
            warnings.append(f"{symbol}: 拉取失败（东财+Sina 均失败）{last_error}")
            continue
        parsed, used_pct = _frame_rows(df, symbol)
        if not parsed:
            warnings.append(f"{symbol}: 没有可用行情")
            continue
        if not used_pct:
            warnings.append(f"{symbol}: 回退源没有涨跌幅，按收盘价链式，除权日可能有误差")
        rows.extend(parsed)
        print(f"  [{index}/{len(symbols)}] {symbol}: {len(parsed)} 行", flush=True)
        time.sleep(max(0.0, delay))
    return rows, warnings


def _deadline(report_date: str) -> str:
    """A 股定期报告法定披露截止日：Q1 4/30、Q2 8/31、Q3 10/31、年报次年 4/30。"""
    year, month, _ = (int(x) for x in report_date.split("-"))
    if month == 3:
        return f"{year}-04-30"
    if month == 6:
        return f"{year}-08-31"
    if month == 9:
        return f"{year}-10-31"
    return f"{year + 1}-04-30"


def fetch_fundamentals(symbols: list[str], start: str, end: str) -> tuple[list[dict], list[str]]:
    """每股净资产 + TTM EPS；公告日用法定截止日，避免前视。"""
    ak = _import_akshare()
    rows: list[dict] = []
    warnings: list[str] = []
    first_year = int(start[:4]) - 1
    last_year = int(end[:4])
    for index, symbol in enumerate(symbols, 1):
        code = _code(symbol)
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(first_year))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{symbol}: 财报拉取失败 {exc}")
            continue
        if df is None or len(df) == 0 or "日期" not in df.columns:
            warnings.append(f"{symbol}: 财报为空")
            continue
        dates = []
        books = {}
        cum_eps = {}
        for _, row in df.iterrows():
            day = str(row["日期"])[:10]
            if len(day) != 10:
                continue
            book = _num(row.get("每股净资产_调整前(元)"))
            eps = _num(row.get("摊薄每股收益(元)"))
            if book is None or book <= 0:
                continue
            dates.append(day)
            books[day] = book
            cum_eps[day] = eps
        dates.sort()
        # 累计 EPS -> 单季 EPS -> TTM
        prev_map = {3: None, 6: "03-31", 9: "06-30", 12: "09-30"}
        q_eps: dict[str, float] = {}
        for day in dates:
            eps = cum_eps.get(day)
            if eps is None:
                continue
            year, month, _ = (int(x) for x in day.split("-"))
            prev = f"{year}-{prev_map[month]}" if prev_map.get(month) else None
            if prev and prev in cum_eps and cum_eps[prev] is not None:
                q_eps[day] = eps - cum_eps[prev]
            else:
                q_eps[day] = eps
        kept = 0
        for i, day in enumerate(dates):
            if i < 3:
                continue
            window = dates[i - 3 : i + 1]
            if any(w not in q_eps for w in window):
                continue
            earnings = sum(q_eps[w] for w in window)
            rows.append(
                {
                    "asset": symbol,
                    "report_date": day,
                    "available_date": _deadline(day),
                    "book": books[day],
                    "earnings": earnings,
                }
            )
            kept += 1
        print(f"  [{index}/{len(symbols)}] {symbol}: 财报 {kept} 期", flush=True)
        time.sleep(0.2)
    return rows, warnings


def fetch_current_constituents(index: str = "000300") -> list[str]:
    """当前指数成分（AkShare/中证官网）；历史时点成分免费接口没有。"""
    ak = _import_akshare()
    df = ak.index_stock_cons_csindex(symbol=index)
    if df is None or len(df) == 0:
        return []
    code_col = "成分券代码" if "成分券代码" in df.columns else "品种代码"
    out = []
    for code in df[code_col].astype(str):
        number = code.zfill(6)
        suffix = ".SH" if number.startswith(("6", "5", "9")) else ".SZ"
        out.append(number + suffix)
    return sorted(set(out))


def build_snapshot(
    *,
    assets: list[str],
    start: str,
    end: str,
    universe_name: str,
    source: str = "akshare",
    calendar: list[str] | None = None,
    universe_rows: list[dict] | None = None,
    fundamentals: list[dict] | None = None,
    min_coverage: float = 0.9,
    retries: int = 3,
    delay: float = 0.5,
) -> tuple[Snapshot, list[str]]:
    prices, warnings = fetch_prices(assets, start, end, retries=retries, delay=delay)
    if not prices:
        raise AkshareError(f"没有取到任何 AkShare 行情；前几条：{warnings[:3]}")
    dates = sorted({r["date"] for r in prices})
    calendar = [d for d in (calendar or dates) if start <= d <= end]
    expected_all = set(calendar)
    per_asset: dict[str, set[str]] = {}
    for row in prices:
        per_asset.setdefault(row["asset"], set()).add(row["date"])
    membership: dict[str, set[str]] = {}
    if universe_rows is not None:
        for row in universe_rows:
            membership.setdefault(row["asset"], set()).add(row["date"])
    keep = set()
    for asset in assets:
        got = per_asset.get(asset, set())
        expected = (membership.get(asset, set()) & expected_all) if universe_rows is not None else expected_all
        if expected and len(got & expected) / len(expected) >= min_coverage:
            keep.add(asset)
        else:
            warnings.append(f"{asset}: 覆盖率不足（有效成分日 {len(expected)}），已剔除")
    prices = [r for r in prices if r["asset"] in keep]
    if not prices:
        raise AkshareError("覆盖率过滤后没有剩下任何标的")
    if universe_rows is None:
        universe_rows = [{"date": d, "asset": a} for d in calendar for a in sorted(keep)]
        point_in_time = False
    else:
        universe_rows = [
            r for r in universe_rows if r["date"] in expected_all and r["asset"] in keep
        ]
        point_in_time = True
    snap = Snapshot(
        universe=universe_name,
        source=source,
        provider="akshare",
        adjust_mode="backward",
        prices=prices,
        fundamentals=fundamentals or [],
        calendar=[{"date": d} for d in calendar],
        universe_rows=universe_rows,
        notes={
            "provider": "akshare",
            "adjust": "raw + 涨跌幅 chain",
            "price_construction": "total_return_chain_pct",
            "universe_point_in_time": point_in_time,
            "assets_requested": len(assets),
            "assets_kept": len(keep),
            "warnings": warnings,
            "limit": "财报公告日使用法定截止日（保守），quality 口径与 baostock 不完全一致",
        },
    )
    return snap, warnings
