"""快照体检：加载之前先证明这份数据没病。

这些东西**不会自己报错**，只会让回测结果好得出奇：

- 除权日没复权 → 一根假跌停，因子被噪声污染；
- 停牌被当成 0 或直接跳过 → 收益序列断裂；
- 财报用报告期而非公告日 → 前视偏差；
- 文件被改过但 manifest 没更新 → 你以为在复现，其实换了数据。

这里的检查是"能不能用"的门槛，不是"数据质量评分"。任何一条 fail，都不该进回测。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict

MAX_MISSING_RATIO = 0.10  # 单标的缺失超过 10% 的交易日 -> fail
SUSPENSION_HINT_RATIO = 0.02  # 超过 2% -> warn（可能是停牌，也可能是数据缺失）


def _fail(code: str, detail: str) -> dict:
    return {"id": code, "status": "fail", "detail": detail}


def _warn(code: str, detail: str) -> dict:
    return {"id": code, "status": "warn", "detail": detail}


def _pass(code: str, detail: str) -> dict:
    return {"id": code, "status": "pass", "detail": detail}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def check_snapshot(dir_path: str) -> dict:
    """返回 {ok, checks:[...], stats:{...}}。ok 为假时不要加载这份数据。"""
    checks: list[dict] = []
    manifest_path = os.path.join(dir_path, "manifest.json")
    if not os.path.exists(manifest_path):
        return {"ok": False, "checks": [_fail("manifest.exists", "找不到 manifest.json")], "stats": {}}

    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    # 1) 文件指纹：改了数据却没更新 manifest，是最隐蔽的一种错
    files = manifest.get("files") or {}
    bad_files = []
    for name, meta in files.items():
        path = os.path.join(dir_path, name)
        if not os.path.exists(path):
            bad_files.append(f"{name} 缺失")
        elif _sha256(path) != meta.get("sha256"):
            bad_files.append(f"{name} 哈希不符")
    checks.append(
        _fail("manifest.files", "；".join(bad_files)) if bad_files else _pass("manifest.files", f"{len(files)} 个文件指纹一致")
    )

    prices_path = os.path.join(dir_path, "prices.csv")
    if not os.path.exists(prices_path):
        return {"ok": False, "checks": checks + [_fail("prices.exists", "找不到 prices.csv")], "stats": {}}
    prices = _read_csv(prices_path)
    if not prices:
        return {"ok": False, "checks": checks + [_fail("prices.empty", "prices.csv 没有数据行")], "stats": {}}

    # 2) 逐行体检
    dup = set()
    bad_price = []
    bad_ohlc = []
    seen = set()
    for i, row in enumerate(prices, start=2):
        key = (row["date"], row["asset"])
        if key in seen:
            dup.add(key)
        seen.add(key)
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            v = float(row["volume"])
        except (TypeError, ValueError):
            bad_price.append(f"第 {i} 行数值无法解析")
            continue
        if min(o, h, l, c) <= 0:
            bad_price.append(f"{row['date']} {row['asset']} 价格 <= 0")
        if h < max(o, c) or l > min(o, c):
            bad_ohlc.append(f"{row['date']} {row['asset']} OHLC 关系不成立")
        if v < 0:
            bad_price.append(f"{row['date']} {row['asset']} 成交量为负")
        if len(bad_price) > 5 and len(bad_ohlc) > 5:
            break

    checks.append(
        _fail("prices.duplicates", f"重复的 (date,asset) {len(dup)} 条") if dup else _pass("prices.duplicates", "无重复行")
    )
    checks.append(
        _fail("prices.values", f"{len(bad_price)} 条异常：{bad_price[:3]}") if bad_price else _pass("prices.values", "价格与成交量合法")
    )
    checks.append(
        _fail("prices.ohlc", f"{len(bad_ohlc)} 条异常：{bad_ohlc[:3]}") if bad_ohlc else _pass("prices.ohlc", "OHLC 关系成立")
    )

    # 3) 面板完整性：分母必须是**交易日历**，不能是 prices 里出现过的日期。
    #    用后者等于"少了整天就看不见"，正是最该拦的截断数据。
    calendar_path = os.path.join(dir_path, "calendar.csv")
    calendar_dates: list[str] = []
    if os.path.exists(calendar_path):
        calendar_dates = sorted({r["date"] for r in _read_csv(calendar_path)})
    dates_in_prices = sorted({r["date"] for r in prices})
    expected_dates = calendar_dates or dates_in_prices
    if not calendar_dates:
        checks.append(_warn("calendar.missing", "没有 calendar.csv，完整性只能以行情日期为分母"))

    assets = sorted({r["asset"] for r in prices})
    per_asset = defaultdict(set)
    for r in prices:
        per_asset[r["asset"]].add(r["date"])
    holes = {}
    for asset in assets:
        missing = 1 - len(per_asset[asset] & set(expected_dates)) / len(expected_dates)
        if missing > 0:
            holes[asset] = round(missing, 4)
    worst = max(holes.values()) if holes else 0.0
    if worst > MAX_MISSING_RATIO:
        worst_asset = max(holes, key=holes.get)
        checks.append(
            _fail(
                "prices.coverage",
                f"最差标的 {worst_asset} 缺失 {worst:.1%} 的交易日（上限 {MAX_MISSING_RATIO:.0%}，分母={len(expected_dates)} 天）",
            )
        )
    elif worst > SUSPENSION_HINT_RATIO:
        checks.append(_warn("prices.coverage", f"存在缺失，最差 {worst:.1%}，请确认是否停牌"))
    else:
        checks.append(_pass("prices.coverage", f"{len(assets)} 个标的 × {len(expected_dates)} 个交易日"))

    # 4) 日历一致性：行情里出现了日历之外的日期
    if calendar_dates:
        extra = sorted(set(dates_in_prices) - set(calendar_dates))
        checks.append(
            _fail("calendar.coverage", f"{len(extra)} 个行情日期不在交易日历里：{extra[:3]}")
            if extra
            else _pass("calendar.coverage", "行情日期均在日历内")
        )

    # 5) 财报公告日：available_date 必须不早于 report_date，否则就是前视的源头
    fund_path = os.path.join(dir_path, "fundamentals.csv")
    if os.path.exists(fund_path):
        rows = _read_csv(fund_path)
        no_avail = [
            r
            for r in rows
            if not (r.get("available_date") or "").strip() or not (r.get("report_date") or "").strip()
        ]
        bad = [
            r
            for r in rows
            if (r.get("available_date") or "").strip()
            and (r.get("report_date") or "").strip()
            and r["available_date"] < r["report_date"]
        ]
        if no_avail:
            # 缺公告日就只能用报告期，等于把未来的财报提前算进今天
            checks.append(
                _fail(
                    "fundamentals.availability",
                    f"{len(no_avail)} 条财报缺少 available_date（公告日）或 report_date",
                )
            )
        elif bad:
            checks.append(_fail("fundamentals.availability", f"{len(bad)} 条公告日早于报告期"))
        else:
            checks.append(_pass("fundamentals.availability", f"{len(rows)} 条财报公告日合法"))
    else:
        checks.append(_warn("fundamentals.missing", "没有 fundamentals.csv：价值/质量因子不可用"))

    # 6) 复权声明
    adjust = manifest.get("adjust_mode")
    has_factor_col = "adj_factor" in (prices[0].keys() if prices else [])
    if adjust in ("forward", "backward") and not has_factor_col:
        checks.append(_warn("prices.adjust", f"manifest 声明 {adjust}，但 prices.csv 没有 adj_factor 列"))
    else:
        checks.append(_pass("prices.adjust", f"adjust_mode={adjust}"))

    # 7) 时点成分：日期要全覆盖，标的不许越界
    #    "某天没有成分行"不等于"当天空池"——前者是数据没导全，后者会让回测凭空空仓。
    uni_path = os.path.join(dir_path, "universe.csv")
    if os.path.exists(uni_path):
        uni_rows = _read_csv(uni_path)
        uni_dates = {r["date"] for r in uni_rows if r.get("date")}
        uni_assets = {r["asset"] for r in uni_rows if r.get("asset")}
        unknown = sorted(uni_assets - set(assets))
        missing_dates = sorted(set(expected_dates) - uni_dates)
        if missing_dates:
            checks.append(
                _fail(
                    "universe.coverage",
                    f"{len(missing_dates)} 个交易日没有成分（例如 {missing_dates[:3]}）",
                )
            )
        elif unknown:
            checks.append(_warn("universe.assets", f"{len(unknown)} 个成分没有行情：{unknown[:3]}"))
        else:
            checks.append(
                _pass("universe.coverage", f"{len(uni_dates)} 个交易日、{len(uni_assets)} 个标的的时点成分")
            )

    ok = all(c["status"] != "fail" for c in checks)
    stats = {
        "dates": len(expected_dates),
        "assets": len(assets),
        "rows": len(prices),
        "start": expected_dates[0],
        "end": expected_dates[-1],
        "worst_missing_ratio": worst,
    }
    return {"ok": ok, "checks": checks, "stats": stats}
