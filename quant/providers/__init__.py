"""数据源适配层。

目录约定（有个坑）：`quant/data.py` 是**模块**，`quant/data/` 是**数据文件目录**，
两者同名共存。所以**绝对不能**在 `quant/data/` 里放 `__init__.py`——一旦放进去，
Python 会把这个目录当成包，`import quant.data` 就会去加载空包而不是加载器，整个项目起不来。
适配器因此放在 `quant/providers/`。

| 文件 | 职责 |
|---|---|
| `contract.py` | 快照规范（schema v2）+ 写入器（含 sha256） |
| `base.py` | `Provider` 协议 |
| `qmt.py` | 券商 QMT / xtquant 适配器（骨架，未在本机验证） |
| `csv_import.py` | 通用 CSV 导入器：任意来源 -> schema v2（**换数据源的首选入口**） |
| `snapshot_check.py` | 快照体检：能挡掉绝大多数脏数据 |
"""
from .contract import SCHEMA_VERSION, ContractError, Snapshot, write_snapshot

__all__ = ["SCHEMA_VERSION", "ContractError", "Snapshot", "write_snapshot"]
