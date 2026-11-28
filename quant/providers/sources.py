"""数据源注册表：统一列出可用导出器。

目前 baostock 仍由脚本按 CLI 方式调用（它的增量/时点成分逻辑和 Provider 协议
不完全同构），AkShare 已提供 `build_snapshot` 函数。注册表的目的是让
Agent 2 / CLI 不再硬编码"只有 baostock"，而不是强行把所有源塞进一个接口。
"""
from __future__ import annotations

from .akshare import build_snapshot as akshare_build_snapshot

SOURCES = {
    "akshare": akshare_build_snapshot,
}


def get_source(name: str):
    try:
        return SOURCES[name]
    except KeyError as exc:
        raise KeyError(f"未知数据源 {name!r}；可用：{sorted(SOURCES)}") from exc


def list_sources() -> list[str]:
    return sorted(SOURCES)
