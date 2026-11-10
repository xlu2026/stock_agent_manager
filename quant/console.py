"""控制台编码修正。

Windows 下管道/重定向时 Python 的 stdout 默认是 cp936（GBK），
中文会变成乱码甚至 UnicodeEncodeError。所有对外输出统一改用 UTF-8，
这样 ``> report.json`` 得到的就是干净 UTF-8 文件。
"""
from __future__ import annotations

import sys


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def force_utf8_all() -> None:
    """含 stdin，供 MCP stdio 服务端使用。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
