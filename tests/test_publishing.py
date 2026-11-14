"""发布台回归测试：状态聚合、卡片、回填、无发布面。

    python -m unittest tests.test_publishing -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing import publishing  # noqa: E402
from writing.compliance import RISK_DISCLAIMER  # noqa: E402
from writing.platforms import zhihu  # noqa: E402

ARTICLE = """---
schema: "nerve.article/v1"
title: "测试文章"
slug: "test-001"
date: "2026-11-14"
status: "draft"
author: "杂灵根散修"
series: "杂灵根散修录"
category: "量化研究"
phase: "phase-1"
tags:
  - "方法论"
summary: "测试摘要"
experiment_ref: null
data_source: "none"
---

# 测试文章

正文一段。

风险提示：{risk}
""".format(risk=RISK_DISCLAIMER)


class PublishingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="publish-")
        self.addCleanup(self.tmp.cleanup)
        self.articles = Path(self.tmp.name) / "articles"
        self.articles.mkdir()
        self.zhihu = Path(self.tmp.name) / "zhihu"
        self.cards = Path(self.tmp.name) / "cards"
        self.ledger = Path(self.tmp.name) / "drafts.jsonl"
        self.changelog = Path(self.tmp.name) / "CHANGELOG.md"
        self.changelog.write_text("# changelog\n", encoding="utf-8")
        self.source = self.articles / "2026-11-14-test-001.md"
        self.source.write_text(ARTICLE, encoding="utf-8", newline="\n")

    def scan(self):
        return publishing.scan(
            article_dir=self.articles,
            zhihu_dir=self.zhihu,
            ledger_path=self.ledger,
        )

    def test_status_before_prepare(self) -> None:
        data = self.scan()
        self.assertEqual(len(data["articles"]), 1)
        row = data["articles"][0]
        self.assertEqual(row["wechat"]["label"], "草稿（未推）")
        self.assertEqual(row["zhihu"]["state"], "未导出")
        self.assertIn("推微信草稿", row["actions"])
        self.assertIn("导出知乎", row["actions"])

    def test_prepare_exports_and_card(self) -> None:
        result = publishing.prepare(
            "test-001",
            platform="zhihu",
            article_dir=self.articles,
            zhihu_dir=self.zhihu,
            card_dir=self.cards,
        )
        self.assertTrue(Path(result["card"]).exists())
        html_text = Path(result["export"]["html_path"]).read_text(encoding="utf-8")
        self.assertIn(zhihu.ORIGIN_LINE, html_text)
        self.assertIn("body_sha256", result["export"]["meta"])
        card = Path(result["card"]).read_text(encoding="utf-8")
        self.assertIn("测试文章", card)
        self.assertIn("publish.py done", card)

        row = self.scan()["articles"][0]
        self.assertEqual(row["zhihu"]["state"], "已导出")
        self.assertIn("发布知乎", row["actions"])

    def test_body_change_marks_export_stale(self) -> None:
        publishing.prepare(
            "test-001",
            platform="zhihu",
            article_dir=self.articles,
            zhihu_dir=self.zhihu,
            card_dir=self.cards,
        )
        self.source.write_text(ARTICLE + "\n补一段。\n", encoding="utf-8", newline="\n")
        row = self.scan()["articles"][0]
        self.assertEqual(row["zhihu"]["state"], "导出过期")
        self.assertIn("重导知乎", row["actions"])

    def test_done_zhihu_backfills_and_is_idempotent(self) -> None:
        publishing.prepare(
            "test-001",
            platform="zhihu",
            article_dir=self.articles,
            zhihu_dir=self.zhihu,
            card_dir=self.cards,
        )
        url = "https://zhuanlan.zhihu.com/p/123456"
        first = publishing.done_zhihu("test-001", url, date="2026-11-14", zhihu_dir=self.zhihu)
        self.assertEqual(first["canonical"], url)
        sidecar = json.loads(Path(first["sidecar"]).read_text(encoding="utf-8"))
        self.assertEqual(sidecar["status"], "published")
        self.assertTrue(sidecar["published"])
        second = publishing.done_zhihu("test-001", url, date="2026-11-14", zhihu_dir=self.zhihu)
        self.assertEqual(second["canonical"], url)
        row = self.scan()["articles"][0]
        self.assertEqual(row["zhihu"]["state"], "已发布")

    def test_done_zhihu_rejects_bad_url(self) -> None:
        publishing.prepare(
            "test-001",
            platform="zhihu",
            article_dir=self.articles,
            zhihu_dir=self.zhihu,
            card_dir=self.cards,
        )
        with self.assertRaises(publishing.PublishError):
            publishing.done_zhihu("test-001", "https://example.com/p/1", zhihu_dir=self.zhihu)

    def test_done_wechat_updates_front_matter(self) -> None:
        result = publishing.done_wechat(
            "test-001",
            date="2026-11-14",
            article_dir=self.articles,
            changelog=self.changelog,
        )
        self.assertFalse(result.get("already"))
        text = self.source.read_text(encoding="utf-8")
        self.assertIn('status: "published"', text)
        self.assertIn('published_at: "2026-11-14"', text)
        self.assertIn("2026-11-14 发布：测试文章", self.changelog.read_text(encoding="utf-8"))
        again = publishing.done_wechat(
            "test-001",
            date="2026-11-14",
            article_dir=self.articles,
            changelog=self.changelog,
        )
        self.assertTrue(again.get("already"))

    def test_compliance_blocks_prepare(self) -> None:
        self.source.write_text(
            ARTICLE.replace("正文一段。", "建议买入并持有 600519。"),
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaises(publishing.PublishError):
            publishing.prepare(
                "test-001",
                platform="zhihu",
                article_dir=self.articles,
                zhihu_dir=self.zhihu,
                card_dir=self.cards,
            )
        self.assertFalse(self.cards.exists() and any(self.cards.iterdir()))

    def test_archived_skipped(self) -> None:
        archived = self.articles / "[存档] 2026-11-07-old.md"
        archived.write_text(ARTICLE.replace('slug: "test-001"', 'slug: "old"'), encoding="utf-8")
        data = self.scan()
        self.assertEqual(len(data["articles"]), 1)
        self.assertEqual(data["summary"]["skipped"], 1)

    def test_no_publish_surface(self) -> None:
        targets = [
            Path(ROOT) / "writing" / "publishing.py",
            Path(ROOT) / "scripts" / "publish.py",
        ]
        forbidden = ("freepublish", "playwright", "selenium", "webbrowser")
        for path in targets:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} 出现在 {path}")


if __name__ == "__main__":
    unittest.main()
