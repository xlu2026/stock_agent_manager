"""McpClient 的 stderr 排空：服务端刷大量日志时不能死锁。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.mcp_client import McpClient  # noqa: E402

SERVER = r"""
import json
import sys

for i in range(20000):
    sys.stderr.write("noise-%d\n" % i)
sys.stderr.flush()

for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("id") is None:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "t", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "ping", "description": "", "inputSchema": {"type": "object"}}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
    sys.stdout.flush()
"""


class StderrDrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-mcp-")
        self.script = os.path.join(self.dir, "server.py")
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(SERVER)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_large_stderr_does_not_deadlock(self) -> None:
        with McpClient([sys.executable, self.script]) as client:
            tools = client.list_tools()
            tail = client._stderr_text()
        self.assertEqual([t["name"] for t in tools], ["ping"])
        self.assertIn("noise-19999", tail)


if __name__ == "__main__":
    unittest.main()
