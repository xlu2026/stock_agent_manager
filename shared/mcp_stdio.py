"""中立的 MCP stdio 协议实现（纯标准库）。

放在 shared/ 而不是 quant/ 或 writing/，是为了让两侧都能复用同一份协议代码
而互不 import：量化服务端和写作的草稿服务端各自只提供工具定义。
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

DEFAULT_PROTOCOLS = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
FALLBACK_PROTOCOL = "2025-06-18"


def log(prefix: str, msg: str) -> None:
    sys.stderr.write(f"[{prefix}] {msg}\n")
    sys.stderr.flush()


class McpServer:
    """一行一个 JSON-RPC 消息的 MCP 服务端；stdout 只走协议，日志走 stderr。"""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        instructions: str = "",
        tools: list[dict[str, Any]],
        protocols: list[str] | None = None,
        in_stream=None,
        out_stream=None,
    ) -> None:
        self.name = name
        self.version = version
        self.instructions = instructions
        self.tools = tools
        self.tool_map: dict[str, Callable[[dict], dict]] = {t["name"]: t["handler"] for t in tools}
        self.protocols = protocols or DEFAULT_PROTOCOLS
        self.inp = in_stream or sys.stdin
        self.out = out_stream or sys.stdout
        self.initialized = False

    # -- 传输
    def _send(self, payload: dict) -> None:
        self.out.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.out.flush()

    def _error(self, msg_id, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    # -- 方法
    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = requested if requested in self.protocols else FALLBACK_PROTOCOL
        self.initialized = True
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def _list_tools(self) -> dict:
        return {
            "tools": [
                {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in self.tools
            ]
        }

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in self.tool_map:
            return {
                "content": [{"type": "text", "text": f"未知工具 {name!r}；可用：{sorted(self.tool_map)}"}],
                "isError": True,
            }
        if not isinstance(args, dict):
            return {"content": [{"type": "text", "text": "arguments 必须是 JSON 对象"}], "isError": True}
        try:
            payload = self.tool_map[name](args)
        except (ValueError, KeyError, RuntimeError) as exc:
            log(self.name, f"tool {name} rejected: {exc}")
            return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
        except Exception as exc:  # noqa: BLE001 - 协议层必须捕获一切，避免服务端崩溃
            log(self.name, f"tool {name} failed:\n{traceback.format_exc()}")
            return {"content": [{"type": "text", "text": f"内部错误：{exc}"}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        }

    def handle(self, msg: dict) -> dict | None:
        if msg.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32600, "message": "invalid request"}}
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}
        if method is None:
            return None
        if msg_id is None:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        try:
            if method == "initialize":
                return {"jsonrpc": "2.0", "id": msg_id, "result": self._initialize(params)}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": msg_id, "result": self._list_tools()}
            if method == "tools/call":
                return {"jsonrpc": "2.0", "id": msg_id, "result": self._call_tool(params)}
            if method == "resources/list":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}
            if method == "resources/templates/list":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"resourceTemplates": []}}
            if method == "prompts/list":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}
        except Exception as exc:  # noqa: BLE001
            log(self.name, f"dispatch error {method}: {traceback.format_exc()}")
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}

    def serve(self) -> int:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        log(self.name, f"ready on stdio (protocols: {', '.join(self.protocols)})")
        for line in self.inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                self._error(None, -32700, f"parse error: {exc}")
                continue
            if isinstance(msg, list):
                replies = [r for r in (self.handle(m) for m in msg) if r]
                if replies:
                    self._send(replies)
                continue
            reply = self.handle(msg)
            if reply is not None:
                self._send(reply)
        log(self.name, "stdin closed, exiting")
        return 0
