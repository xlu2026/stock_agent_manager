"""券商 QMT（迅投 xtquant）数据适配器。

> ⚠️ **未在本机验证**：本仓库所在机器没装 QMT 终端，也没有 `xtquant` 包。
> 这份代码是按 xtquant 的公开接口写的骨架，第一次在你机器上跑时，
> 函数名、字段名、返回结构都可能需要按你的券商版本微调。别把"能 import"当成"能用"。

> 2026-10 起 QMT 客户端限制联网与本地文件读写，但**终端里已下载的数据仍可读**
> （用户已向券商确认）。所以本模块只调用读接口，**绝不调用 `download_history_data`**：
> 没有的数据就是没有，要去终端里手工补，或者换数据源。
> 入口在 `scripts/export_qmt_snapshot.py`，`--probe` 可以只看本地有什么。

前置条件（都在你的 Windows 机器上，不在这台机器上）：

1. QMT 终端已安装并登录，且该券商开通了量化权限；
2. `xtquant` 能 import——通常在 QMT 安装目录的 `bin.x64` 或 `Lib/site-packages` 下，
   需要把它加进 `sys.path`，或 `pip install xtquant`；
3. 历史数据已下载：`xtdata.download_history_data(code, period='1d', start_time=..., end_time=...)`。
   **没下载就直接取，会拿到空表。**

复权的处理：本适配器直接取"后复权"价（`dividend_type='back'`），因此 `adj_factor` 一律写 1.0、
`adjust_mode='backward'`。**不要把后复权价再乘一次因子**，那会二次复权。

停牌的处理：QMT 对停牌日可能返回缺失行或全 0 行。这里统一成"沿用前收盘、成交量 0"，
并在 `notes.suspended_filled` 里记录被填充的条数——填充是为了让面板保持矩形，
但它是**编造出来的价格**，回测时必须知道有多少条。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..console import force_utf8  # noqa: F401  (保持脚本行为一致)
from .contract import Snapshot

DEFAULT_FIELDS = ["open", "high", "low", "close", "volume"]


def _norm_date(value) -> str:
    """xtquant 的日期可能是毫秒时间戳、'YYYYMMDD' 或 'YYYY-MM-DD'。"""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) >= 10:
        return text[:10]
    raise ValueError(f"无法识别的日期格式：{value!r}")


class QmtProvider:
    """QMT 适配器。`name` 会写进 manifest，方便追溯数据来源。"""

    name = "qmt"
    adjust_mode = "backward"

    def __init__(self, *, dividend_type: str = "back", data_dir: str | None = None) -> None:
        if dividend_type not in ("none", "front", "back"):
            raise ValueError("dividend_type 只能是 none / front / back")
        self.dividend_type = dividend_type
        self.data_dir = data_dir

    # ------------------------------------------------------------------ 取数

    def _xtdata(self):
        try:
            from xtquant import xtdata  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖本机环境
            raise RuntimeError(
                "找不到 xtquant。请确认 QMT 终端已安装，并把它的 bin.x64 目录加入 sys.path，"
                "或在装了终端的环境里 pip install xtquant。"
            ) from exc
        return xtdata

    def trading_dates(self, start: str, end: str) -> list[str]:
        xtdata = self._xtdata()
        raw = xtdata.get_trading_dates("SH", start_time=start, end_time=end)
        return sorted({_norm_date(x) for x in raw})

    def fetch(
        self,
        start: str,
        end: str,
        universe: str,
        *,
        stocks: list[str] | None = None,
        sector: str | None = None,
        universe_map: dict[str, list[str]] | None = None,
        fundamentals: list[dict] | None = None,
    ) -> Snapshot:
        """取行情并组装快照。

        `universe_map`（date -> [code]）是**时点成分股**。不给的话只能退化成"当前成分"，
        这会引入幸存者偏差——所以会在 notes 里明确标出来，而不是假装没有。
        """
        xtdata = self._xtdata()

        if stocks is None:
            if sector:
                stocks = list(xtdata.get_stock_list_in_sector(sector))
            else:
                raise ValueError("必须给 stocks 或 sector，否则不知道该取哪些标的")
        stocks = [s for s in stocks if s]

        data = xtdata.get_market_data_ex(
            field_list=DEFAULT_FIELDS,
            stock_list=stocks,
            period="1d",
            start_time=start,
            end_time=end,
            dividend_type=self.dividend_type,
        )

        notes: dict = {"dividend_type": self.dividend_type, "stock_count": len(stocks)}
        prices: list[dict] = []
        suspended = 0

        for code, frame in (data or {}).items():
            if frame is None or len(frame) == 0:
                notes.setdefault("empty_symbols", []).append(code)
                continue
            last_close = None
            for index, row in frame.iterrows():
                date = _norm_date(index)
                close = float(row.get("close") or 0.0)
                volume = float(row.get("volume") or 0.0)
                if close <= 0:
                    # 停牌：沿用前收盘，成交量记 0，并计数（见模块说明）
                    if last_close is None:
                        continue
                    close = last_close
                    volume = 0.0
                    suspended += 1
                open_ = float(row.get("open") or close)
                high = float(row.get("high") or max(open_, close))
                low = float(row.get("low") or min(open_, close))
                prices.append(
                    {
                        "date": date,
                        "asset": code,
                        "open": round(open_, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "close": round(close, 4),
                        "volume": int(volume),
                        "adj_factor": 1.0,  # 已经是后复权价
                    }
                )
                last_close = close

        notes["suspended_filled"] = suspended

        universe_rows: list[dict] = []
        if universe_map:
            for date, codes in universe_map.items():
                for code in codes:
                    universe_rows.append({"date": _norm_date(date), "asset": code})
            notes["universe_point_in_time"] = True
        else:
            notes["universe_point_in_time"] = False
            notes["universe_warning"] = "未提供时点成分股，回测将带幸存者偏差"

        calendar_rows = [{"date": d} for d in self.trading_dates(start, end)]

        return Snapshot(
            universe=universe,
            source="qmt / xtquant",
            provider=f"{self.name}:{self.dividend_type}",
            adjust_mode=self.adjust_mode,
            prices=prices,
            fundamentals=fundamentals or [],
            universe_rows=universe_rows,
            calendar=calendar_rows,
            notes=notes,
        )

    # ---------------------------------------------------------------- 财报

    def fetch_fundamentals(self, start: str, end: str, stocks: list[str]) -> list[dict]:
        """财报数据**故意不自动取**。

        原因：QMT 各券商版本的财务表名、字段名差异很大（`Balance` / `Income` / `m_anntime` 之类），
        写错字段名不会报错，只会让你拿到空值——然后价值因子静默失效。
        更危险的是**公告日**：拿不到 `available_date` 就只能用报告期，那是前视偏差。

        所以这里直接抛错，逼你先确认字段：
        1. 在你的终端上跑 `xtdata.get_financial_data(...)`，把返回的列名贴出来；
        2. 确认有"公告日/披露日"字段（通常叫 `m_anntime`、`ann_date` 或类似）；
        3. 按报告期 + 公告日导出成 `fundamentals.csv`，作为 `fetch(fundamentals=...)` 传入。
        """
        raise NotImplementedError(
            "QMT 财务数据的表名与公告日字段因券商版本而异，未做自动适配。"
            "请先导出 fundamentals.csv（asset, report_date, available_date, book, earnings），"
            "再通过 fetch(fundamentals=...) 传入。"
        )
