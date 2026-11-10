"""数据快照的加载与指纹校验。

一个快照就是一个目录：``prices.csv`` + ``manifest.json``，v2 还可能有
``fundamentals.csv`` / ``universe.csv`` / ``calendar.csv``。
快照目录默认是 ``quant/data/``，可用环境变量 ``NFR_DATA_DIR`` 或
``load_panel(dir)`` 参数切到别处——这样"真实数据"不必覆盖合成样本。

v1（合成样本）与 v2 的差别，本模块用**缺省值**吸收掉：

- 没有 ``adj_factor`` 列 -> 因子视为 1.0，价格按原样使用；
- 没有 ``fundamentals.csv`` -> 用 ``prices.csv`` 里的 ``book``/``earnings`` 列（v1 的做法）；
- 没有 ``universe.csv`` -> 全池每天有效（等价于"固定成分"，v1 的做法）。

v2 的三件事各自防一个错：

- ``adj_factor``：不复权价算收益，除权日就是假跌停；
- ``available_date``：用报告期当日数据 = 前视偏差，所以财报按**公告日**生效；
- ``universe.csv``：用今天的成分股回测五年前 = 幸存者偏差，所以成分按**日期**生效。

**停牌/退市造成的空洞**：``Panel`` 的序列必须等长（下标即交易日序号），
所以缺失的 (date, asset) 会用"最近一次收盘价"补齐、成交量记 0，并在
``Panel.filled_rows`` 里计数。这不是免费午餐——填充出来的是编造的价格，
引擎会把它写进 provenance，体检（``snapshot_check``）会用交易日历当分母
把缺口显形。补数据是 Provider 的责任，这里是最后一道兜底。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_DIR_ENV = "NFR_DATA_DIR"
PRICES_CSV = "prices.csv"
MANIFEST_JSON = "manifest.json"
FUNDAMENTALS_CSV = "fundamentals.csv"
UNIVERSE_CSV = "universe.csv"
CALENDAR_CSV = "calendar.csv"

PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
INLINE_FUNDAMENTAL_COLUMNS = ("book", "earnings")
NAN = float("nan")


class DataError(RuntimeError):
    """数据快照缺失、被篡改或与约定不符。"""


@dataclass(frozen=True)
class Panel:
    """按日期对齐的日频面板；所有序列等长，下标即交易日序号。"""

    dates: list[str]
    assets: list[str]
    close: dict[str, list[float]]
    open: dict[str, list[float]]
    high: dict[str, list[float]]
    low: dict[str, list[float]]
    volume: dict[str, list[float]]
    book: dict[str, list[float]]
    earnings: dict[str, list[float]]
    universe: str
    data_version: str
    data_sha256: str
    # ---- v2 补充信息：不参与计算，但决定你敢不敢信这份数据 ----
    source: str = "unknown"
    provider: str = ""
    adjust_mode: str = "none"
    schema_version: int = 1
    notes: dict = field(default_factory=dict)
    # 时点成分：date -> 当日有效标的。None 表示没有 universe.csv（全池每天有效）。
    universe_by_date: dict[str, tuple[str, ...]] | None = None
    # 被"前收盘填充"的 (date, asset) 单元格数量
    filled_rows: int = 0

    def index_of(self, date: str) -> int:
        """返回 >= date 的第一个交易日下标；用于把 spec 日期对齐到日历。"""
        lo, hi = 0, len(self.dates) - 1
        if date <= self.dates[lo]:
            return lo
        if date > self.dates[hi]:
            return -1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.dates[mid] < date:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def allowed_at(self, i: int) -> tuple[str, ...] | None:
        """第 i 个交易日的有效标的；None 表示这份快照没有时点成分。"""
        if self.universe_by_date is None:
            return None
        return self.universe_by_date.get(self.dates[i], ())

    def has_point_in_time_universe(self) -> bool:
        return self.universe_by_date is not None


def data_dir_path(override: str | None = None) -> str:
    """快照目录的解析顺序：显式参数 > 环境变量 > 仓库内置合成样本。"""
    if override:
        return os.path.abspath(override)
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return os.path.abspath(env)
    return DATA_DIR


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    """读 CSV 并统一表头/取值两端空白（导出工具常带空格和 BOM）。"""
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


def _float(value, where: str) -> float:
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text:
        raise DataError(f"{where} 为空，无法解析成数字")
    try:
        return float(text)
    except ValueError as exc:
        raise DataError(f"{where} 不是数字：{value!r}") from exc


def _calendar_dates(dir_path: str) -> list[str]:
    path = os.path.join(dir_path, CALENDAR_CSV)
    if not os.path.exists(path):
        return []
    _, rows = _read_csv(path)
    return sorted({r["date"] for r in rows if r.get("date")})


def _pit_fundamentals(
    dir_path: str, assets: list[str], dates: list[str]
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """按公告日（available_date）把财报展开成日频序列。

    没有可用财报的日期记 NaN——**不往前填充**。往前填等于"下一期财报提前生效"，
    是典型前视偏差；NaN 会让 value/quality 因子自然缺席，而不是给一个假分数。
    """
    path = os.path.join(dir_path, FUNDAMENTALS_CSV)
    _, rows = _read_csv(path)
    per_asset: dict[str, list[tuple[str, float, float]]] = {}
    for n, row in enumerate(rows, start=2):
        asset = row.get("asset") or ""
        report = row.get("report_date") or ""
        avail = row.get("available_date") or report
        if not asset:
            raise DataError(f"fundamentals.csv 第 {n} 行 asset 为空")
        if not avail:
            raise DataError(f"fundamentals.csv 第 {n} 行缺少 report_date/available_date")
        per_asset.setdefault(asset, []).append(
            (
                avail,
                _float(row.get("book"), f"fundamentals.csv 第 {n} 行 book"),
                _float(row.get("earnings"), f"fundamentals.csv 第 {n} 行 earnings"),
            )
        )

    book_out: dict[str, list[float]] = {}
    earnings_out: dict[str, list[float]] = {}
    for asset in assets:
        history = sorted(per_asset.get(asset, []))
        series_book: list[float] = []
        series_earn: list[float] = []
        j = 0
        current: tuple[str, float, float] | None = None
        for d in dates:
            while j < len(history) and history[j][0] <= d:
                current = history[j]
                j += 1
            series_book.append(current[1] if current else NAN)
            series_earn.append(current[2] if current else NAN)
        book_out[asset] = series_book
        earnings_out[asset] = series_earn
    return book_out, earnings_out


def _universe_by_date(
    dir_path: str, dates: list[str], assets: list[str]
) -> dict[str, tuple[str, ...]] | None:
    path = os.path.join(dir_path, UNIVERSE_CSV)
    if not os.path.exists(path):
        return None
    _, rows = _read_csv(path)
    known = set(assets)
    per_date: dict[str, set[str]] = {}
    unknown: set[str] = set()
    for n, row in enumerate(rows, start=2):
        d = row.get("date") or ""
        a = row.get("asset") or ""
        if not d or not a:
            raise DataError(f"universe.csv 第 {n} 行 date/asset 为空")
        if a not in known:
            unknown.add(a)
            continue
        per_date.setdefault(d, set()).add(a)
    if unknown:
        raise DataError(
            f"universe.csv 里有 {len(unknown)} 个标的在 prices.csv 中不存在：{sorted(unknown)[:5]}"
        )
    missing = [d for d in dates if d not in per_date]
    if missing:
        raise DataError(
            f"universe.csv 缺少 {len(missing)} 个交易日的成分（例如 {missing[:3]}）；"
            "缺日期不等于「当天空池」，要么补齐，要么删掉 universe.csv 用固定成分"
        )
    return {d: tuple(sorted(per_date[d])) for d in dates}


def _build_market_series(
    rows: list[dict], fields: list[str], dates: list[str], assets: list[str]
) -> tuple[dict[str, dict[str, list[float]]], int]:
    """组装价格面板，返回 (按列组织的序列, 填充单元格数)。"""
    has_factor = "adj_factor" in fields
    has_inline_fundamentals = all(c in fields for c in INLINE_FUNDAMENTAL_COLUMNS)
    columns = PRICE_COLUMNS + (INLINE_FUNDAMENTAL_COLUMNS if has_inline_fundamentals else ())

    by_date: dict[str, dict[str, dict[str, float]]] = {}
    for n, row in enumerate(rows, start=2):
        d = row.get("date") or ""
        a = row.get("asset") or ""
        if not d or not a:
            raise DataError(f"prices.csv 第 {n} 行 date/asset 为空")
        vals = {c: _float(row.get(c), f"prices.csv 第 {n} 行 {c}") for c in columns}
        # 收益必须用复权价算：把因子乘回价格。没有这一列时因子就是 1.0。
        factor = 1.0
        if has_factor and row.get("adj_factor"):
            factor = _float(row["adj_factor"], f"prices.csv 第 {n} 行 adj_factor")
            if factor <= 0:
                raise DataError(f"prices.csv 第 {n} 行 adj_factor <= 0（{factor}）")
        if factor != 1.0:
            for c in ("open", "high", "low", "close"):
                vals[c] = vals[c] * factor
        bucket = by_date.setdefault(d, {})
        if a in bucket:
            raise DataError(f"prices.csv 第 {n} 行重复：{d} {a}（同一 (date,asset) 只能有一行）")
        bucket[a] = vals

    series: dict[str, dict[str, list[float]]] = {
        c: {a: [] for a in assets} for c in columns + ("book", "earnings")
    }
    first_close: dict[str, float] = {}
    for d in dates:
        for a, row in by_date.get(d, {}).items():
            if a in series["close"]:
                first_close.setdefault(a, row["close"])

    last_close: dict[str, float] = {}
    last_fundamentals: dict[str, dict[str, float]] = {}
    filled = 0
    for d in dates:
        bucket = by_date.get(d, {})
        for a in assets:
            row = bucket.get(a)
            if row is None:
                px = last_close.get(a, first_close.get(a))
                if px is None:
                    raise DataError(f"资产 {a} 在整份快照里没有任何行情")
                filled += 1
                for c in ("open", "high", "low", "close"):
                    series[c][a].append(px)
                series["volume"][a].append(0.0)
                for c in INLINE_FUNDAMENTAL_COLUMNS:
                    series[c][a].append(last_fundamentals.get(a, {}).get(c, NAN))
                continue
            for c in PRICE_COLUMNS:
                series[c][a].append(row[c])
            last_close[a] = row["close"]
            if has_inline_fundamentals:
                last_fundamentals[a] = {c: row[c] for c in INLINE_FUNDAMENTAL_COLUMNS}
            for c in INLINE_FUNDAMENTAL_COLUMNS:
                series[c][a].append(row[c] if has_inline_fundamentals else NAN)
    return series, filled


def _manifest_assets(manifest: dict) -> list[str]:
    assets = [str(a).strip() for a in (manifest.get("assets") or []) if str(a).strip()]
    return list(dict.fromkeys(assets))


def _infer_source(manifest: dict) -> str:
    explicit = str(manifest.get("source") or "").strip()
    if explicit:
        return explicit
    if manifest.get("generator"):
        # v1 合成样本的清单没有 source 字段，只有 generator
        return "synthetic_sample"
    return "unknown"


def load_panel(data_dir: str | None = None) -> Panel:
    """读取并校验数据快照（进程内按目录缓存一次）。"""
    return _load_panel_at(data_dir_path(data_dir))


@lru_cache(maxsize=8)
def _load_panel_at(dir_path: str) -> Panel:
    manifest_path = os.path.join(dir_path, MANIFEST_JSON)
    prices_path = os.path.join(dir_path, PRICES_CSV)
    if not os.path.exists(manifest_path):
        raise DataError(f"缺少数据清单 {manifest_path}；请先运行 tools/gen_sample_data.py")
    if not os.path.exists(prices_path):
        raise DataError(f"缺少数据文件 {prices_path}")

    manifest = _read_json(manifest_path)
    actual = _sha256_file(prices_path)
    expected = manifest.get("sha256")
    if expected and actual != expected:
        raise DataError(
            "数据指纹不一致：prices.csv 与 manifest.json 不匹配，"
            f"expected={str(expected)[:12]} actual={actual[:12]}"
        )

    fields, rows = _read_csv(prices_path)
    price_dates = sorted({r["date"] for r in rows if r.get("date")})
    if not price_dates:
        raise DataError(f"{prices_path} 里没有任何行情行")

    calendar = _calendar_dates(dir_path)
    if calendar:
        extra = sorted(set(price_dates) - set(calendar))
        if extra:
            raise DataError(f"{len(extra)} 个行情日期不在 calendar.csv 里（例如 {extra[:3]}）")
        empty_days = sorted(set(calendar) - set(price_dates))
        if empty_days:
            raise DataError(
                f"calendar.csv 里有 {len(empty_days)} 个交易日没有任何行情（例如 {empty_days[:3]}）；"
                "整段消失是最危险的截断，拒绝加载"
            )
        dates = calendar
    else:
        dates = price_dates

    price_assets = sorted({r["asset"] for r in rows if r.get("asset")})
    assets = _manifest_assets(manifest)
    assets = assets + [a for a in price_assets if a not in set(assets)]
    if not assets:
        raise DataError("数据快照资产列表为空")

    series, filled = _build_market_series(rows, fields, dates, assets)

    if os.path.exists(os.path.join(dir_path, FUNDAMENTALS_CSV)):
        series["book"], series["earnings"] = _pit_fundamentals(dir_path, assets, dates)

    return Panel(
        dates=dates,
        assets=assets,
        close=series["close"],
        open=series["open"],
        high=series["high"],
        low=series["low"],
        volume=series["volume"],
        book=series["book"],
        earnings=series["earnings"],
        universe=str(manifest.get("universe") or "unknown"),
        data_version="dv-" + actual[:12],
        data_sha256=actual,
        source=_infer_source(manifest),
        provider=str(manifest.get("provider") or ""),
        adjust_mode=str(manifest.get("adjust_mode") or "none"),
        schema_version=int(manifest.get("schema_version") or 1),
        notes=dict(manifest.get("notes") or {}),
        universe_by_date=_universe_by_date(dir_path, dates, assets),
        filled_rows=filled,
    )


def assert_universe(panel: Panel, universe: str) -> None:
    """确认请求的标的池就是这份快照的标的池——不是"资产列表非空"这种恒真检查。

    v2 起不再维护硬编码白名单：池名来自快照自己的 manifest，真实数据不必
    改代码才能用。跨池仍然拒绝，错误信息里给出切换快照的办法。
    """
    if not isinstance(universe, str) or not universe.strip():
        raise DataError(f"universe 必须是非空字符串，收到 {universe!r}")
    if panel.universe != universe:
        raise DataError(
            f"数据快照属于 {panel.universe!r}，请求的是 {universe!r}；拒绝跨池回测"
            f"（要换数据请设环境变量 {DATA_DIR_ENV} 或调用 load_panel(dir)）"
        )
    if len(panel.assets) != len(set(panel.assets)) or not panel.assets:
        raise DataError("数据快照资产列表为空或存在重复")
