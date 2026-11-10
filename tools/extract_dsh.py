"""Extract selected dsh plugin packages from app.asar into .probe/dsh_src for inspection."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asar_tool import Asar  # noqa: E402

ASAR = r"C:\Users\ADMIN\AppData\Local\Programs\DeepSeek Harness\resources\app.asar"
DEST = r"C:\AI_workspace\stock_agent_manager\.probe\dsh_src"
PKGS = [
    "dsh-mcp-client",
    "dsh-agent-preset",
    "dsh-agent-preset-registry",
    "dsh-agent",
    "dsh-sdk-app",
    "dsh-headless",
    "dsh-base",
    "dsh-official-bundles",
    "dsh-scope",
    "dsh-agent-instructions",
]


def main() -> int:
    a = Asar(ASAR)
    prefix = "dsh/node_modules/@deepseek-ai/"
    all_paths = a.ls(prefix)
    for pkg in PKGS:
        stem = f"{prefix}{pkg}/"
        files = [p for p in all_paths if p.startswith(stem) and p.endswith((".js", ".json", ".md", ".yml", ".yaml", ".d.ts"))]
        for p in files:
            rel = p[len(stem):]
            dest = os.path.join(DEST, pkg, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(a.read(p))
        print(f"{pkg}: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
