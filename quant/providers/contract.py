"""数据快照的规范格式（schema v2）与写入器。

设计目标：**生产者（各家数据源）产出同一套文件，消费者（引擎）只认这一套。**

v1（现有合成数据）只有 `prices.csv` + `manifest.json`，等价于"无复权、财报当期可用、池子固定"。
v2 增加了三样真实数据绕不过去的东西：

- `adj_factor`：复权因子。收益必须用复权价算，否则除权日会出现假暴跌；
- `available_date`：财报**实际公布日**。用报告期当期数据就是前视偏差；
- `universe.csv`：**时点**成分股。用今天的名单回测五年前，就是幸存者偏差。

v1 的快照仍然能读（缺什么补默认值），所以合成数据那份不受影响。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field

SCHEMA_VERSION = 2

PRICES_FIELDS = ["date", "asset", "open", "high", "low", "close", "volume", "adj_factor"]
FUNDAMENTAL_FIELDS = ["asset", "report_date", "available_date", "book", "earnings"]
UNIVERSE_FIELDS = ["date", "asset"]
CALENDAR_FIELDS = ["date"]


class ContractError(ValueError):
    pass


@dataclass
class Snapshot:
    """一份待落盘的数据快照。所有列表里的 dict 必须严格按字段名。"""

    universe: str
    source: str
    provider: str
    adjust_mode: str  # none | forward | backward
    prices: list[dict] = field(default_factory=list)
    fundamentals: list[dict] = field(default_factory=list)
    universe_rows: list[dict] = field(default_factory=list)
    calendar: list[dict] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def assets(self) -> list[str]:
        return sorted({r["asset"] for r in self.prices})

    def dates(self) -> list[str]:
        if self.calendar:
            return sorted({r["date"] for r in self.calendar})
        return sorted({r["date"] for r in self.prices})


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_csv(path: str, fields: list[str], rows: list[dict]) -> int:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            missing = [f for f in fields if f not in row]
            if missing:
                raise ContractError(f"{os.path.basename(path)} 缺少字段 {missing}: {row}")
            w.writerow({f: row[f] for f in fields})
    return len(rows)


def write_snapshot(out_dir: str, snap: Snapshot) -> dict:
    """把快照写成规范文件，并生成含 sha256 的 manifest。返回 manifest。"""
    if not snap.prices:
        raise ContractError("prices 为空，拒绝写快照")
    os.makedirs(out_dir, exist_ok=True)

    files: dict[str, dict] = {}
    counts = {
        "prices.csv": _write_csv(os.path.join(out_dir, "prices.csv"), PRICES_FIELDS, snap.prices),
        "calendar.csv": _write_csv(os.path.join(out_dir, "calendar.csv"), CALENDAR_FIELDS, snap.calendar),
    }
    if snap.fundamentals:
        counts["fundamentals.csv"] = _write_csv(
            os.path.join(out_dir, "fundamentals.csv"), FUNDAMENTAL_FIELDS, snap.fundamentals
        )
    if snap.universe_rows:
        counts["universe.csv"] = _write_csv(
            os.path.join(out_dir, "universe.csv"), UNIVERSE_FIELDS, snap.universe_rows
        )

    for name, rows in counts.items():
        path = os.path.join(out_dir, name)
        files[name] = {"sha256": _sha256_file(path), "rows": rows}

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "universe": snap.universe,
        "source": snap.source,
        "provider": snap.provider,
        "adjust_mode": snap.adjust_mode,
        "start": snap.dates()[0],
        "end": snap.dates()[-1],
        "assets": snap.assets(),
        "rows": counts["prices.csv"],
        # 生产者的自述：停牌填充了多少、有没有时点成分、用的哪种复权……
        # 这些不进回测，但决定了你敢不敢信这份数据。
        "notes": snap.notes,
        "files": files,
        # sha256 指 prices.csv，与 v1 的 data_version 语义保持兼容
        "sha256": files["prices.csv"]["sha256"],
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest
