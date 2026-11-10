"""Phase 1 研究指令契约：自然语言研究意图 -> 可执行的 spec。

任务书规定的输入是四个字段：

    {"question": "...", "universe": "沪深300", "period": "起止日期", "factor_logic": "..."}

其中只有 ``period`` 和 ``universe`` 是结构化的，``factor_logic`` 是一段自然语言。
把这段文字翻译成"引擎能执行的因子"这一步，**用代码里的显式关键词表完成，不交给模型**，
并且把映射过程原样记录在结果里。理由：如果让 LLM 决定"这句话对应哪个因子"，
它就事实上决定了回测跑什么，进而影响盈亏——这违反"LLM 不进入盈亏计算回路"。
用确定性的映射表，模型只能复述，不能左右。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# 外部 universe 名称 -> 数据快照里真实存在的标的池
UNIVERSE_ALIASES = {
    "synthetic_40": "synthetic_40",
    "合成样本40": "synthetic_40",
    "合成样本": "synthetic_40",
    "样本池": "synthetic_40",
}

# factor_logic 关键词 -> 因子。命中次数最多的胜出；平票或零命中一律拒绝，不猜。
FACTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "momentum_12_1": ("动量", "趋势", "强势", "惯性", "涨势", "追涨", "momentum"),
    "value_proxy": ("估值", "便宜", "低估", "账面", "价值", "b/p", "b p", "pb", "value"),
    "low_vol_60d": ("波动", "低波", "风险", "稳健", "回撤", "volatility", "vol"),
    "quality_proxy": ("质量", "roe", "盈利", "赚钱", "基本面", "现金流", "quality"),
}

CONTRACT_FIELDS = ("question", "universe", "period", "factor_logic")

# 可选覆盖项：允许，但都不改变"跑什么因子"这件事
OPTIONAL_OVERRIDES = ("rebalance", "top_k", "cost_bps", "seed", "data_version")

DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")


class InstructionError(ValueError):
    """研究指令不合规；message 面向人和 Agent，附带可执行的修正建议。"""

    def __init__(self, message: str, *, code: str = "INVALID_INSTRUCTION", extra: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


@dataclass
class Instruction:
    question: str
    universe: str
    period: str
    factor_logic: str
    start: str
    end: str
    factor: str
    mapping: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)

    def to_spec(self) -> dict:
        spec = {
            "factor": self.factor,
            "universe": self.universe,
            "start": self.start,
            "end": self.end,
        }
        spec.update(self.overrides)
        return spec


def _find_dates(text: str) -> list[str]:
    out: list[str] = []
    for y, m, d in DATE_RE.findall(text):
        out.append(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    return out


def parse_period(period: str) -> tuple[str, str]:
    """接受 2020-01-02~2024-12-31 / 2020-01-02 至 2024-12-31 / 2020/01/02..2024/12/31。"""
    if not isinstance(period, str):
        raise InstructionError(f"period 必须是字符串，收到 {period!r}", code="BAD_PERIOD")
    dates = _find_dates(period)
    if len(dates) < 2:
        raise InstructionError(
            f"period 里没找到两个日期：{period!r}；请写成 \"2020-01-02~2024-12-31\"",
            code="BAD_PERIOD",
        )
    start, end = dates[0], dates[1]
    if start >= end:
        raise InstructionError(f"period 起始 {start} 不早于结束 {end}", code="BAD_PERIOD")
    return start, end


def resolve_universe(universe: str) -> str:
    key = str(universe).strip()
    if key in UNIVERSE_ALIASES:
        return UNIVERSE_ALIASES[key]
    raise InstructionError(
        f"标的池 {key!r} 在当前数据快照里不存在；可用：{sorted(set(UNIVERSE_ALIASES.values()))}。"
        "接真实行情源后在这里加映射，不要用不存在的标的池假装回测。",
        code="UNIVERSE_UNAVAILABLE",
        extra={"available": sorted(set(UNIVERSE_ALIASES.values()))},
    )


def resolve_factor(factor_logic: str) -> tuple[str, dict]:
    """关键词打分；返回 (factor, 命中明细)。零命中或平票都拒绝。"""
    text = str(factor_logic).lower()
    scores = {f: sum(text.count(k.lower()) for k in kws) for f, kws in FACTOR_KEYWORDS.items()}
    best = max(scores.values()) if scores else 0
    winners = [f for f, s in scores.items() if s == best and s > 0]
    detail = {"scores": scores, "matched": winners, "source": "keyword_table"}
    if not winners:
        raise InstructionError(
            f"factor_logic 无法映射到已实现因子：{factor_logic!r}；"
            f"可用关键词示例见 {sorted(FACTOR_KEYWORDS)}",
            code="FACTOR_UNMAPPED",
            extra={"available_factors": sorted(FACTOR_KEYWORDS)},
        )
    if len(winners) > 1:
        raise InstructionError(
            f"factor_logic 同时命中多个因子 {winners}，无法判定该跑哪一个；请把逻辑写得更具体。",
            code="FACTOR_AMBIGUOUS",
            extra={"candidates": winners},
        )
    return winners[0], detail


def parse_instruction(raw: dict | str) -> Instruction:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InstructionError(f"研究指令不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise InstructionError("研究指令必须是 JSON 对象")

    missing = [k for k in CONTRACT_FIELDS if k not in raw]
    if missing:
        raise InstructionError(
            f"缺少必填字段 {missing}；Phase 1 契约是 {list(CONTRACT_FIELDS)}",
            code="MISSING_FIELDS",
            extra={"missing": missing},
        )

    question = raw["question"]
    if not isinstance(question, str) or not question.strip():
        raise InstructionError("question 必须是非空字符串", code="BAD_QUESTION")

    universe = resolve_universe(raw["universe"])
    start, end = parse_period(raw["period"])
    factor, mapping = resolve_factor(raw["factor_logic"])

    overrides = {k: raw[k] for k in OPTIONAL_OVERRIDES if k in raw}
    unknown = sorted(set(raw) - set(CONTRACT_FIELDS) - set(OPTIONAL_OVERRIDES))
    if unknown:
        raise InstructionError(
            f"出现未知字段 {unknown}；契约字段 {list(CONTRACT_FIELDS)}，可选覆盖 {list(OPTIONAL_OVERRIDES)}",
            code="UNKNOWN_FIELDS",
            extra={"unknown": unknown},
        )

    return Instruction(
        question=question.strip(),
        universe=universe,
        period=raw["period"],
        factor_logic=raw["factor_logic"],
        start=start,
        end=end,
        factor=factor,
        mapping={**mapping, "period_raw": raw["period"], "universe_raw": raw["universe"]},
        overrides=overrides,
    )


def looks_like_internal_spec(raw: dict) -> bool:
    """兼容已落库的内部 spec，方便复查时直接重跑。"""
    return isinstance(raw, dict) and "factor" in raw and "start" in raw and "end" in raw
