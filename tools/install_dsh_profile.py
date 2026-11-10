"""把仓库里的 Phase 1 配置安装成两个 DSH profile（quant / writing）。

    python tools/build_cordis.py        # 先由提示词生成 cordis/profiles/*.yml
    python tools/install_dsh_profile.py [--profiles-dir DIR] [--dry-run]

生成的 profile 是"手动触发、不常驻"的一次性会话入口：

    dsh --profile quant   "跑一次动量因子回测"
    dsh --profile writing "把这份简报写成公众号草稿"

两个 profile 的差别就是能力面：quant 的 patch 里插入了 srq MCP 服务端，
writing 的 patch 里没有任何 MCP 行，因此写作会话的工具表里不存在 mcp__srq__*。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILES = os.path.join(os.path.expanduser("~"), ".dsh", "profiles")
PROFILE_SRC = os.path.join(ROOT, "cordis", "profiles")
MARKER = "# 由 tools/install_dsh_profile.py 从仓库 cordis/profiles/ 生成"

PROFILES = {
    "quant": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "note": "Agent 1 量化研究：注册 srq MCP 服务端，工具表含 mcp__srq__*",
    },
    "writing": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "note": "Agent 3 公众号写作：不注册任何 MCP 服务端，工具表无量化工具",
    },
}

HEADER = f"""{MARKER}
# 不要手改；改 cordis/prompts/*.md 后跑 tools/build_cordis.py + tools/install_dsh_profile.py。
#
# headless profile 默认关闭交互式凭据存储，这里打开，让一次性 CLI 会话
# 复用 GUI 已保存的登录态（见 dsh-headless README 的 credentials 一节）。

- id: agent-default-model
  config:
    provider: deepseek-account
    model: deepseek-flash
    reasoningEffort: high

- id: credentials
  disabled: false

- id: authorization
  disabled: false

- id: deepseek-account
  disabled: false

"""

PNPM = "packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n"
CORDIS = (
    "# dsh profile root — an empty entry list. The tree is composed as patches:\n"
    "# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml.\n"
    "[]\n"
)


def install(name: str, spec: dict, profiles_dir: str, dry_run: bool) -> str:
    src = os.path.join(PROFILE_SRC, f"{name}.yml")
    with open(src, encoding="utf-8-sig") as fh:
        profile_patch = fh.read().strip("\n")

    target = os.path.join(profiles_dir, name)
    files = {
        "package.json": json.dumps(
            {
                "name": f"dsh-profile-{name}",
                "private": True,
                "dependencies": {},
                "dsh": {"profile": {"bundles": spec["bundles"]}},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "pnpm-workspace.yaml": PNPM,
        "cordis.yml": CORDIS,
        "cordis.patch.yml": HEADER + profile_patch + "\n",
    }
    if dry_run:
        return f"[dry-run] {target} ({len(files)} files)"

    os.makedirs(target, exist_ok=True)
    for fname, content in files.items():
        path = os.path.join(target, fname)
        if fname == "cordis.patch.yml" and os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles-dir", default=DEFAULT_PROFILES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    for name, spec in PROFILES.items():
        where = install(name, spec, args.profiles_dir, args.dry_run)
        print(f"{name:8s} -> {where}")
        print(f"           {spec['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
