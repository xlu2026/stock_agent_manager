"""知乎导出的回归测试：格式、合规、手工字段合并、无发布面。

    python -m unittest tests.test_platforms -v
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing import article as art  # noqa: E402
from writing.compliance import NAME_BANNED, RISK_DISCLAIMER, SYNTHETIC_NOTICE  # noqa: E402
from writing.platforms import zhihu  # noqa: E402

BRIEF = {
    "title": "把判断写成因子：第一期",
    "subtitle": "杂灵根散修录 · 量化研究 001",
    "summary": "记录一次把判断变成可证伪因子的过程。",
    "category": "量化研究",
    "series": "杂灵根散修录",
    "tags": ["方法论", "回测"],
    "sections": [
        {
            "heading": "为什么",
            "body": ["因为过去的证据是事后挑的。", "这次用 `exp-a359c2d77697` 对账。"],
        },
        {"heading": "结果", "body": ["结果和预期不一样，**先记下来**。"]},
    ],
}


class ZhihuExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="zhihu-export-")
        self.addCleanup(self.tmp.cleanup)
        self.rendered = art.render(BRIEF)
        self.src = self._write(self.rendered["markdown"], self.rendered["filename"])

    def _write(self, text: str, name: str) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def _export(self, source: str | None = None, out: str | None = None) -> dict:
        return zhihu.export_article(
            source or self.src,
            out_dir=out or os.path.join(self.tmp.name, "out"),
        )

    def _read(self, path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_front_matter_parsed(self) -> None:
        front, body = zhihu.parse_front_matter(self.rendered["markdown"])
        self.assertEqual(front["title"], BRIEF["title"])
        self.assertEqual(front["category"], "量化研究")
        self.assertEqual(front["tags"], ["方法论", "回测"])
        self.assertEqual(front["data_source"], "synthetic")
        # 嵌套映射（compliance）整块跳过，不当成空列表
        self.assertIsNone(front.get("compliance"))
        self.assertTrue(body.lstrip().startswith("# "))

    def test_export_strips_front_matter_and_h1(self) -> None:
        result = self._export()
        html_text = self._read(result["html_path"])
        md_text = self._read(result["markdown_path"])

        self.assertFalse(html_text.startswith("---"))
        self.assertNotIn("schema:", html_text)
        self.assertNotIn("<h1>", html_text)
        self.assertNotIn("# 把判断", md_text)
        self.assertIn("<h2>为什么</h2>", html_text)
        self.assertIn("<em>杂灵根散修录 · 量化研究 001</em>", html_text)
        self.assertIn("<code>exp-a359c2d77697</code>", html_text)
        self.assertIn("<strong>先记下来</strong>", html_text)

    def test_disclaimers_survive_verbatim(self) -> None:
        result = self._export()
        html_text = self._read(result["html_path"])
        md_text = self._read(result["markdown_path"])
        for text in (SYNTHETIC_NOTICE, RISK_DISCLAIMER):
            self.assertIn(text, html_text)
            self.assertIn(text, md_text)

    def test_origin_footer_appended_once(self) -> None:
        result = self._export()
        html_text = self._read(result["html_path"])
        md_text = self._read(result["markdown_path"])
        self.assertIn(zhihu.ORIGIN_LINE, html_text)
        self.assertEqual(md_text.count(zhihu.ORIGIN_LINE), 1)
        self.assertTrue(md_text.rstrip().endswith(zhihu.ORIGIN_LINE))
        self.assertTrue(html_text.rstrip().endswith(f"<p>{zhihu.ORIGIN_LINE}</p>"))

    def test_origin_footer_not_duplicated(self) -> None:
        markdown = self.rendered["markdown"].rstrip("\n") + "\n\n" + zhihu.ORIGIN_LINE + "\n"
        path = self._write(markdown, "with-footer.md")
        result = zhihu.export_article(path, out_dir=os.path.join(self.tmp.name, "footer"))
        md_text = self._read(result["markdown_path"])
        html_text = self._read(result["html_path"])
        self.assertEqual(md_text.count(zhihu.ORIGIN_LINE), 1)
        self.assertEqual(html_text.count(zhihu.ORIGIN_LINE), 1)

    def test_export_rechecks_compliance(self) -> None:
        bad = dict(
            BRIEF,
            sections=[{"heading": "结论", "body": ["建议大家买入 600519 并持有。"]}],
        )
        rendered = art.render(bad)
        self.assertFalse(rendered["compliance"]["ok"])
        path = self._write(rendered["markdown"], "bad.md")

        with self.assertRaises(zhihu.ExportRejected) as ctx:
            zhihu.export_article(path, out_dir=os.path.join(self.tmp.name, "bad-out"))
        self.assertTrue(ctx.exception.compliance["violations"])

        # 拒绝时不该产生任何导出文件
        out = os.path.join(self.tmp.name, "bad-out")
        self.assertFalse(os.path.isdir(out) and os.listdir(out))

    def test_meta_merge_preserves_manual_fields(self) -> None:
        first = self._export()
        with open(first["meta_path"], encoding="utf-8") as fh:
            meta = json.load(fh)
        meta.update(
            {
                "canonical": "https://zhuanlan.zhihu.com/p/123456",
                "published_at": "2026-11-09T12:00:00+08:00",
                "status": "published",
                "published": True,
                "notes": "手工回填",
            }
        )
        with open(first["meta_path"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

        second = self._export()
        with open(second["meta_path"], encoding="utf-8") as fh:
            merged = json.load(fh)
        self.assertEqual(merged["canonical"], meta["canonical"])
        self.assertEqual(merged["published_at"], meta["published_at"])
        self.assertEqual(merged["status"], "published")
        self.assertTrue(merged["published"])
        self.assertEqual(merged["notes"], "手工回填")

    def test_topics_bounded_and_safe(self) -> None:
        topics = self._export()["meta"]["topics"]
        self.assertTrue(1 <= len(topics) <= zhihu.MAX_TOPICS)
        for topic in topics:
            for banned in NAME_BANNED:
                self.assertNotIn(banned, topic)

    def test_meta_has_no_publish_surface(self) -> None:
        meta = self._export()["meta"]
        self.assertFalse(meta["published"])
        self.assertEqual(meta["publish_api"], "absent")
        self.assertIsNone(meta["canonical"])

    def test_source_sha256_matches_file(self) -> None:
        meta = self._export()["meta"]
        with open(self.src, "rb") as fh:
            expected = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(meta["source_sha256"], expected)

    def test_default_export_dir_is_repo_output(self) -> None:
        """成文稿在写作工作区，导出物必须落仓库 output/articles/zhihu。"""
        self.assertEqual(
            os.path.normpath(zhihu.DEFAULT_OUT_DIR),
            os.path.normpath(os.path.join(ROOT, "output", "articles", "zhihu")),
        )

    def test_workspace_source_kept_absolute(self) -> None:
        """仓库外的源（写作工作区/临时目录）不写 `..\\..` 相对路径。"""
        self.assertFalse(self._export()["meta"]["source"].startswith(".."))

    def test_dedicated_cover_wins_over_category(self) -> None:
        self.assertEqual(
            zhihu.cover_for({"category": "杂项"}, "opening"),
            os.path.join("output", "articles", "cover-opening-2.35x1.png"),
        )
        self.assertEqual(
            zhihu.cover_for({"category": "量化研究"}, "no-such-slug"),
            os.path.join("output", "articles", "covers", "cover-quant-2.35x1.png"),
        )

    def test_missing_title_is_rejected(self) -> None:
        path = self._write("---\nslug: \"x\"\n---\n\n正文。\n", "no-title.md")
        with self.assertRaises(zhihu.ExportError):
            zhihu.export_article(path, out_dir=os.path.join(self.tmp.name, "no-title-out"))

    def test_html_escapes_and_keeps_linebreak(self) -> None:
        html_text = zhihu.markdown_to_html(
            "第一行\n第二行\n\n<script>alert(1)</script>\n\n## 小标题"
        )
        self.assertIn("第一行<br/>第二行", html_text)
        self.assertIn("&lt;script&gt;", html_text)
        self.assertNotIn("<script>", html_text)
        self.assertIn("<h2>小标题</h2>", html_text)

    def test_deterministic_export(self) -> None:
        a = self._export(out=os.path.join(self.tmp.name, "a"))
        b = self._export(out=os.path.join(self.tmp.name, "b"))
        self.assertEqual(self._read(a["html_path"]), self._read(b["html_path"]))
        self.assertEqual(self._read(a["markdown_path"]), self._read(b["markdown_path"]))

    def test_cli_exports_one_article(self) -> None:
        from writing.export import main

        out = os.path.join(self.tmp.name, "cli")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([self.src, "--out-dir", out])
        self.assertEqual(rc, 0)
        self.assertIn("导出：", buf.getvalue())
        names = os.listdir(out)
        self.assertTrue(any(n.endswith(".zhihu.html") for n in names))
        self.assertTrue(any(n.endswith(".zhihu.json") for n in names))

    def test_no_publish_surface_in_source(self) -> None:
        """导出层不得出现发布/浏览器自动化/网络客户端的调用路径。"""
        targets = [
            os.path.join(ROOT, "writing", "export.py"),
            os.path.join(ROOT, "writing", "platforms", "__init__.py"),
            os.path.join(ROOT, "writing", "platforms", "zhihu.py"),
        ]
        forbidden = ("freepublish", "playwright", "selenium", "requests", "webbrowser", "urllib")
        for path in targets:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} 出现在 {path}")


if __name__ == "__main__":
    unittest.main()
