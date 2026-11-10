"""把任意来源导出的 CSV 归一化成 schema v2 快照。

这是"数据从哪来"与"引擎怎么算"之间的解耦点：券商终端、通达信、公开接口、
手工导出的 Excel，只要能落成 CSV，就都能进同一套快照，拿到同一个 sha256
语义。换数据源时**不需要改引擎**，只需要换输入文件和列名映射。

    python -m quant.providers.csv_import \\
        --prices raw/prices.csv --out snapshots/mine \\
        --universe csi300 --source "通达信日线导出" \\
        --adjust-mode backward \\
        --map 收盘价=close --map 股票代码=asset

设计约定（和 `contract.py` 一致）：

- 只做"翻译 + 排序 + 落盘 + 体检"，不改数据、不补缺失、不做复权计算；
- 输入行序不影响输出：所有表都按 (date, asset) 等键排序后写出，sha256 稳定；
- 中英文表头都认，`--map 字段=列名` 可覆盖；
- `available_date` 缺失直接报错——宁可导不进来，也不要一个前视偏差的快照。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date as _date

from ..console import force_utf8
from ..data import DataError
from .contract import ContractError, Snapshot, write_snapshot
from .snapshot_check import check_snapshot

# 字段 -> 可接受的表头别名（按顺序尝试；比较时忽略大小写与空白）
PRICE_ALIASES = {
    "date": ("date", "日期", "交易日期", "trade_date", "datetime", "时间"),
    "asset": ("asset", "代码", "股票代码", "证券代码", "标的代码", "symbol", "code", "ticker"),
    "open": ("open", "开盘", "开盘价"),
    "high": ("high", "最高", "最高价"),
    "low": ("low", "最低", "最低价"),
    "close": ("close", "收盘", "收盘价"),
    "volume": ("volume", "成交量", "vol"),
    "adj_factor": ("adj_factor", "复权因子", "复权系数", "factor"),
}
FUNDAMENTAL_ALIASES = {
    "asset": PRICE_ALIASES["asset"],
    "report_date": ("report_date", "报告期", "报告日期", "报告期末"),
    "available_date": ("available_date", "公告日", "公告日期", "披露日", "披露日期", "ann_date"),
    "book": ("book", "净资产", "账面价值", "股东权益", "bv"),
    "earnings": ("earnings", "净利润", "盈利", "归母净利润", "ni"),
}
UNIVERSE_ALIASES = {
    "date": PRICE_ALIASES["date"],
    "asset": PRICE_ALIASES["asset"],
}
CALENDAR_ALIASES = {"date": PRICE_ALIASES["date"]}

_DATE_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),
    re.compile(r"^(\d{4})/(\d{2})/(\d{2})$"),
    re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
)


def normalize_date(value, where: str) -> str:
    """把 2024-01-02 / 20240102 / 2024/01/02 / 带时分秒的时间 统一成 YYYY-MM-DD。"""
    text = ("" if value is None else str(value)).strip()
    if not text:
        raise ContractError(f"{where} 日期为空")
    text = text.split(" ")[0].split("T")[0]
    for pattern in _DATE_PATTERNS:
        m = pattern.match(text)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return _date(y, mo, d).isoformat()
            except ValueError as exc:
                raise ContractError(f"{where} 不是合法日期：{value!r}") from exc
    raise ContractError(f"{where} 无法识别的日期格式：{value!r}（支持 2024-01-02 / 20240102 / 2024/01/02）")


def _number(value, where: str) -> float:
    text = ("" if value is None else str(value)).strip().replace(",", "").replace("，", "")
    if text in ("", "-", "--", "None", "null", "N/A", "nan"):
        raise ContractError(f"{where} 为空或不是数字：{value!r}")
    try:
        return float(text)
    except ValueError as exc:
        raise ContractError(f"{where} 不是数字：{value!r}") from exc


def _header_map(header: list[str], aliases: dict[str, tuple[str, ...]], mapping: dict[str, str]) -> dict[str, str]:
    """把"契约字段 -> 实际列名"解析出来；显式 mapping 优先。"""
    normalized = {h.strip().lower(): h.strip() for h in header}
    out: dict[str, str] = {}
    for field_name, names in aliases.items():
        override = mapping.get(field_name)
        if override:
            if override not in header:
                raise ContractError(f"--map 指定的列 {override!r} 不在表头 {header} 里")
            out[field_name] = override
            continue
        for candidate in names:
            hit = normalized.get(candidate.lower())
            if hit:
                out[field_name] = hit
                break
    return out


def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = [str(h).strip().lstrip("\ufeff") for h in next(reader)]
        except StopIteration:
            return [], []
        rows: list[dict] = []
        for raw in reader:
            if not raw or not any(str(c).strip() for c in raw):
                continue
            rows.append({k: str(v).strip() for k, v in zip(header, raw)})
    return header, rows


def read_prices(path: str, mapping: dict[str, str] | None = None) -> tuple[list[dict], bool]:
    """读取行情 CSV，返回 (按 (date,asset) 排序的行, 输入是否带复权因子列)。"""
    mapping = mapping or {}
    header, rows = _read_csv(path)
    cols = _header_map(header, PRICE_ALIASES, mapping)
    missing = [f for f in ("date", "asset", "open", "high", "low", "close", "volume") if f not in cols]
    if missing:
        raise ContractError(
            f"{os.path.basename(path)} 缺少列 {missing}（表头：{header}）；"
            "用 --map 字段=列名 显式指定"
        )
    has_factor = "adj_factor" in cols
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for n, row in enumerate(rows, start=2):
        d = normalize_date(row.get(cols["date"]), f"{os.path.basename(path)} 第 {n} 行")
        a = row.get(cols["asset"], "")
        if not a:
            raise ContractError(f"{os.path.basename(path)} 第 {n} 行 asset 为空")
        key = (d, a)
        if key in seen:
            raise ContractError(f"{os.path.basename(path)} 第 {n} 行重复：{d} {a}")
        seen.add(key)
        volume = _number(row.get(cols["volume"]), f"{os.path.basename(path)} 第 {n} 行成交量")
        out.append(
            {
                "date": d,
                "asset": a,
                "open": _number(row.get(cols["open"]), f"{os.path.basename(path)} 第 {n} 行开盘"),
                "high": _number(row.get(cols["high"]), f"{os.path.basename(path)} 第 {n} 行最高"),
                "low": _number(row.get(cols["low"]), f"{os.path.basename(path)} 第 {n} 行最低"),
                "close": _number(row.get(cols["close"]), f"{os.path.basename(path)} 第 {n} 行收盘"),
                "volume": int(volume) if float(volume).is_integer() else volume,
                "adj_factor": (
                    _number(row.get(cols["adj_factor"]), f"{os.path.basename(path)} 第 {n} 行复权因子")
                    if has_factor and row.get(cols["adj_factor"])
                    else 1.0
                ),
            }
        )
    return sorted(out, key=lambda r: (r["date"], r["asset"])), has_factor


def read_fundamentals(path: str, mapping: dict[str, str] | None = None) -> list[dict]:
    mapping = mapping or {}
    header, rows = _read_csv(path)
    cols = _header_map(header, FUNDAMENTAL_ALIASES, mapping)
    missing = [f for f in ("asset", "report_date", "available_date", "book", "earnings") if f not in cols]
    if missing:
        raise ContractError(
            f"{os.path.basename(path)} 缺少列 {missing}（表头：{header}）；"
            "没有 available_date 就会引入前视偏差，所以这里不猜"
        )
    out: list[dict] = []
    for n, row in enumerate(rows, start=2):
        where = f"{os.path.basename(path)} 第 {n} 行"
        avail = row.get(cols["available_date"], "")
        if not avail:
            raise ContractError(f"{where} 公告日为空：没有公告日就无法按时点生效，拒绝导入")
        out.append(
            {
                "asset": row.get(cols["asset"], ""),
                "report_date": normalize_date(row.get(cols["report_date"]), where),
                "available_date": normalize_date(avail, where),
                "book": _number(row.get(cols["book"]), f"{where} book"),
                "earnings": _number(row.get(cols["earnings"]), f"{where} earnings"),
            }
        )
    return sorted(out, key=lambda r: (r["asset"], r["report_date"], r["available_date"]))


def read_universe(path: str, mapping: dict[str, str] | None = None) -> list[dict]:
    mapping = mapping or {}
    header, rows = _read_csv(path)
    cols = _header_map(header, UNIVERSE_ALIASES, mapping)
    missing = [f for f in ("date", "asset") if f not in cols]
    if missing:
        raise ContractError(f"{os.path.basename(path)} 缺少列 {missing}（表头：{header}）")
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for n, row in enumerate(rows, start=2):
        d = normalize_date(row.get(cols["date"]), f"{os.path.basename(path)} 第 {n} 行")
        a = row.get(cols["asset"], "")
        if not a:
            raise ContractError(f"{os.path.basename(path)} 第 {n} 行 asset 为空")
        if (d, a) in seen:
            continue
        seen.add((d, a))
        out.append({"date": d, "asset": a})
    return sorted(out, key=lambda r: (r["date"], r["asset"]))


def read_calendar(path: str, mapping: dict[str, str] | None = None) -> list[dict]:
    mapping = mapping or {}
    header, rows = _read_csv(path)
    cols = _header_map(header, CALENDAR_ALIASES, mapping)
    if "date" not in cols:
        raise ContractError(f"{os.path.basename(path)} 缺少 date 列（表头：{header}）")
    dates = {normalize_date(r.get(cols["date"]), f"{os.path.basename(path)} 第 {n} 行") for n, r in enumerate(rows, start=2)}
    return [{"date": d} for d in sorted(dates)]


def build_snapshot(
    prices: list[dict],
    *,
    universe: str,
    source: str,
    adjust_mode: str = "none",
    fundamentals: list[dict] | None = None,
    universe_rows: list[dict] | None = None,
    calendar: list[dict] | None = None,
    notes: dict | None = None,
) -> Snapshot:
    if not prices:
        raise ContractError("prices 为空，拒绝生成快照")
    if not universe.strip():
        raise ContractError("universe 名称不能为空")
    return Snapshot(
        universe=universe.strip(),
        source=source.strip() or "csv_import",
        provider="csv_import",
        adjust_mode=adjust_mode,
        prices=prices,
        fundamentals=fundamentals or [],
        universe_rows=universe_rows or [],
        calendar=calendar or [],
        notes=dict(notes or {}),
    )


def import_snapshot(
    out_dir: str,
    *,
    prices_path: str,
    universe: str,
    source: str = "csv_import",
    adjust_mode: str = "none",
    fundamentals_path: str | None = None,
    universe_path: str | None = None,
    calendar_path: str | None = None,
    mapping: dict[str, str] | None = None,
    extra_notes: dict | None = None,
) -> dict:
    """导入一份 CSV 快照并立即体检。返回 {ok, out_dir, manifest, check}。"""
    if adjust_mode not in ("none", "forward", "backward"):
        raise ContractError("adjust_mode 只能是 none / forward / backward")

    notes: dict = {
        "imported_by": "quant.providers.csv_import",
        "input": {"prices": os.path.basename(prices_path)},
        "column_map": dict(mapping or {}),
    }
    prices, has_factor = read_prices(prices_path, mapping)
    if not has_factor:
        notes["adj_factor_missing"] = True
        notes["adj_factor_note"] = "输入没有复权因子列，adj_factor 一律记 1.0：请确认导出的价格本身已复权"
    if fundamentals_path:
        notes["input"]["fundamentals"] = os.path.basename(fundamentals_path)
    if universe_path:
        notes["input"]["universe"] = os.path.basename(universe_path)
    if calendar_path:
        notes["input"]["calendar"] = os.path.basename(calendar_path)
    if extra_notes:
        notes.update(extra_notes)

    snapshot = build_snapshot(
        prices,
        universe=universe,
        source=source,
        adjust_mode=adjust_mode,
        fundamentals=read_fundamentals(fundamentals_path, mapping) if fundamentals_path else [],
        universe_rows=read_universe(universe_path, mapping) if universe_path else [],
        calendar=read_calendar(calendar_path, mapping) if calendar_path else [],
        notes=notes,
    )
    manifest = write_snapshot(out_dir, snapshot)
    result = check_snapshot(out_dir)
    return {
        "ok": result["ok"],
        "out_dir": os.path.abspath(out_dir),
        "data_version": "dv-" + manifest["sha256"][:12],
        "schema_version": manifest["schema_version"],
        "assets": len(manifest["assets"]),
        "rows": manifest["rows"],
        "has_fundamentals": bool(snapshot.fundamentals),
        "has_universe": bool(snapshot.universe_rows),
        "has_calendar": bool(snapshot.calendar),
        "check": result,
    }


def _parse_note(values: list[str]) -> dict:
    notes: dict = {}
    for item in values or []:
        if "=" not in item:
            raise ContractError(f"--note 需要 key=value 形式，收到 {item!r}")
        k, v = item.split("=", 1)
        notes[k.strip()] = v.strip()
    return notes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m quant.providers.csv_import",
        description="把任意来源的 CSV 归一化成 schema v2 快照并体检",
    )
    p.add_argument("--prices", required=True, help="行情 CSV（必需）")
    p.add_argument("--out", required=True, help="输出快照目录")
    p.add_argument("--universe", required=True, help="标的池名称，写进 manifest")
    p.add_argument("--source", default="csv_import", help="数据来源描述，写进 manifest")
    p.add_argument("--adjust-mode", default="none", choices=["none", "forward", "backward"])
    p.add_argument("--fundamentals", help="财报 CSV（asset, report_date, available_date, book, earnings）")
    p.add_argument("--universe-file", help="时点成分 CSV（date, asset）")
    p.add_argument("--calendar", help="交易日历 CSV（date）")
    p.add_argument("--map", action="append", default=[], metavar="字段=列名", help="显式列名映射，可重复")
    p.add_argument("--note", action="append", default=[], metavar="key=value", help="附加到 manifest.notes")
    return p


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)
    mapping: dict[str, str] = {}
    for item in args.map:
        if "=" not in item:
            print(f"--map 需要 字段=列名 形式，收到 {item!r}", file=sys.stderr)
            return 2
        k, v = item.split("=", 1)
        mapping[k.strip()] = v.strip()

    try:
        result = import_snapshot(
            args.out,
            prices_path=args.prices,
            universe=args.universe,
            source=args.source,
            adjust_mode=args.adjust_mode,
            fundamentals_path=args.fundamentals,
            universe_path=args.universe_file,
            calendar_path=args.calendar,
            mapping=mapping,
            extra_notes=_parse_note(args.note),
        )
    except (ContractError, DataError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    summary = {k: v for k, v in result.items() if k != "check"}
    summary["fails"] = [c for c in result["check"]["checks"] if c["status"] == "fail"]
    summary["stats"] = result["check"].get("stats", {})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not result["ok"]:
        print("\n体检未通过：这份快照不要拿去回测。", file=sys.stderr)
        return 1
    print(f"\n写入 {result['out_dir']}（{result['data_version']}），体检通过。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
