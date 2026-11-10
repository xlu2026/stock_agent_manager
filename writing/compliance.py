"""合规扫描：一票否决的文本闸门。

规则来自项目简报第 3 节。这里做的是**机械可复核**的检查，不依赖模型自觉：
- 不得出现荐股/买卖指令/收益承诺措辞；
- 不得出现个股代码；
- 风险提示声明必须逐字存在。

刻意支持否定语境（"不推荐个股""无需买入"），否则合规声明本身会被误杀。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DISCLAIMER_VERSION = "disclaimer-2026-11-v2"

# 与 cordis/prompts/agent3.md 附录 A2 逐字一致；改这里必须同步改提示词
RISK_DISCLAIMER = "本文仅为个人研究记录，不构成任何投资建议。市场有风险，决策需独立。"

# data_source=synthetic 时正文必须逐字出现
SYNTHETIC_NOTICE = (
    "前期回测基于合成数据，仅用于验证研究链路，不代表真实市场表现，"
    "不构成任何策略有效性证据。"
)

# 口述整理稿的固定披露句：稿件由人口述、AI 只做整理时，正文必须逐字出现。
# front matter 标 ai_assisted: true 的稿子由 article_compliance 机械校验，不靠自觉。
AI_DISCLOSURE = "本文由我口述、AI 协助整理，观点与判断由我负责。"

# 文风自检的关键词（只用于给 warning，不做一票否决）
XIUXIAN_WORDS = ("苟住", "筑基", "散修", "灵根", "修仙", "道心", "功法", "金丹")
TITLE_MAX_CHARS = 20

# 出现即违规的"动作性断言"（正则）。命中后回看否定词，命中否定则放行。
BANNED_CLAIMS: list[tuple[str, str]] = [
    (r"推荐(?:买入|卖出|关注|持有)?", "荐股/推荐措辞"),
    (r"建议(?:买入|卖出|加仓|减仓|持有|关注)", "买卖建议"),
    (r"(?:买入|卖出|加仓|减仓|清仓|满仓|抄底|逃顶)(?:信号|时机|点)", "买卖信号"),
    (r"必涨|必跌|稳赚|包赚|躺赚|保本|保收益", "收益承诺"),
    (r"(?:年化|月化|稳定)(?:收益|回报)\s*\d", "收益承诺"),
    (r"牛股|妖股|黑马股|涨停板|涨停", "诱导性个股措辞"),
    (r"翻倍|暴富|财务自由", "收益诱导"),
]

# 名称/功能介绍层面必须回避的词（用于公众号命名与简介自检）
NAME_BANNED = ["股票", "证券", "投资", "理财", "基金", "荐股", "选股", "牛股", "涨停", "量化选股"]

NEGATIONS = ("不", "勿", "非", "无", "禁", "避免", "拒绝", "杜绝", "免", "别", "零")
# "不少/不但/不仅" 含"不"但不表否定，判定前先剔除
FALSE_NEGATIONS = ("不少", "不但", "不仅", "不停", "不同", "不论")

SENTENCE_BREAKS = "。！？；\n"

# 刊头：H1 与副标题（`*系列名 · 类型 编号*`）。系列名里自带"灵根/散修"，标题里也可能有"苟住"，
# 它们是刊头不是修辞，统计隐喻时先剥掉，否则每篇开头先白扣配额。
H1_RE = re.compile(r"\A\s*#[^\n]*\n")
SUBTITLE_RE = re.compile(r"\A\s*\*[^*\n]+\*\n")

# 6 位数字代码（A 股/基金代码形态），允许被空格分隔的序号排除
CODE_RE = re.compile(r"(?<![0-9A-Za-z])(?:60|68|00|30|43|83|87)\d{4}(?![0-9A-Za-z])")

FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)


@dataclass
class Violation:
    rule: str
    matched: str
    context: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "matched": self.matched, "context": self.context}


def _negated(text: str, start: int) -> bool:
    """同一句话内、命中词之前出现否定词 => 视为否定语境。

    只在句内回看，不做全文负向匹配：这样"不做任何形式的标的推荐"能放行，
    而"很多人都推荐这只票"仍会被拦下。已知局限：反讽或分句过长的否定
    可能漏判，因此草稿一律 status=draft，由人复核后才可能进入下一步。
    """
    boundary = max(text.rfind(ch, 0, start) for ch in SENTENCE_BREAKS)
    prefix = text[boundary + 1 : start]
    for bad in FALSE_NEGATIONS:
        prefix = prefix.replace(bad, "")
    return any(neg in prefix for neg in NEGATIONS)


def _strip_front_matter(text: str) -> str:
    return FRONT_MATTER_RE.sub("", text, count=1)


def scan_text(text: str, *, require_disclaimer: bool = False) -> list[Violation]:
    body = _strip_front_matter(text)
    found: list[Violation] = []

    for pattern, rule in BANNED_CLAIMS:
        for m in re.finditer(pattern, body):
            if _negated(body, m.start()):
                continue
            found.append(
                Violation(
                    rule=rule,
                    matched=m.group(0),
                    context=body[max(0, m.start() - 12) : m.end() + 12].replace("\n", " "),
                )
            )

    for m in CODE_RE.finditer(body):
        found.append(
            Violation(
                rule="个股代码",
                matched=m.group(0),
                context=body[max(0, m.start() - 10) : m.end() + 10].replace("\n", " "),
            )
        )

    if require_disclaimer and RISK_DISCLAIMER not in body:
        found.append(Violation(rule="缺少风险提示", matched="", context="正文未逐字包含风险提示声明"))

    return found


def check_name(name: str) -> dict:
    """公众号名称/功能介绍自检。"""
    hits = [w for w in NAME_BANNED if w in name]
    return {"name": name, "ok": not hits, "hits": hits, "banned": NAME_BANNED}


def style_warnings(title: str, body: str) -> list[str]:
    """文风自检：只给建议，不拦发布。对应提示词第六节的自检清单。"""
    out: list[str] = []
    if len(title) > TITLE_MAX_CHARS:
        out.append(f"标题 {len(title)} 字，超过 {TITLE_MAX_CHARS} 字")
    wo = body.count("我们")
    me = body.count("我") - wo
    if wo > me:
        out.append(f'"我们" 出现 {wo} 次，多于 "我" 的 {me} 次')

    # 规则说的是"每篇不超过 3 处"，所以按"出现隐喻的段落数"算，
    # 不按词频——否则标题和账号名里的"苟住""筑基"会被重复扣分。
    body_no_header = SUBTITLE_RE.sub("", H1_RE.sub("", body, count=1), count=1)
    paras = [p for p in re.split(r"\n\s*\n", body_no_header) if p.strip()]
    metaphor_paras = [p for p in paras if any(w in p for w in XIUXIAN_WORDS)]
    if len(metaphor_paras) > 3:
        out.append(f"修仙隐喻出现在 {len(metaphor_paras)} 个段落里，建议不超过 3 处")

    if "众所周知" in body or "大家应该" in body:
        out.append("出现“众所周知/大家应该”这类空话")
    return out


def article_compliance(
    title: str,
    markdown: str,
    tags: list[str] | None = None,
    *,
    data_source: str = "synthetic",
    ai_assisted: bool = False,
) -> dict:
    body = _strip_front_matter(markdown)
    violations = scan_text(markdown, require_disclaimer=True)

    if data_source not in ("real", "none") and SYNTHETIC_NOTICE not in body:
        violations.append(
            Violation(rule="缺少合成数据声明", matched="", context="data_source=synthetic 但正文未逐字声明")
        )

    if ai_assisted and AI_DISCLOSURE not in body:
        violations.append(
            Violation(
                rule="缺少 AI 披露",
                matched="",
                context="ai_assisted=true 但正文未逐字包含口述整理披露句",
            )
        )

    combined = title + "\n" + " ".join(tags or [])
    name_hits = [w for w in NAME_BANNED if w in combined]
    warnings = style_warnings(title, body)
    ok = not violations and not name_hits
    return {
        "checked": True,
        "ok": ok,
        "disclaimer_version": DISCLAIMER_VERSION,
        "violations": [v.as_dict() for v in violations],
        "name_channel_hits": name_hits,
        "warnings": warnings,
        "data_source": data_source,
        "ai_assisted": ai_assisted,
        "engine": "regex+negation-window",
    }
