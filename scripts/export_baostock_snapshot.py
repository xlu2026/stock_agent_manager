"""用 baostock 拉真实日线（可选财报），导出 schema v2 快照。

**运行环境**：需要能 `import baostock` 的 Python。推荐用 SmartX 自带的解释器：

    C:\\Users\\<you>\\AppData\\Local\\Programs\\xtp_rich_client\\bin\\cpython\\python.exe

仓库本身仍然只用标准库——本脚本只在 `main()` 里 import baostock，所以测试可以正常导入它。

用法：

    python scripts\\export_baostock_snapshot.py ^
        --out C:\\AI_workspace\\smartx_client\\out\\real40 ^
        --universe hs300_40 --index hs300 --sample 40 ^
        --start 2019-01-01 --end 2024-12-31 --fundamentals

产物：

    <out>\\raw\\prices.csv        date, asset, open, high, low, close, volume, adj_factor
    <out>\\raw\\calendar.csv      date
    <out>\\raw\\fundamentals.csv  asset, report_date, available_date, book, earnings
    <out>\\manifest.json ...     由 csv_import 生成（含 sha256 与体检）

约定：

- 价格用**后复权**（baostock adjustflag=1），`adj_factor` 一律写 1.0，
  `adjust_mode=backward`——与 `quant/providers/qmt.py` 的口径一致，避免二次复权。
- `book` 是每股净资产：baostock 没有直接字段，用 `epsTTM / roeAvg` 反推；
  `earnings` 用 `epsTTM`。这样 `quality_proxy = earnings/book` 就约等于 ROE。
- `available_date` 用财报的 `pubDate`（公告日），没有公告日的记录直接丢弃。
- 指数成分是**当前**名单（baostock 只给最新），不是时点成分——快照 notes 会标明
  幸存者偏差，别拿这份数据下"策略有效"的结论。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.console import force_utf8  # noqa: E402

ADJUST_FLAG = {"backward": "1", "forward": "2"}
PRICE_FIELDS = "date,open,high,low,close,volume"
INDEX_APIS = {"hs300": "query_hs300_stocks", "zz500": "query_zz500_stocks", "sz50": "query_sz50_stocks"}


def _num(value) -> float | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _asset(code: str) -> str:
    """baostock 的 sh.600000 -> 我们快照里的 600000.SH。"""
    market, _, number = code.partition(".")
    if not number:
        raise ValueError(f"无法识别的 baostock 代码：{code!r}")
    return f"{number}.{market.upper()}"


def _fundamental_row(asset: str, row: dict) -> list | None:
    """把一条利润表记录翻译成 fundamentals.csv 的一行；不可用的返回 None。"""
    pub = str(row.get("pubDate") or "").strip()
    stat = str(row.get("statDate") or "").strip()
    if not pub or not stat:
        return None
    eps = _num(row.get("epsTTM"))
    roe = _num(row.get("roeAvg"))
    if eps is None or roe is None or eps <= 0 or roe <= 0:
        # 亏损或数据缺失：不写这一期。加载器会沿用上一期，宁可略旧也不要假数据。
        return None
    book_per_share = eps / roe
    return [asset, stat, pub, round(book_per_share, 4), round(eps, 4)]


def _index_codes(bs, api_name: str) -> list[str]:
    rs = getattr(bs, api_name)()
    if rs.error_code != "0":
        raise SystemExit(f"{api_name} 失败：{rs.error_code} {rs.error_msg}")
    codes = []
    while rs.next():
        codes.append(rs.get_row_data()[1])
    return sorted(set(codes))


def _sample(codes, n: int) -> list[str]:
    codes = sorted(set(codes))
    if n and n < len(codes):
        stride = max(1, len(codes) // n)
        codes = codes[::stride][:n]
    return codes


def _month_ends(calendar: list[str]) -> list[str]:
    """每个自然月最后一个交易日——用它当成分查询点。"""
    out = []
    for i, d in enumerate(calendar):
        if i + 1 == len(calendar) or calendar[i + 1][:7] != d[:7]:
            out.append(d)
    return out


def _fetch_membership(bs, grid: list[str], api_name: str) -> dict[str, set[str]]:
    """按日期查成分，按返回的 updateDate（生效日）归档。

    baostock 每次返回的是"该日期生效的名单"，并带 updateDate；所以即使只在月末查，
    也能拿到当月所有调整的准确生效日。
    """
    by_effective: dict[str, set[str]] = {}
    for d in grid:
        rs = getattr(bs, api_name)(date=d)
        if rs.error_code != "0":
            print(f"  成分查询 {d} 失败：{rs.error_code} {rs.error_msg}", flush=True)
            continue
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            continue
        by_effective[rows[0][0]] = {r[1] for r in rows}
    return by_effective


def _members_by_date(calendar: list[str], by_effective: dict[str, set[str]]) -> dict[str, set[str]]:
    """把"查询日 -> 名单"前向填充到每个交易日，并转成我们的 asset 命名。

    注意：baostock 返回的 updateDate 是"查询日吸附到的交易日"，不是指数调整生效日；
    所以第一个查询点之前的日期，用最早那份名单回填（半年才调一次，这段没有变化）。
    """
    keys = sorted(by_effective)
    out: dict[str, set[str]] = {}
    if not keys:
        return {d: set() for d in calendar}
    idx = 0
    current = {_asset(c) for c in by_effective[keys[0]]}
    for d in calendar:
        while idx < len(keys) and keys[idx] <= d:
            current = {_asset(c) for c in by_effective[keys[idx]]}
            idx += 1
        out[d] = set(current)
    return out


def _universe_rows(calendar: list[str], members: dict[str, set[str]], codes: list[str]) -> list[list]:
    assets = {_asset(c) for c in codes}
    rows: list[list] = []
    for d in calendar:
        for a in sorted(members.get(d, set()) & assets):
            rows.append([d, a])
    return rows


def _trim_dates(dates: list[str], prices: list[list]) -> list[str]:
    """把日历裁到最后一个有行情的日期。

    盘中刷新时 baostock 的交易日历已经包含“今天”，但当日行情还没生成；
    不裁掉这一天，加载器会把它当成整段截断并拒绝加载。
    """
    last = max((row[0] for row in prices), default=None)
    if not last:
        return []
    return [d for d in dates if d <= last]


def _fetch_prices(bs, codes: list[str], start: str, end: str, adjustflag: str) -> list[list]:
    rows: list[list] = []
    for i, code in enumerate(codes, 1):
        rs = bs.query_history_k_data_plus(
            code, PRICE_FIELDS, start_date=start, end_date=end, frequency="d", adjustflag=adjustflag
        )
        if rs.error_code != "0":
            raise SystemExit(f"{code} 行情失败：{rs.error_code} {rs.error_msg}")
        asset = _asset(code)
        n = 0
        while rs.next():
            d = rs.get_row_data()
            o, h, l, c = (_num(d[i]) for i in (1, 2, 3, 4))
            if o is None or h is None or l is None or c is None or min(o, h, l, c) <= 0:
                continue
            # 停牌/无成交日 baostock 会给空成交量：记 0，而不是让整批导入失败
            volume = _num(d[5])
            rows.append([d[0], asset, d[1], d[2], d[3], d[4], str(0 if volume is None else int(volume)), "1.0"])
            n += 1
        print(f"  [{i}/{len(codes)}] {asset}: {n} 行", flush=True)
    return rows


CONTINUOUS_FIELDS = "date,open,high,low,close,preclose,volume"


def _continuous_rows(asset: str, raw_rows: list[list]) -> list[list]:
    """raw rows: [date, open, high, low, close, preclose, volume] -> 连续价格行。"""
    out: list[list] = []
    adj = None
    prev_close = None
    for d in raw_rows:
        o, h, l, c = (_num(d[i]) for i in (1, 2, 3, 4))
        pre = _num(d[5])
        if o is None or h is None or l is None or c is None or min(o, h, l, c) <= 0:
            continue
        if adj is None:
            adj = c
        else:
            base = pre if pre and pre > 0 else prev_close
            if base and base > 0:
                adj *= c / base
        factor = adj / c
        volume = _num(d[6])
        out.append(
            [
                d[0],
                asset,
                f"{o * factor:.10f}",
                f"{h * factor:.10f}",
                f"{l * factor:.10f}",
                f"{adj:.10f}",
                str(0 if volume is None else int(volume)),
                "1.0",
            ]
        )
        prev_close = c
    return out


def _fetch_raw_prices(bs, codes: list[str], start: str, end: str) -> dict[str, list[list]]:
    """拉不复权 OHLC + preclose，按 asset 分组，供连续价增量使用。"""
    out: dict[str, list[list]] = {}
    for i, code in enumerate(codes, 1):
        rs = bs.query_history_k_data_plus(
            code, CONTINUOUS_FIELDS, start_date=start, end_date=end, frequency="d", adjustflag="3"
        )
        if rs.error_code != "0":
            raise SystemExit(f"{code} 行情失败：{rs.error_code} {rs.error_msg}")
        asset = _asset(code)
        out[asset] = [rs.get_row_data() for _ in iter(lambda: rs.next(), False)]
        print(f"  [{i}/{len(codes)}] {asset}: {len(out[asset])} 行（原始）", flush=True)
    return out


def _extend_continuous(
    old_prices: list[list], raw_by_asset: dict[str, list[list]], last_date: str
) -> list[list]:
    """从 base 最后收盘价出发，用新窗口的 close/preclose 继续链式复利。"""
    old_by: dict[str, list[list]] = {}
    for row in old_prices:
        old_by.setdefault(row[1], []).append(row)
    out: list[list] = []
    for asset, raw_rows in raw_by_asset.items():
        base_rows = old_by.get(asset)
        if not base_rows:
            continue
        base_close = _num(base_rows[-1][5])
        if base_close is None or base_close <= 0:
            continue
        adj = base_close
        prev_close = None
        for d in raw_rows:
            c = _num(d[4])
            if c is None or c <= 0:
                continue
            if d[0] <= last_date:
                prev_close = c
                continue
            o, h, l = (_num(d[i]) for i in (1, 2, 3))
            if o is None or h is None or l is None or min(o, h, l) <= 0:
                continue
            pre = _num(d[5])
            base_px = pre if pre and pre > 0 else prev_close
            if base_px and base_px > 0:
                adj *= c / base_px
            factor = adj / c
            volume = _num(d[6])
            out.append(
                [
                    d[0],
                    asset,
                    f"{o * factor:.10f}",
                    f"{h * factor:.10f}",
                    f"{l * factor:.10f}",
                    f"{adj:.10f}",
                    str(0 if volume is None else int(volume)),
                    "1.0",
                ]
            )
            prev_close = c
    return out


def _fetch_calendar(bs, start: str, end: str) -> list[list]:
    rs = bs.query_trade_dates(start_date=start, end_date=end)
    rows: list[list] = []
    while rs.next():
        d = rs.get_row_data()
        if d[1] == "1":
            rows.append([d[0]])
    return rows


def _fetch_fundamentals(bs, codes: list[str], first_year: int, last_year: int) -> list[list]:
    rows: list[list] = []
    seen: set[tuple[str, str]] = set()
    for i, code in enumerate(codes, 1):
        asset = _asset(code)
        got = 0
        for year in range(first_year, last_year + 1):
            for quarter in (1, 2, 3, 4):
                try:
                    rs = bs.query_profit_data(code=code, year=year, quarter=quarter)
                except Exception as exc:  # 网络超时/断线：跳过这一期，别让整批失败
                    print(f"    {asset} {year}Q{quarter} 查询异常：{exc}", flush=True)
                    continue
                if rs.error_code != "0":
                    continue
                while rs.next():
                    row = dict(zip(rs.fields, rs.get_row_data()))
                    parsed = _fundamental_row(asset, row)
                    if not parsed:
                        continue
                    key = (parsed[0], parsed[1])
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(parsed)
                    got += 1
        print(f"  [{i}/{len(codes)}] {asset}: 财报 {got} 期", flush=True)
    return rows


def _write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _filter_coverage(
    prices: list[list],
    calendar: list[list],
    threshold: float,
    members: dict[str, set[str]] | None = None,
) -> list[list]:
    """剔除覆盖率低于阈值的标的。

    给了时点成分时，分母只算"它属于指数成分"的交易日——退市/调出之后的空洞不算缺失。
    """
    dates = {r[0] for r in calendar} or {r[0] for r in prices}
    if not dates:
        return prices
    per: dict[str, set[str]] = {}
    for row in prices:
        per.setdefault(row[1], set()).add(row[0])

    keep: set[str] = set()
    for asset, got in per.items():
        if members is not None:
            expected = {d for d in dates if asset in members.get(d, set())}
        else:
            expected = dates
        if expected and len(got & expected) / len(expected) >= threshold:
            keep.add(asset)

    dropped = sorted(set(per) - keep)
    if dropped:
        print(f"  覆盖率低于 {threshold:.0%} 被剔除：{dropped}", flush=True)
    return [row for row in prices if row[1] in keep]


def _import_baostock():
    try:
        import baostock as bs  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖运行环境
        raise SystemExit(
            "找不到 baostock。请用装了 baostock 的 Python 运行，例如 SmartX 自带的：\n"
            r"  C:\Users\<you>\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
        ) from exc
    return bs


PRICE_HEADER = ["date", "asset", "open", "high", "low", "close", "volume", "adj_factor"]
CLOSE_IDX = 5


def _read_rows(path: str) -> tuple[list[str], list[list]]:
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        rows = [r for r in reader if len(r) > 1]
    return header, rows


def _asset_to_code(asset: str) -> str:
    """600000.SH -> sh.600000（_asset 的逆运算）。"""
    number, _, market = asset.partition(".")
    if not market:
        raise ValueError(f"无法识别的 asset：{asset!r}")
    return f"{market.lower()}.{number}"


def _overlap_changed(old_rows: list[list], new_rows: list[list], overlap_dates: set[str], tol: float = 1e-4) -> list:
    """重叠窗口里收盘价变了 -> 除权/数据修订。返回 [(asset, date, old, new)]。"""
    old_by: dict[str, dict[str, list]] = {}
    for row in old_rows:
        old_by.setdefault(row[1], {})[row[0]] = row
    bad = []
    for row in new_rows:
        d, a = row[0], row[1]
        if d not in overlap_dates:
            continue
        old = old_by.get(a, {}).get(d)
        if not old:
            continue
        o, n = _num(old[CLOSE_IDX]), _num(row[CLOSE_IDX])
        if o is None or n is None or o <= 0:
            continue
        if abs(n / o - 1.0) > tol:
            bad.append((a, d, o, n))
    return bad


def _merge_prices(old_rows: list[list], new_rows: list[list], last_date: str) -> list[list]:
    merged = {(r[0], r[1]): r for r in old_rows}
    for row in new_rows:
        if row[0] > last_date:
            merged[(row[0], row[1])] = row
    return [merged[key] for key in sorted(merged)]


def _latest_quarters(end_date: str, count: int = 4) -> list[tuple[int, int]]:
    year, month = int(end_date[:4]), int(end_date[5:7])
    quarter = (month - 1) // 3 + 1
    out = []
    for _ in range(count):
        out.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            quarter, year = 4, year - 1
    return out


def _fetch_fundamentals_latest(bs, codes: list[str], quarters, existing: set) -> list[list]:
    rows: list[list] = []
    for code in codes:
        asset = _asset(code)
        for year, quarter in quarters:
            try:
                rs = bs.query_profit_data(code=code, year=year, quarter=quarter)
            except Exception:
                continue
            if rs.error_code != "0":
                continue
            while rs.next():
                parsed = _fundamental_row(asset, dict(zip(rs.fields, rs.get_row_data())))
                if not parsed:
                    continue
                key = (parsed[0], parsed[1])
                if key in existing:
                    continue
                existing.add(key)
                rows.append(parsed)
    return rows


def _extend_universe(bs, args, old_rows: list[list], new_dates: list[str], assets: set[str]):
    """在已有 universe 后面补新日期：先查新月末，再前向填充。"""
    by_date: dict[str, set[str]] = {}
    for row in old_rows:
        by_date.setdefault(row[0], set()).add(row[1])
    current = by_date.get(max(by_date), set()) if by_date else set()
    queries = sorted(set(_month_ends(new_dates) + [new_dates[-1]]))
    by_effective = _fetch_membership(bs, queries, INDEX_APIS[args.index])
    keys = sorted(by_effective)
    idx = 0
    rows = list(old_rows)
    for d in new_dates:
        while idx < len(keys) and keys[idx] <= d:
            current = {_asset(c) for c in by_effective[keys[idx]]}
            idx += 1
        for a in sorted(current & assets):
            rows.append([d, a])
    return rows, len(by_effective)


def _fallback_full(args, reason: str) -> int:
    """回退全量：重新起一个进程跑，不带 --incremental。"""
    print(f"{reason}；回退全量刷新", flush=True)
    cleaned: list[str] = []
    skip = False
    for item in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if item == "--incremental":
            continue
        if item == "--base-dir":
            skip = True
            continue
        if item.startswith("--base-dir="):
            continue
        cleaned.append(item)
    import subprocess

    return subprocess.call([sys.executable, os.path.abspath(__file__)] + cleaned)


def _fetch_prices_continuous(bs, codes: list[str], start: str, end: str) -> list[list]:
    """全量：不复权 OHLC + preclose -> 连续总收益价。"""
    rows: list[list] = []
    for asset, raw in _fetch_raw_prices(bs, codes, start, end).items():
        rows.extend(_continuous_rows(asset, raw))
    return rows


def _run_incremental(bs, args) -> int:
    base = os.path.abspath(args.base_dir)
    out = os.path.abspath(args.out)
    if base == out:
        print("--incremental 的输出目录不能和 --base-dir 相同（会破坏旧实验的可复现性）", file=sys.stderr)
        return 2
    continuous = getattr(args, "continuous", False)
    if continuous:
        try:
            with open(os.path.join(base, "manifest.json"), encoding="utf-8") as fh:
                base_notes = (json.load(fh).get("notes") or {})
        except (OSError, ValueError):
            base_notes = {}
        if base_notes.get("price_construction") != "total_return_chain_preclose":
            return _fallback_full(args, "base 不是连续价快照，无法安全增量；改为全量重建")

    _, old_prices = _read_rows(os.path.join(base, "prices.csv"))
    if not old_prices:
        return _fallback_full(args, f"{base} 里没有 prices.csv")
    try:
        with open(os.path.join(base, "manifest.json"), encoding="utf-8") as fh:
            base_manifest = json.load(fh)
        base_universe_name = str(base_manifest.get("universe") or args.universe)
    except (OSError, ValueError):
        base_universe_name = args.universe
    _, old_cal = _read_rows(os.path.join(base, "calendar.csv"))
    old_dates = [r[0] for r in old_cal] or sorted({r[0] for r in old_prices})
    last_date = max(old_dates)
    if args.end <= last_date:
        print(f"已是最新：base 末尾 {last_date} >= --end {args.end}")
        return 0

    new_dates = [r[0] for r in _fetch_calendar(bs, last_date, args.end) if r[0] > last_date]
    if not new_dates:
        print("区间内没有新交易日")
        return 0

    assets = {r[1] for r in old_prices}
    codes = [_asset_to_code(a) for a in sorted(assets)]
    if continuous:
        new_prices = _extend_continuous(
            old_prices, _fetch_raw_prices(bs, codes, last_date, args.end), last_date
        )
        if not new_prices:
            print("没有新增行情（可能今天尚未收盘或区间内无新交易日）")
            return 0
        merged_prices = sorted(old_prices + new_prices, key=lambda r: (r[0], r[1]))
    else:
        overlap = set(old_dates[-max(1, args.overlap_days) :])
        fetch_start = min(overlap) if overlap else last_date
        new_prices = _fetch_prices(bs, codes, fetch_start, args.end, ADJUST_FLAG[args.adjust])
        bad = _overlap_changed(old_prices, new_prices, overlap)
        if bad:
            a, d, old_v, new_v = bad[0]
            return _fallback_full(args, f"重叠窗口发现除权/修订（{a} {d}: {old_v} -> {new_v}）")
        merged_prices = _merge_prices(old_prices, new_prices, last_date)
    if len(merged_prices) == len(old_prices):
        print("没有新增行情（可能今天尚未收盘或区间内无新交易日）")
        return 0
    trimmed_dates = _trim_dates(new_dates, merged_prices)
    if len(trimmed_dates) != len(new_dates):
        print(f"  日历裁到最后一个有行情的日期：{trimmed_dates[-1]}（请求 end={args.end}）", flush=True)
    new_dates = trimmed_dates

    _, old_uni = _read_rows(os.path.join(base, "universe.csv"))
    universe_rows = old_uni
    membership_versions = 0
    if old_uni and not args.stocks:
        universe_rows, membership_versions = _extend_universe(bs, args, old_uni, new_dates, assets)
        if new_dates and not membership_versions:
            return _fallback_full(args, "取不到新的成分名单")
    elif old_uni and args.stocks:
        return _fallback_full(args, "base 带时点成分，但本次用 --stocks，无法增量维护")

    _, old_fund = _read_rows(os.path.join(base, "fundamentals.csv"))
    fundamentals = list(old_fund)
    appended_fund = 0
    if args.fundamentals:
        existing = {(r[0], r[1]) for r in old_fund}
        new_fund = _fetch_fundamentals_latest(bs, codes, _latest_quarters(args.end), existing)
        appended_fund = len(new_fund)
        fundamentals = old_fund + new_fund

    raw = os.path.join(out, "raw")
    os.makedirs(raw, exist_ok=True)
    _write_csv(os.path.join(raw, "prices.csv"), PRICE_HEADER, merged_prices)
    _write_csv(os.path.join(raw, "calendar.csv"), ["date"], [[d] for d in old_dates + new_dates])
    if universe_rows:
        _write_csv(os.path.join(raw, "universe.csv"), ["date", "asset"], universe_rows)
    if fundamentals:
        _write_csv(
            os.path.join(raw, "fundamentals.csv"),
            ["asset", "report_date", "available_date", "book", "earnings"],
            sorted(fundamentals, key=lambda r: (r[0], r[1])),
        )

    from quant.data import DataError
    from quant.providers.contract import ContractError
    from quant.providers.csv_import import import_snapshot

    notes = {
        "provider": "baostock",
        "adjustflag": "3+preclose(continuous)" if getattr(args, "continuous", False) else ADJUST_FLAG[args.adjust],
        "price_construction": "total_return_chain_preclose" if getattr(args, "continuous", False) else "baostock_adjusted_close",
        "index": args.index if not args.stocks else None,
        "sample": args.sample,
        "universe_point_in_time": bool(old_uni),
        "membership_grid": "month-end",
        "membership_versions": membership_versions,
        "incremental": True,
        "base_dir": base,
        "overlap_days": args.overlap_days,
        "appended_price_rows": len(merged_prices) - len(old_prices),
        "appended_fundamental_rows": appended_fund,
        "requested_end": args.end,
        "calendar_end": new_dates[-1] if new_dates else last_date,
        "calendar_trimmed": bool(new_dates and new_dates[-1] < args.end),
        "survivorship": "时点成分（按 updateDate 前向填充），已消除名单层面的幸存者偏差"
        if old_uni
        else "无 universe.csv（固定池）",
    }
    try:
        result = import_snapshot(
            out,
            prices_path=os.path.join(raw, "prices.csv"),
            universe=base_universe_name,
            source=args.source,
            adjust_mode=args.adjust,
            fundamentals_path=os.path.join(raw, "fundamentals.csv") if fundamentals else None,
            universe_path=os.path.join(raw, "universe.csv") if universe_rows else None,
            calendar_path=os.path.join(raw, "calendar.csv"),
            extra_notes=notes,
        )
    except (ContractError, DataError) as exc:
        print(f"生成快照失败：{exc}\nraw CSV 已保留在 {raw}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "incremental": True,
                "base_dir": base,
                "out_dir": result["out_dir"],
                "data_version": result["data_version"],
                "assets": result["assets"],
                "rows": result["rows"],
                "appended_price_rows": len(merged_prices) - len(old_prices),
                "appended_fundamental_rows": appended_fund,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python scripts/export_baostock_snapshot.py",
        description="用 baostock 拉真实日线/财报，导出 schema v2 快照",
    )
    p.add_argument("--out", required=True, help="输出目录（会写 raw\\ 与快照文件）")
    p.add_argument("--universe", default="hs300_40", help="写进 manifest 的池名")
    p.add_argument("--stocks", help="逗号分隔的 baostock 代码，如 sh.600000,sz.000001")
    p.add_argument("--index", default="hs300", choices=sorted(INDEX_APIS), help="从指数成分取样")
    p.add_argument("--sample", type=int, default=40, help="从指数成分里等距取样多少只（0=全部）")
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--adjust", default="backward", choices=sorted(ADJUST_FLAG))
    p.add_argument(
        "--continuous",
        action="store_true",
        help="用不复权 OHLC + preclose 链式生成连续总收益价（修复除权日跳空；暂不支持增量）",
    )
    p.add_argument("--fundamentals", action="store_true", help="同时拉财报（慢，但价值/质量因子需要）")
    p.add_argument("--timeout", type=float, default=20.0, help="单次网络查询超时秒数（默认 20）")
    p.add_argument("--min-coverage", type=float, default=0.9, help="标的在交易日历上的最低覆盖率（默认 0.9）")
    p.add_argument(
        "--no-pit-universe",
        dest="pit_universe",
        action="store_false",
        help="用当前成分而不是时点成分（默认用时点成分）",
    )
    p.set_defaults(pit_universe=True)
    p.add_argument("--no-build", action="store_true", help="只写 raw CSV，不生成快照")
    p.add_argument("--source", default="baostock", help="写进 manifest 的来源描述")
    p.add_argument("--incremental", action="store_true", help="基于 --base-dir 增量刷新；重叠窗口发现除权/修订则回退全量")
    p.add_argument("--base-dir", help="增量刷新所基于的已有快照目录（不能与 --out 相同）")
    p.add_argument("--overlap-days", type=int, default=10, help="重叠校验的交易日数（默认 10）")
    return p


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)
    socket.setdefaulttimeout(args.timeout)
    os.makedirs(args.out, exist_ok=True)
    raw = os.path.join(args.out, "raw")
    os.makedirs(raw, exist_ok=True)

    if args.incremental:
        if not args.base_dir:
            print("--incremental 需要 --base-dir", file=sys.stderr)
            return 2
        if os.path.abspath(args.out) == os.path.abspath(args.base_dir):
            print("--incremental 的输出目录不能和 --base-dir 相同（会破坏旧实验的可复现性）", file=sys.stderr)
            return 2

    bs = _import_baostock()
    login = bs.login()
    if login.error_code != "0":
        print(f"baostock 登录失败：{login.error_code} {login.error_msg}", file=sys.stderr)
        return 2

    if args.incremental:
        if not args.base_dir:
            print("--incremental 需要 --base-dir", file=sys.stderr)
            bs.logout()
            return 2
        try:
            return _run_incremental(bs, args)
        finally:
            bs.logout()

    try:
        calendar = _fetch_calendar(bs, args.start, args.end)
        cal_dates = [r[0] for r in calendar]
        members = None
        universe_rows: list[list] = []
        membership_versions = 0
        if args.stocks:
            codes = [c.strip() for c in args.stocks.split(",") if c.strip()]
            print(f"标的 {len(codes)} 只（显式指定），区间 {args.start}..{args.end}")
        elif args.pit_universe:
            by_effective = _fetch_membership(bs, _month_ends(cal_dates), INDEX_APIS[args.index])
            members = _members_by_date(cal_dates, by_effective)
            membership_versions = len(by_effective)
            pool = set().union(*by_effective.values()) if by_effective else set()
            codes = _sample(pool, args.sample)
            print(
                f"时点成分：{len(by_effective)} 个生效版本，历史并集 {len(pool)} 只，取样 {len(codes)} 只",
                flush=True,
            )
        else:
            codes = _sample(_index_codes(bs, INDEX_APIS[args.index]), args.sample)
            print(f"当前成分取样 {len(codes)} 只（非时点）", flush=True)

        prices = (
            _fetch_prices_continuous(bs, codes, args.start, args.end)
            if getattr(args, "continuous", False)
            else _fetch_prices(bs, codes, args.start, args.end, ADJUST_FLAG[args.adjust])
        )
        if not prices:
            print("没有取到任何行情，终止", file=sys.stderr)
            return 2
        if args.min_coverage > 0:
            prices = _filter_coverage(prices, calendar, args.min_coverage, members)
        trimmed_dates = _trim_dates(cal_dates, prices)
        if len(trimmed_dates) != len(cal_dates):
            print(f"  日历裁到最后一个有行情的日期：{trimmed_dates[-1]}（请求 end={args.end}）", flush=True)
        cal_dates = trimmed_dates
        calendar = [[d] for d in cal_dates]
        # 没有任何行情的标的（退市/长期停牌）不能出现在 universe.csv 里，
        # 否则加载器会报"成分在行情里不存在"。
        assets_with_prices = {row[1] for row in prices}
        missing_price_codes = [c for c in codes if _asset(c) not in assets_with_prices]
        if missing_price_codes:
            print(f"  无行情被剔除：{missing_price_codes}", flush=True)
        codes = [c for c in codes if _asset(c) in assets_with_prices]
        if members is not None:
            universe_rows = _universe_rows(cal_dates, members, codes)
        fundamentals: list[list] = []
        if args.fundamentals:
            first_year = int(args.start[:4]) - 1
            last_year = int(args.end[:4])
            fundamentals = _fetch_fundamentals(bs, codes, first_year, last_year)
    finally:
        bs.logout()

    _write_csv(
        os.path.join(raw, "prices.csv"),
        ["date", "asset", "open", "high", "low", "close", "volume", "adj_factor"],
        sorted(prices, key=lambda r: (r[0], r[1])),
    )
    _write_csv(os.path.join(raw, "calendar.csv"), ["date"], calendar)
    if universe_rows:
        _write_csv(os.path.join(raw, "universe.csv"), ["date", "asset"], universe_rows)
    if fundamentals:
        _write_csv(
            os.path.join(raw, "fundamentals.csv"),
            ["asset", "report_date", "available_date", "book", "earnings"],
            sorted(fundamentals, key=lambda r: (r[0], r[1])),
        )
    print(
        f"prices={len(prices)} calendar={len(calendar)} fundamentals={len(fundamentals)} "
        f"universe_rows={len(universe_rows)}"
    )

    if args.no_build:
        print(f"raw 已写入 {raw}（按 --no-build 跳过快照生成）")
        return 0

    from quant.data import DataError
    from quant.providers.contract import ContractError
    from quant.providers.csv_import import import_snapshot

    notes = {
        "provider": "baostock",
        "adjustflag": "3+preclose(continuous)" if getattr(args, "continuous", False) else ADJUST_FLAG[args.adjust],
        "price_construction": "total_return_chain_preclose" if getattr(args, "continuous", False) else "baostock_adjusted_close",
        "index": args.index if not args.stocks else None,
        "sample": args.sample,
        "universe_point_in_time": members is not None,
        "membership_grid": "month-end" if members is not None else None,
        "membership_versions": membership_versions,
        "requested_end": args.end,
        "calendar_end": cal_dates[-1] if cal_dates else None,
        "calendar_trimmed": bool(cal_dates and cal_dates[-1] < args.end),
        "survivorship": (
            "时点成分（按 updateDate 前向填充），已消除名单层面的幸存者偏差"
            if members is not None
            else "指数成分为当前名单，非时点成分，存在幸存者偏差"
        ),
    }
    try:
        result = import_snapshot(
            args.out,
            prices_path=os.path.join(raw, "prices.csv"),
            universe=args.universe,
            source=args.source,
            adjust_mode=args.adjust,
            fundamentals_path=os.path.join(raw, "fundamentals.csv") if fundamentals else None,
            universe_path=os.path.join(raw, "universe.csv") if universe_rows else None,
            calendar_path=os.path.join(raw, "calendar.csv"),
            extra_notes=notes,
        )
    except (ContractError, DataError) as exc:
        print(f"生成快照失败：{exc}\nraw CSV 已保留在 {raw}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "out_dir": result["out_dir"],
                "data_version": result["data_version"],
                "assets": result["assets"],
                "rows": result["rows"],
                "has_fundamentals": result["has_fundamentals"],
                "fails": result["check"]["checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
