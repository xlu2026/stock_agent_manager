"""写作侧的回归测试：合规闸门、front matter、降级路径。

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing import article as art  # noqa: E402
from writing.compliance import (  # noqa: E402
    AI_DISCLOSURE,
    RISK_DISCLAIMER,
    SYNTHETIC_NOTICE,
    check_name,
    scan_text,
)

BRIEF = {
    "title": "把判断写成因子：第一期",
    "summary": "记录一次把判断变成可证伪因子的过程。",
    "series": "杂灵根散修录",
    "tags": ["方法论", "回测"],
    "sections": [
        {"heading": "为什么", "body": ["因为过去的证据是事后挑的。"]},
        {"heading": "结果", "body": ["结果和预期不一样。"]},
    ],
}


class ComplianceTests(unittest.TestCase):
    def test_negated_phrases_allowed(self) -> None:
        for text in ("不做任何形式的标的推荐。", "本号不推荐任何个股。", "本文不构成投资建议。"):
            self.assertEqual(scan_text(text), [], text)

    def test_banned_claims_flagged(self) -> None:
        cases = ["我推荐这只票。", "建议买入并持有。", "该组合必涨。", "这是牛股。"]
        for text in cases:
            self.assertTrue(scan_text(text), text)

    def test_stock_code_flagged(self) -> None:
        self.assertTrue(scan_text("关注 600519 的走势", require_disclaimer=False))

    def test_missing_disclaimer_flagged(self) -> None:
        hits = scan_text("正文没有任何声明。", require_disclaimer=True)
        self.assertTrue(any(h.rule == "缺少风险提示" for h in hits))

    def test_ai_disclosure_required_for_dictated_draft(self) -> None:
        """口述整理稿必须逐字带披露句；未标 ai_assisted 的稿子不受影响。"""
        from writing.compliance import article_compliance

        body = "正文一段。\n\n" + SYNTHETIC_NOTICE + "\n\n风险提示：" + RISK_DISCLAIMER
        missing = article_compliance("测试标题", body, [], data_source="synthetic", ai_assisted=True)
        self.assertFalse(missing["ok"])
        self.assertTrue(any(v["rule"] == "缺少 AI 披露" for v in missing["violations"]))

        present = article_compliance(
            "测试标题", AI_DISCLOSURE + "\n\n" + body, [], data_source="synthetic", ai_assisted=True
        )
        self.assertTrue(present["ok"])

        # 不声明 ai_assisted 时不额外要求（旧稿子维持原判）
        legacy = article_compliance("测试标题", body, [], data_source="synthetic")
        self.assertFalse(any(v["rule"] == "缺少 AI 披露" for v in legacy["violations"]))

    def test_name_channel_words(self) -> None:
        self.assertTrue(check_name("杂灵根散修录")["ok"])
        self.assertFalse(check_name("AI 量化选股笔记")["ok"])

    def test_headers_do_not_eat_metaphor_budget(self) -> None:
        """标题与副标题里的"苟住/灵根/散修"是刊头，不该占掉 3 处隐喻配额。"""
        from writing.compliance import style_warnings

        three = "# 先苟住\n\n*杂灵根散修录 · 开发日志 009*\n\n苟住了。\n\n先筑基。\n\n散修的日子。\n"
        self.assertEqual(style_warnings("先苟住", three), [])

        four = three + "\n还是散修。\n"
        self.assertTrue(any("修仙隐喻" in w for w in style_warnings("先苟住", four)))


class ArticleRenderTests(unittest.TestCase):
    def test_front_matter_and_disclaimer(self) -> None:
        out = art.render(BRIEF)
        md = out["markdown"]
        self.assertTrue(md.startswith("---\n"))
        fm = md.split("---\n", 2)[1]
        for key in ("schema", "title", "slug", "date", "status", "tags", "compliance"):
            self.assertIn(f"{key}:", fm)
        self.assertIn(RISK_DISCLAIMER, md)
        self.assertIn(SYNTHETIC_NOTICE, md)
        self.assertIn('category: "杂项"', fm)  # 未指定栏目时落默认类
        self.assertEqual(out["compliance"]["violations"], [])

    def test_unknown_category_falls_back_to_misc(self) -> None:
        """栏目只认四类；旧值（如 认知记录）不许原样漏进 front matter。"""
        fs = art.CATEGORIES
        self.assertIn("杂项", fs)
        stale = art.render(dict(BRIEF, category="认知记录"))["markdown"]
        self.assertIn('category: "杂项"', stale)
        kept = art.render(dict(BRIEF, category="量化研究"))["markdown"]
        self.assertIn('category: "量化研究"', kept)

    def test_synthetic_notice_required(self) -> None:
        brief = dict(BRIEF)
        out = art.render(brief)
        without = out["markdown"].replace(SYNTHETIC_NOTICE, "")
        from writing.compliance import article_compliance

        result = article_compliance(brief["title"], without, brief["tags"], data_source="synthetic")
        self.assertFalse(result["ok"])
        self.assertTrue(any(v["rule"] == "缺少合成数据声明" for v in result["violations"]))

        # 换成真实数据来源时不该强制这句
        result_real = article_compliance(brief["title"], without, brief["tags"], data_source="real")
        self.assertFalse(any(v["rule"] == "缺少合成数据声明" for v in result_real["violations"]))

        # 纯工程文章（data_source=none）同样不该被强制
        result_none = article_compliance(brief["title"], without, brief["tags"], data_source="none")
        self.assertFalse(any(v["rule"] == "缺少合成数据声明" for v in result_none["violations"]))
        self.assertTrue(result_none["ok"])

    def test_deterministic_render(self) -> None:
        a = art.render(BRIEF)["markdown"]
        b = art.render(BRIEF)["markdown"]
        self.assertEqual(a, b)

    def test_status_can_be_overridden(self) -> None:
        """默认 draft；简报可显式标 archived，避免被当成待发稿。"""
        self.assertIn('status: "draft"', art.render(BRIEF)["markdown"])
        archived = art.render(dict(BRIEF, status="archived"))["markdown"]
        self.assertIn('status: "archived"', archived)

    def test_update_front_matter(self) -> None:
        """就地改 front matter，正文一个字节都不能动。"""
        import tempfile

        out = art.render(BRIEF)
        d = tempfile.mkdtemp(prefix="fm-")
        path = os.path.join(d, "a.md")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out["markdown"])

        body_before = out["markdown"].split("---\n", 2)[2]
        art.update_front_matter(path, {"status": "published", "published_at": "2026-11-09"})
        text = open(path, encoding="utf-8").read()
        self.assertIn('status: "published"', text)
        self.assertIn('published_at: "2026-11-09"', text)
        self.assertEqual(text.split("---\n", 2)[2], body_before)

    def test_brief_can_pin_date(self) -> None:
        """简报钉住日期后，重渲染不会改文件名里的日期，也不会每天多出一个副本。"""
        pinned = art.render(dict(BRIEF, date="2026-11-08"))
        self.assertIn('date: "2026-11-08"', pinned["markdown"])
        self.assertEqual(pinned["filename"], f"2026-11-08-{pinned['slug']}.md")

    def test_render_blocks_picking_advice(self) -> None:
        bad = dict(BRIEF)
        bad["sections"] = [{"heading": "结论", "body": ["建议大家买入并长期持有 600519。"]}]
        out = art.render(bad)
        self.assertFalse(out["compliance"]["ok"])
        self.assertTrue(out["compliance"]["violations"])


class DraftPipelineTests(unittest.TestCase):
    """草稿链路：合规在前，网络在后；不满足条件就不该发出任何请求。"""

    def test_noncompliant_rejected_before_network(self) -> None:
        from writing.drafts import DraftRejected, create_draft

        with self.assertRaises(DraftRejected):
            create_draft(title="必涨组合", markdown="这只票必涨，赶紧上车。")

    def test_unavailable_without_credentials(self) -> None:
        """探测说不可用时，create_draft 必须抛 DraftUnavailable，且不发起网络请求。"""
        from unittest.mock import patch

        from writing.drafts import DraftUnavailable, create_draft

        probe = {"available": False, "reason": "NO_CREDENTIALS", "detail": "未配置凭据"}
        with patch("writing.drafts.probe_draft_api", return_value=probe):
            with self.assertRaises(DraftUnavailable) as ctx:
                create_draft(
                    title="测试标题",
                    markdown="正文一段。\n\n" + SYNTHETIC_NOTICE + "\n\n风险提示：" + RISK_DISCLAIMER,
                )
            self.assertEqual(ctx.exception.probe["reason"], "NO_CREDENTIALS")


class DraftProbeClassifierTests(unittest.TestCase):
    """微信的失败有两种形态：HTTP 4xx 抛异常，和 HTTP 200 + body.errmsg。
    两种都要归类正确，否则 48001 会被误判成"有权限"。"""

    def test_body_errcode_48001_is_unavailable(self) -> None:
        from writing.wechat import classify_draft_probe

        r = classify_draft_probe({"errcode": 48001, "errmsg": "api unauthorized"}, None)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "API_UNAUTHORIZED")

    def test_body_errcode_40007_is_available(self) -> None:
        from writing.wechat import classify_draft_probe

        r = classify_draft_probe({"errcode": 40007, "errmsg": "invalid media_id"}, None)
        self.assertTrue(r["available"])
        self.assertEqual(r["reason"], "OK")

    def test_http_error_path(self) -> None:
        from writing.wechat import WeChatError, classify_draft_probe

        r = classify_draft_probe(None, WeChatError(48004, "banned", "draft/get"))
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "API_UNAUTHORIZED")

    def test_unknown_errcode_is_not_silently_available(self) -> None:
        from writing.wechat import classify_draft_probe

        r = classify_draft_probe({"errcode": 50001, "errmsg": "whatever"}, None)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "PROBE_UNKNOWN")


class LedgerTests(unittest.TestCase):
    """草稿账本：只追加、按 slug 取最新、合规结果可落盘。"""

    def test_append_and_latest(self) -> None:
        import tempfile

        from writing import ledger

        d = tempfile.mkdtemp(prefix="ledger-")
        path = os.path.join(d, "drafts.jsonl")
        ledger.append({"slug": "a", "media_id": "1"}, path)
        ledger.append({"slug": "a", "media_id": "2"}, path)
        ledger.append({"slug": "b", "media_id": "3"}, path)

        entries = ledger.read_all(path)
        self.assertEqual(len(entries), 3)
        latest = ledger.latest_by_slug(entries)
        self.assertEqual(latest["a"]["media_id"], "2")
        self.assertEqual(latest["b"]["media_id"], "3")
        self.assertIn("ts", entries[0])

        out = ledger.record_compliance("a", {"ok": True, "violations": []}, path)
        self.assertTrue(out.endswith("compliance-a.json"))
        self.assertTrue(os.path.exists(out))


class WeChatFallbackTests(unittest.TestCase):
    def test_html_keeps_real_line_break(self) -> None:
        """块内换行要变成真 <br/>，不能被转义成字面量。"""
        from writing.wechat import markdown_to_wechat_html

        html_out = markdown_to_wechat_html("正文\n\n---\n\n实验 ID：exp-1\n风险提示：x")
        self.assertIn("<br/>", html_out)
        self.assertNotIn("&lt;br/&gt;", html_out)

    def test_no_credentials_is_unavailable(self) -> None:
        from writing.wechat import probe_draft_api

        saved = {k: os.environ.pop(k, None) for k in ("WECHAT_APPID", "WECHAT_APPSECRET")}
        try:
            probe = probe_draft_api({"present": False, "appid": "", "appsecret": "", "source": None})
            self.assertFalse(probe["available"])
            self.assertEqual(probe["reason"], "NO_CREDENTIALS")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_no_publish_surface(self) -> None:
        """写作侧不得出现 freepublish 调用路径。"""
        root = os.path.join(ROOT, "writing")
        offenders = []
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dirpath, f)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if "freepublish" in text and "不存在" not in text and "没有" not in text:
                    offenders.append(path)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
