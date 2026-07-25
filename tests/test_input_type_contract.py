from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.support.cli import temporary_test_directory
from video_summary import config, llm
from video_summary.documents import extract_document_text
from video_summary.outputs import build_refined_summary, write_outputs


class InputTypeContractTests(unittest.TestCase):
    def _refined_text(self, source: str) -> str:
        lines = build_refined_summary(
            "测试主题",
            source,
            "作者",
            90,
            None,
            "这是用于测试输入类型标题和来源标签的正文。",
            ["核心结论"],
            ["核心概念"],
            [{"title": "第一章", "summary": "章节摘要", "time": 0}],
        )
        return "\n".join(lines)

    def test_document_refined_draft_uses_document_titles_and_source_label(self) -> None:
        draft = self._refined_text("课程.docx")

        self.assertIn("# 文档精校总结：测试主题", draft)
        self.assertIn("## 文档章节总结 ｜ 测试主题", draft)
        self.assertIn("- 文稿来源：文档", draft)
        self.assertNotIn("视频精校总结", draft)
        self.assertNotIn("视频章节总结", draft)
        self.assertNotIn("本地转写", draft)

    def test_video_refined_draft_keeps_video_titles_and_local_transcription_metadata(self) -> None:
        draft = self._refined_text("课程.mp4")

        self.assertIn("# 视频精校总结：测试主题", draft)
        self.assertIn("## 视频章节总结 ｜ 测试主题", draft)
        self.assertIn("- 文稿来源：本地转写", draft)
        self.assertNotIn("local transcription", draft)

    def test_compact_document_draft_does_not_describe_document_as_transcription(self) -> None:
        with temporary_test_directory() as temp_dir:
            out_dir = Path(temp_dir) / "output"
            write_outputs(
                {"title": "测试文档", "uploader": "本地文件", "duration": None},
                "课程.pdf",
                out_dir,
                "这是用于测试文档来源标签的正文，不能被描述为视频转写。",
                None,
                "compact",
            )
            draft = (out_dir / "_internal" / "summary_draft.md").read_text(encoding="utf-8")

        self.assertIn("- 字幕语言：文档", draft)
        self.assertNotIn("无字幕，使用转写", draft)

    def test_llm_document_detection_accepts_only_supported_extensions(self) -> None:
        for source in ("report.pdf", "report.doc", "report.docx", "report.DOCX?download=1"):
            with self.subTest(source=source):
                self.assertTrue(llm.is_document_source(source))

        for source in ("report.odt", "report.rtf", "report.odt?download=1", "report.mp4"):
            with self.subTest(source=source):
                self.assertFalse(llm.is_document_source(source))
                self.assertNotEqual(llm.transcript_source_label(source, None), "文档")

    def test_document_llm_prompt_uses_document_language(self) -> None:
        prompt = llm.build_llm_prompt(
            "测试文档",
            "报告.pdf",
            "作者",
            "未知",
            "文档正文",
            None,
            "",
            "video",
        )

        self.assertIn("# 文档精校总结：{title}", prompt)
        self.assertIn("## 文档章节总结 ｜ {one_sentence_title}", prompt)
        self.assertIn("Document metadata:", prompt)
        self.assertNotIn("# 视频精校总结：{title}", prompt)
        self.assertNotIn("## 视频章节总结 ｜ {one_sentence_title}", prompt)
        self.assertNotIn("Video metadata:", prompt)

    def test_document_final_summary_normalizes_video_template_headings(self) -> None:
        generated = (
            "# 视频精校总结：测试文档\n\n"
            "- 文稿来源：字幕\n\n"
            "## 视频章节总结 ｜ 测试文档\n\n"
            "正文。"
        )

        cleaned = llm._prepare_final_summary(generated, "报告.pdf")

        self.assertIn("# 文档精校总结：测试文档", cleaned)
        self.assertIn("## 文档章节总结 ｜ 测试文档", cleaned)
        self.assertIn("- 文稿来源：文档", cleaned)
        self.assertNotIn("视频精校总结", cleaned)
        self.assertNotIn("视频章节总结", cleaned)

    def test_image_only_pdf_is_rejected_without_ocr_or_media_fallback(self) -> None:
        fake_pypdf = types.ModuleType("pypdf")

        class Page:
            def extract_text(self):
                return ""

        class PdfReader:
            def __init__(self, path):
                self.pages = [Page()]

        fake_pypdf.PdfReader = PdfReader
        original = sys.modules.get("pypdf")
        sys.modules["pypdf"] = fake_pypdf
        try:
            with temporary_test_directory() as temp_dir:
                path = Path(temp_dir) / "image-only.pdf"
                path.write_bytes(b"%PDF-image-only")
                with self.assertRaises(config.UserFacingError) as raised:
                    extract_document_text(path)
        finally:
            if original is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = original

        message = str(getattr(raised.exception, "message", raised.exception))
        self.assertIn("PDF 未提取到文本层，图像型 PDF 暂不支持", message)
        self.assertNotIn("OCR", message)
        self.assertNotIn("音频", message)


if __name__ == "__main__":
    unittest.main()
