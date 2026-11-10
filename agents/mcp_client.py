"""最小 MCP stdio 客户端（标准库实现）。

Agent 1 通过它与 srq MCP 服务端通信，走的是 LLM 未来会走的同一条协议路径，
而不是绕过协议直接 import 引擎——这样"工具面是否真的可用"才算被验证过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, command: list[str] | None = None, cwd: str | None = None) -> None:
        self.command = command or [sys.executable, "-m", "quant.cli", "mcp", "serve"]
        self.cwd = cwd or ROOT
        self.proc: subprocess.Popen | None = None
        self._id = 0

    def __enter__(self) -> "McpClient":
        env = dict(os.environ)
        env["PYTHONPATH"] = self.cwd
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "agent1-quant", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc:
            if self.proc.stdin:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            for stream in (self.proc.stdout, self.proc.stderr):
                if stream:
                    stream.close()

    # -- 内部
    def _notify(self, method: str, params: dict | None = None) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict | None = None) -> dict:
        assert self.proc and self.proc.stdin and self.proc.stdout
        self._id += 1
        self.proc.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}},
                ensure_ascii=False,
            )
            + "\n"
        )
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise McpError(f"MCP 服务端无响应（{method}）；stderr:\n{err}")
        msg = json.loads(line)
        if "error" in msg:
            raise McpError(f"{method} 失败：{msg['error']}")
        return msg.get("result", {})

    # -- 对外
    def list_tools(self) -> list[dict]:
        return self._request("tools/list").get("tools", [])

    def call(self, name: str, arguments: dict) -> dict:
        res = self._request("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            text = "\n".join(b.get("text", "") for b in res.get("content", []))
            raise McpError(text.strip() or f"{name} 返回错误")
        structured = res.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        # 兜底：服务端只给了文本时，尝试按 JSON 解析
        text = "\n".join(b.get("text", "") for b in res.get("content", []))
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpError(f"{name} 返回内容不是 JSON：{text[:200]}") from exc
