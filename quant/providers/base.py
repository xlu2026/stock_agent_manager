"""数据源适配器：把某家数据商的东西，翻译成 `contract.Snapshot`。

约定：**Provider 只负责取数与翻译，不负责落盘、不负责校验**。
落盘由 `contract.write_snapshot` 做，体检由 `snapshot_check` 做——
这样换数据源时，只有这一个文件要重写。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contract import Snapshot


@runtime_checkable
class Provider(Protocol):
    name: str
    adjust_mode: str  # none | forward | backward

    def fetch(self, start: str, end: str, universe: str) -> Snapshot:
        """取 [start, end] 区间，返回规范快照。失败要抛错，不要返回半份数据。"""
        ...
