"""由 cordis/prompts/*.md 生成 Cordis 配置，保证提示词单一来源。

产出：
    cordis/phase1-presets.yml        两个 preset 声明（Web 会话按 preset 隔离时使用）
    cordis/profiles/quant.yml        Agent 1 profile patch（量化 MCP + 只保留文件工具）
    cordis/profiles/writing.yml      Agent 3 profile patch（草稿 MCP + 只保留文件工具）

    python tools/build_cordis.py
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_DIR = os.path.join(ROOT, "cordis", "prompts")
OUT_PRESETS = os.path.join(ROOT, "cordis", "phase1-presets.yml")
OUT_PROFILES = os.path.join(ROOT, "cordis", "profiles")

REPO = ROOT.replace("\\", "/")
GEN = "# 由 tools/build_cordis.py 生成；不要手改，改 cordis/prompts/*.md 后重新生成。\n"

# 两个 Agent 都不需要的能力：Phase 1 不做 subagent、不做常驻任务、不联网、不改工作区。
# 关掉的是"工具行"，服务行保留，否则会连带打断组合。
DISABLED_TOOLS = [
    "tool-bash",
    "tool-pwsh",
    "tool-subagent",
    "tool-subagent-control",
    "tool-subagent-fork",
    "tool-workflow",
    "tool-web",
    "tool-plugin-manager",
    "tool-todo",
    "tool-jobs",
    "tool-goal",
    "command-goal",
    "tool-skill",
    "tool-working-directory",
]

SRQ_ROW = f"""\
- id: mcp-srq
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: srq
    transport: stdio
    command: python
    args:
      - '-m'
      - 'quant.cli'
      - 'mcp'
      - 'serve'
    cwd: '{REPO}'
    failOnStartupError: true
    toolCallTimeoutMs: 120000
"""

DRAFT_ROW = f"""\
- id: mcp-wechat-draft
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: draft
    transport: stdio
    command: python
    args:
      - '-m'
      - 'writing.draft_mcp'
    cwd: '{REPO}'
    failOnStartupError: true
    toolCallTimeoutMs: 60000
"""

COMPACT = """\
- id: compaction
  name: cordis:group
  group: true
  isolate:
    compaction: true
    toolResultPruner: true
  config:
    - id: compaction-basic
      name: '@deepseek-ai/dsh-compaction-basic'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
      config:
        thresholdChars: 8192
        headChars: 4096
        tailChars: 1024
"""

# preset 是独立作用域：不能靠 disabled 关掉宿主行，必须显式列出要授予的工具。
# 两个 preset 都只给文件能力，量化/草稿能力由各自的 MCP 服务端提供。
PRESET_FS_ROWS = """\
- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
  config:
    applyPatch: false
- id: tool-fs-search
  name: '@deepseek-ai/dsh-tool-fs-search'
  config:
    sampleOverCapGlobResults: false
"""


def read_prompt(name: str) -> str:
    path = os.path.join(PROMPT_DIR, f"{name}.md")
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read().strip("\n")
    if not text:
        raise SystemExit(f"提示词为空：{path}")
    return text


def block_scalar(text: str, indent: int) -> str:
    pad = " " * indent
    return "\n".join((pad + line) if line.strip() else pad.rstrip() for line in text.splitlines())


def indent(text: str, by: int = 4) -> str:
    """按行缩进；保留原文末尾换行，否则相邻块会被粘成一行。"""
    pad = " " * by
    body = "\n".join((pad + line) if line.strip() else line for line in text.splitlines())
    return body + "\n" if text.endswith("\n") else body


def build_presets() -> str:
    a1, a3 = read_prompt("agent1"), read_prompt("agent3")
    body: list[str] = [
        "- id: agent-preset-registry\n",
        "  name: '@deepseek-ai/dsh-agent-preset-registry'\n",
        "  config:\n    default: quant-research\n",
        "\n- id: preset-quant-research\n  name: '@deepseek-ai/dsh-agent-preset'\n  config:\n",
        "    id: quant-research\n",
        "    name: 量化研究 Agent 1\n",
        "    description: 结构化研究指令 -> 确定性回测 -> 指标与实验 ID。无实盘、无荐股。\n",
        "    order: 1\n    plugins:\n",
        "      - id: persona\n        name: '@deepseek-ai/dsh-persona'\n        config:\n          prefix: |\n",
        block_scalar(a1, 12) + "\n",
        indent(PRESET_FS_ROWS, 6),
        "      - id: agent-instructions\n        name: '@deepseek-ai/dsh-agent-instructions'\n        config:\n          maxBytes: 65536\n",
        "      - id: time-context\n        name: '@deepseek-ai/dsh-time-context'\n",
        indent(SRQ_ROW, 6),
        indent(COMPACT, 6),
        "\n- id: preset-wechat-writing\n  name: '@deepseek-ai/dsh-agent-preset'\n  config:\n",
        "    id: wechat-writing\n",
        "    name: 公众号写作 Agent 3\n",
        "    description: 生成带 front matter 的 Markdown 草稿，最高到草稿箱，无发布能力。\n",
        "    order: 2\n    plugins:\n",
        "      - id: persona\n        name: '@deepseek-ai/dsh-persona'\n        config:\n          prefix: |\n",
        block_scalar(a3, 12) + "\n",
        indent(PRESET_FS_ROWS, 6),
        "      - id: agent-instructions\n        name: '@deepseek-ai/dsh-agent-instructions'\n        config:\n          maxBytes: 65536\n",
        "      - id: time-context\n        name: '@deepseek-ai/dsh-time-context'\n",
        indent(DRAFT_ROW, 6),
        indent(COMPACT, 6),
    ]
    inner = "".join(body)
    header = GEN + (
        "# Phase 1 的两套 Agent 能力面（preset 形态，仅 Web 表面支持按会话选择）。\n"
        "# 以 insert 形式提供：patch 层只能按 id 覆盖已有条目，新增条目必须放进 insert。\n"
        "# 一次性 headless 入口不消费 preset，那种场景用 cordis/profiles/*.yml 做 profile 级隔离。\n"
    )
    return header + "- insert:\n" + indent(inner, 4)


def build_profile(name: str, prompt_name: str, with_mcp: str) -> str:
    """with_mcp: 'srq' | 'draft'。"""
    rows = [
        GEN,
        "# profile 级 patch：一次性 headless 入口不看 preset，能力面在这里用 profile 隔离。\n",
        "- id: system-prompt\n  config:\n    personaPrefix: |\n",
        block_scalar(read_prompt(prompt_name), 6) + "\n",
        "\n# 关闭 Phase 1 用不到的工具面（shell / subagent / workflow / web / 插件管理）\n",
    ]
    for t in DISABLED_TOOLS:
        rows.append(f"- id: {t}\n  disabled: true\n")
    rows.append("\n- insert:\n")
    rows.append(indent(SRQ_ROW if with_mcp == "srq" else DRAFT_ROW, 4))
    return "".join(rows)


def main() -> int:
    os.makedirs(OUT_PROFILES, exist_ok=True)
    with open(OUT_PRESETS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_presets())
    for name, prompt_name, mcp in (("quant", "agent1", "srq"), ("writing", "agent3", "draft")):
        text = build_profile(name, prompt_name, mcp)
        path = os.path.join(OUT_PROFILES, f"{name}.yml")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"wrote {os.path.relpath(path, ROOT)} ({len(text)} bytes, mcp={mcp})")
    print(f"wrote {os.path.relpath(OUT_PRESETS, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
