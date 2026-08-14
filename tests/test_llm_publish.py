from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_summary import config, llm, outputs


class FinalDeliveryTests(unittest.TestCase):
    def test_final_delivery_ready_accepts_nonempty_summary_without_mindmap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "summary.md").write_text("# 只有正文的最终摘要\n", encoding="utf-8")

            self.assertTrue(outputs.final_delivery_ready(out_dir))
            self.assertFalse((out_dir / "mindmap.mmd").exists())

    def test_write_outputs_does_not_prepare_output_directory_implicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.object(outputs, "prepare_output_directory") as prepare:
                outputs.write_outputs(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证输出写入不负责生命周期准备。",
                    "zh",
                    "compact",
                )

            prepare.assert_not_called()
            self.assertTrue((out_dir / "_internal" / "summary_draft.md").is_file())

    def test_llm_refinement_publishes_summary_without_mindmap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            refined = "# 只有正文的最终摘要\n\n这里没有 Mermaid 脑图。"

            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证只有正文时仍可发布摘要。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")
            self.assertFalse((out_dir / "mindmap.mmd").exists())

    def test_new_draft_run_preserves_existing_delivery_and_stages_new_draft_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "output"
            run_dir = root / "run"
            out_dir.mkdir()
            (out_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (out_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            (out_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            (out_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            outputs.prepare_output_directory(out_dir)
            outputs.write_outputs({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", run_dir, "本次运行的逐字稿内容足够长，用于生成新的摘要草稿。", "zh", "compact")
            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), "旧摘要\n")
            self.assertEqual((out_dir / "mindmap.mmd").read_text(encoding="utf-8"), "旧脑图\n")
            self.assertEqual((out_dir / "notes.txt").read_text(encoding="utf-8"), "用户文件\n")
            self.assertFalse((out_dir / "summary_refined.md").exists())
            self.assertTrue((run_dir / "_internal" / "summary_draft.md").is_file())
            self.assertFalse((out_dir / "_internal").exists())

    def test_prepare_removes_legacy_root_subtitles_without_moving_them_to_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "subtitle.zh-Hans.vtt").write_text("WEBVTT\n", encoding="utf-8")
            (out_dir / "subtitle.en.srt").write_text("旧英文字幕\n", encoding="utf-8")
            (out_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            outputs.prepare_output_directory(out_dir)
            self.assertFalse((out_dir / "subtitle.zh-Hans.vtt").exists())
            self.assertFalse((out_dir / "subtitle.en.srt").exists())
            self.assertFalse((out_dir / "_internal").exists())
            self.assertTrue((out_dir / "notes.txt").exists())

    def test_prepare_removes_legacy_refined_files_without_creating_an_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            (out_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
            outputs.prepare_output_directory(out_dir)
            self.assertFalse((out_dir / "summary_refined.md").exists())
            self.assertFalse((out_dir / "mindmap_refined.mmd").exists())
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_llm_failure_hides_existing_delivery_without_archiving_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "output"
            run_dir = root / "run"
            out_dir.mkdir()
            (out_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (out_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm, "call_llm", side_effect=RuntimeError("LLM 请求失败")):
                with self.assertRaises(Exception):
                    llm.refine_with_llm({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", out_dir, "本次运行的逐字稿内容足够长。", "zh", "gpt-test", "responses", 12000, "video", workspace_dir=run_dir)
            self.assertFalse((out_dir / "summary.md").exists())
            self.assertFalse((out_dir / "mindmap.mmd").exists())
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_successful_refinement_publishes_only_final_files_after_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "output"
            run_dir = root / "run"
            out_dir.mkdir()
            (out_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            (out_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
            outputs.prepare_output_directory(out_dir)
            outputs.write_outputs({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", run_dir, "本次运行的逐字稿内容足够长。", "zh", "compact")
            refined = "# 精校摘要\n\n这是经过整理的实质正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm, "call_llm", return_value=refined):
                llm.refine_with_llm({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", out_dir, "本次运行的逐字稿内容足够长。", "zh", "gpt-test", "responses", 12000, "video", workspace_dir=run_dir)
            self.assertEqual({path.name for path in out_dir.iterdir()}, {"summary.md", "mindmap.mmd"})
            self.assertFalse((out_dir / "_internal").exists())

    def test_refine_with_llm_publishes_from_run_workspace_without_archive_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "output"
            run_dir = root / "run"
            out_dir.mkdir()
            outputs.write_outputs({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", run_dir, "本次运行的逐字稿内容足够长。", "zh", "compact")
            refined = "# 精校摘要\n\n这是经过整理的实质正文。\n"
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm, "call_llm", return_value=refined):
                llm.refine_with_llm({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", out_dir, "本次运行的逐字稿内容足够长。", "zh", "gpt-test", "responses", 12000, "video", workspace_dir=run_dir)
            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined)
            self.assertFalse((out_dir / "_internal").exists())
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_llm_success_clears_previous_final_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            internal = out_dir / "_internal"
            archive = internal / "previous_final"
            archive.mkdir(parents=True)
            (archive / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (archive / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            (archive / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            (archive / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
            (internal / "summary_draft.md").write_text("新草稿", encoding="utf-8")
            refined = "# 精校摘要\n\n这是经过整理的实质正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"

            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertFalse(archive.exists())
            self.assertTrue((out_dir / "summary.md").is_file())
            self.assertTrue((out_dir / "mindmap.mmd").is_file())

    def test_publish_failure_restores_existing_files_without_non_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            summary_path = out_dir / "summary.md"
            mindmap_path = out_dir / "mindmap.mmd"
            summary_path.write_text("旧摘要\n", encoding="utf-8")
            mindmap_path.write_text("旧脑图\n", encoding="utf-8")
            original_replace = llm.os.replace
            failure_injected = False

            def fail_mindmap_publish(source: str | bytes | Path, destination: str | bytes | Path) -> None:
                nonlocal failure_injected
                if (
                    not failure_injected
                    and Path(destination) == mindmap_path
                    and Path(source).name.startswith(".mindmap.mmd.")
                ):
                    failure_injected = True
                    raise OSError("模拟脑图发布失败")
                original_replace(source, destination)

            with mock.patch.object(llm.os, "replace", side_effect=fail_mindmap_publish), mock.patch.object(
                Path,
                "write_bytes",
                side_effect=AssertionError("恢复不得使用非原子 write_bytes"),
            ):
                with self.assertRaises(OSError):
                    llm._publish_final_outputs(out_dir, "新摘要\n", "新脑图\n")

            self.assertEqual(summary_path.read_text(encoding="utf-8"), "旧摘要\n")
            self.assertEqual(mindmap_path.read_text(encoding="utf-8"), "旧脑图\n")
            self.assertEqual(list(out_dir.glob(".*.tmp")), [])

    def test_local_document_prompt_uses_safe_display_name(self) -> None:
        source = r"D:\private\资料\黄金投资体系.docx"

        prompt = llm.build_llm_prompt(
            "黄金投资体系",
            source,
            "本地文件",
            "未知",
            "文档正文足够长，用于验证文档提示词。",
            None,
            "文档草稿摘要",
            "video",
        )

        self.assertIn("- url: 黄金投资体系.docx", prompt)
        self.assertNotIn(str(Path(source).parent), prompt)
        self.assertNotIn(source, prompt)

    def test_local_video_prompt_uses_safe_display_name(self) -> None:
        source = r"C:\private\视频\课程第一讲.mp4"

        prompt = llm.build_llm_prompt(
            "课程第一讲",
            source,
            "本地文件",
            "未知",
            "视频转写内容足够长，用于验证视频提示词。",
            "zh",
            "视频草稿摘要",
            "video",
        )

        self.assertIn("- url: 课程第一讲.mp4", prompt)
        self.assertNotIn(str(Path(source).parent), prompt)
        self.assertNotIn(source, prompt)

    def test_local_document_summary_removes_parent_path_before_publish(self) -> None:
        source = r"D:\private\资料\黄金投资体系.docx"
        refined = f"# 文档精校总结\n\n来源：{source}\n父目录：{Path(source).parent}\n\n正文。"

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "黄金投资体系", "uploader": "本地文件", "duration": None},
                    source,
                    out_dir,
                    "文档原文足够长，用于验证文档最终稿不会泄露本地父路径。",
                    None,
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")

        self.assertIn("来源：黄金投资体系.docx", published)
        self.assertNotIn(str(Path(source).parent), published)
        self.assertNotIn(source, published)

    def test_local_video_summary_removes_parent_path_before_publish(self) -> None:
        source = r"C:\private\视频\课程第一讲.mp4"
        refined = f"# 视频精校总结\n\n来源：{source}\n父目录：{Path(source).parent}\n\n正文。"

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "课程第一讲", "uploader": "本地文件", "duration": None},
                    source,
                    out_dir,
                    "视频转写内容足够长，用于验证视频最终稿不会泄露本地父路径。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")

        self.assertIn("来源：课程第一讲.mp4", published)
        self.assertNotIn(str(Path(source).parent), published)
        self.assertNotIn(source, published)

    def test_local_video_final_summary_uses_chinese_transcription_label(self) -> None:
        source = r"C:\private\视频\课程第一讲.mp4"
        refined = (
            "# 视频精校总结\n\n"
            "## 元信息\n"
            "- 来源：课程第一讲.mp4\n"
            "- 文稿来源：local transcription\n\n"
            "## 摘要\n"
            "这是保留的高质量精修摘要。"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "课程第一讲", "uploader": "本地文件", "duration": None},
                    source,
                    out_dir,
                    "本地音频转写内容足够长，用于验证最终稿元信息标签。",
                    None,
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")

        self.assertIn("- 文稿来源：本地转写", published)
        self.assertNotIn("local transcription", published)

    def test_remote_url_remains_unchanged_in_prompt_and_published_summary(self) -> None:
        source = "https://example.test/video?id=123"
        prompt = llm.build_llm_prompt(
            "远程视频",
            source,
            "作者",
            "未知",
            "远程视频转写内容。",
            "zh",
            "草稿摘要",
            "video",
        )
        refined = f"# 远程视频\n\n来源：{source}\n\n正文。"

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "远程视频", "uploader": "作者", "duration": None},
                    source,
                    out_dir,
                    "远程视频转写内容。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")

        self.assertIn(f"- url: {source}", prompt)
        self.assertIn(f"来源：{source}", published)

    def test_document_prompt_labels_source_as_document_and_forbids_full_transcript(self) -> None:
        prompt = llm.build_llm_prompt(
            "黄金投资体系",
            "D:/资料/黄金投资体系.docx",
            "本地文件",
            "未知",
            "文档正文足够长，用于验证文档提示词。",
            None,
            "文档草稿摘要",
            "video",
        )

        self.assertIn("transcript source: 文档", prompt)
        self.assertNotIn("transcript source: local transcription", prompt)
        self.assertIn("不得输出完整逐字稿", prompt)

    def test_document_final_summary_removes_transcript_and_normalizes_source(self) -> None:
        refined = """# 文档精校总结

## 元信息
- 来源：`D:/资料/黄金投资体系.docx`
- 文稿来源：本地音频转写

## 摘要
这是保留的高质量精修摘要。

## 思维导图
```mermaid
mindmap
  root((黄金))
```

## 整理后逐字稿
这是不应进入最终稿的完整文档原文：文档原文完整内容哨兵。
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "黄金投资体系", "uploader": "本地文件", "duration": None},
                    "D:/资料/黄金投资体系.docx",
                    out_dir,
                    "文档原文足够长，用于验证文档最终稿不会复制完整 transcript。",
                    None,
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")

        self.assertIn("## 摘要", published)
        self.assertIn("这是保留的高质量精修摘要。", published)
        self.assertIn("- 文稿来源：文档", published)
        self.assertNotIn("本地音频转写", published)
        self.assertNotIn("## 整理后逐字稿", published)
        self.assertNotIn("文档原文完整内容哨兵", published)

    def test_titled_full_or_large_transcript_copy_is_rejected_before_publish(self) -> None:
        transcript = (
            "第一部分讨论目标与背景，强调先建立清晰的问题边界。"
            "第二部分说明方法与步骤，要求根据证据逐项验证结论。"
            "第三部分回顾常见误区，提醒不要把中间材料当作最终交付。"
            "第四部分给出执行建议，先小范围测试再逐步扩大。"
            "第五部分总结验收标准，要求把结论落实为可复核行动。"
        )
        responses = (
            "# 摘要\n\n" + transcript,
            "# 摘要\n\n" + transcript[:-24] + "\n\n补充说明。",
        )
        for response in responses:
            with self.subTest(response=response[:24]):
                self._assert_invalid_refinement_is_not_published(response, transcript)

    def test_titled_long_summary_is_published(self) -> None:
        transcript = "原始逐字稿讨论了背景、方法和执行风险，但最终摘要应重新组织观点。"
        refined = """# 精校摘要

## 核心结论
本视频先界定问题，再比较不同方案的适用边界，最后给出可复核的执行步骤。

## 实践建议
先验证关键假设，再用小范围实验观察结果，确认有效后再扩大应用范围。
""".strip()

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    transcript,
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")

    def test_titled_summary_with_one_to_three_quoted_sentences_is_published(self) -> None:
        transcript = (
            "第一句原始内容说明要先确认问题边界。"
            "第二句原始内容说明要根据证据验证结论。"
            "第三句原始内容说明要在小范围内测试方案。"
            "第四句原始内容说明要记录结果并持续复盘。"
        )
        refined = """# 精校摘要

视频将问题拆成边界、证据和验证三个环节，并把复杂讨论转化为可执行步骤。

> 第一句原始内容说明要先确认问题边界。
> 第二句原始内容说明要根据证据验证结论。

因此，执行时应先做小范围测试，再根据结果调整方案。
""".strip()

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    transcript,
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")

    def test_titled_chinese_and_english_refusals_are_rejected_before_publish(self) -> None:
        responses = (
            "# 摘要\n\n抱歉，我无法完成这个请求。",
            "# Summary\n\nI'm sorry, I can't provide a summary for this request.",
        )
        for response in responses:
            with self.subTest(response=response):
                self._assert_invalid_refinement_is_not_published(response)

    def test_slash_separator_between_words_is_not_rejected_as_path(self) -> None:
        refined = """# 精校摘要

## 核心结论
相对控股 / 绝对控股的分界是市占率 30% 与 50%，竞争格局比行业增速更重要。

## 实践建议
先验证关键假设，再小范围测试。
""".strip()

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "这是用于校验最终稿质量的原始逐字稿，内容足够长，用于验证斜杠分隔词不会被误判为本机路径。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")

    def test_any_windows_or_unix_absolute_path_is_rejected_before_publish(self) -> None:
        paths = (
            "/secret",
            "/tmp",
            "/Users",
            "/",
            "C:\\",
            "C:/",
            r"\\",
            r"\\server\share",
        )
        for local_path in paths:
            with self.subTest(local_path=local_path):
                self._assert_invalid_refinement_is_not_published(
                    f"# 摘要\n\n这是正常正文。\n\n来源文件：{local_path}"
                )

    def test_mermaid_absolute_paths_are_rejected_before_publish(self) -> None:
        paths = (
            "/secret",
            "/tmp",
            "/Users",
            "/",
            "C:\\",
            "C:/",
            r"\\",
            r"\\server\share",
        )
        for local_path in paths:
            responses = (
                f"# 摘要\n\n这是正常正文。\n\n```mermaid\nmindmap\n  root(({local_path}))\n```",
                f"# 摘要\n\n这是正常正文。\n\nmindmap\n  root(({local_path}))",
            )
            for response in responses:
                with self.subTest(local_path=local_path, response=response):
                    self._assert_invalid_refinement_is_not_published(response)

    def test_remote_url_inside_mermaid_is_not_treated_as_local_path(self) -> None:
        refined = (
            "# 摘要\n\n这是正常正文。\n\n"
            "```mermaid\nmindmap\n  root((https://example.test/video/path?id=123))\n```"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证远程 URL 不应被本机路径规则误伤。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertTrue((out_dir / "summary.md").is_file())
            self.assertTrue((out_dir / "mindmap.mmd").is_file())

    def test_mindmap_word_in_plain_text_does_not_remove_following_content(self) -> None:
        summary = "# 摘要\n\nmindmap 是本文用来说明结构的普通术语。\n\n后续结论仍然重要。"

        self.assertEqual(llm._without_mermaid(summary), summary)

    def test_extract_mermaid_bare_mindmap_stops_before_following_markdown_or_plain_text(self) -> None:
        for suffix in ("## 后续章节\n\n后续正文。", "后续普通正文。"):
            with self.subTest(suffix=suffix):
                response = (
                    "# 摘要\n\n前置正文。\n\n"
                    "mindmap\n"
                    "  root((测试主题))\n"
                    "    章节一\n"
                    f"{suffix}"
                )
                extracted = llm.extract_mermaid(response)

                self.assertEqual(
                    extracted,
                    "mindmap\n  root((测试主题))\n    章节一",
                )
                self.assertNotIn("后续章节", extracted)
                self.assertNotIn("后续正文", extracted)
                self.assertNotIn("后续普通正文", extracted)

    def test_bare_mindmap_is_removed_from_published_summary_without_swallowing_following_content(self) -> None:
        refined = (
            "# 摘要\n\n前置正文。\n\n"
            "mindmap\n"
            "  root((测试主题))\n"
            "    章节一\n"
            "## 后续章节\n\n后续正文。"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证裸脑图不会污染最终摘要。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            published = (out_dir / "summary.md").read_text(encoding="utf-8")
            published_mindmap = (out_dir / "mindmap.mmd").read_text(encoding="utf-8")

        self.assertIn("前置正文。", published)
        self.assertIn("## 后续章节", published)
        self.assertIn("后续正文。", published)
        self.assertNotIn("mindmap", published)
        self.assertNotIn("root((测试主题))", published)
        self.assertNotIn("章节一", published)
        self.assertEqual(
            published_mindmap,
            "mindmap\n  root((测试主题))\n    章节一\n",
        )
        self.assertNotIn("后续章节", published_mindmap)
        self.assertNotIn("后续正文", published_mindmap)

    def test_bare_mindmap_only_is_still_rejected_before_publish(self) -> None:
        self._assert_invalid_refinement_is_not_published(
            "mindmap\n  root((测试主题))\n    章节一"
        )

    def test_quality_failure_hides_stale_root_final_files_without_archive(self) -> None:
        transcript = "这是本次运行的原始逐字稿，内容足够长，用于验证质量失败时旧最终稿仍然可见。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "output"
            run_dir = root / "run"
            out_dir.mkdir()
            (out_dir / "summary.md").write_text("旧最终摘要\n", encoding="utf-8")
            (out_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm, "call_llm", return_value="# 摘要\n\n抱歉，我无法完成这个请求。"):
                with self.assertRaises(config.UserFacingError):
                    llm.refine_with_llm({"title": "测试视频", "uploader": "作者", "duration": 90}, "https://example.test/video", out_dir, transcript, "zh", "gpt-test", "responses", 12000, "video", workspace_dir=run_dir)
            self.assertFalse((out_dir / "summary.md").exists())
            self.assertFalse((out_dir / "mindmap.mmd").exists())
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_reference_prompts_forbid_full_transcript_in_final_output(self) -> None:
        references = Path(llm.REFERENCES_DIR)
        for filename in ("refined_prompt.md", "lecture_prompt.md"):
            with self.subTest(filename=filename):
                prompt = (references / filename).read_text(encoding="utf-8")
                self.assertNotIn("## 口播逐字稿", prompt)
                self.assertNotIn("## 整理后逐字稿", prompt)
                self.assertIn("transcript 仅作分析依据", prompt)
                self.assertIn("最终稿不得包含完整逐字稿", prompt)

    def _assert_invalid_refinement_is_not_published(
        self,
        response: str | None,
        transcript: str = "这是用于校验最终稿质量的原始逐字稿，内容足够长。",
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=response
            ):
                try:
                    llm.refine_with_llm(
                        {"title": "测试视频", "uploader": "作者", "duration": 90},
                        "https://example.test/video",
                        out_dir,
                        transcript,
                        "zh",
                        "gpt-test",
                        "responses",
                        12000,
                        "video",
                    )
                except BaseException as error:
                    self.assertIsInstance(error, config.UserFacingError)
                    self.assertNotEqual(getattr(error, "code", 0), 0)
                    self.assertIn("LLM 返回", getattr(error, "message", str(error)))
                else:
                    self.fail("无效 LLM 响应不得发布最终稿")

            self.assertFalse((out_dir / "summary.md").exists())
            self.assertFalse((out_dir / "mindmap.mmd").exists())
            self.assertEqual(list(out_dir.glob(".*.tmp")), [])

    def test_empty_llm_response_is_rejected_before_publish(self) -> None:
        self._assert_invalid_refinement_is_not_published(None)

    def test_refusal_and_invalid_short_llm_responses_are_rejected(self) -> None:
        for response in ("抱歉，我无法完成这个请求。", "好的。"):
            with self.subTest(response=response):
                self._assert_invalid_refinement_is_not_published(response)

    def test_title_plus_fenced_mermaid_only_llm_response_is_rejected_before_publish(self) -> None:
        response = "# 摘要\n\n```mermaid\nmindmap\n  root((测试主题))\n```"
        self._assert_invalid_refinement_is_not_published(response)

    def test_mindmap_heading_plus_fenced_mermaid_only_llm_response_is_rejected_before_publish(self) -> None:
        response = "## 思维导图\n\n```mermaid\nmindmap\n  root((测试主题))\n```"
        self._assert_invalid_refinement_is_not_published(response)

    def test_title_plus_bare_mindmap_only_llm_response_is_rejected_before_publish(self) -> None:
        response = "# 摘要\n\nmindmap\n  root((测试主题))"
        self._assert_invalid_refinement_is_not_published(response)

    def test_setext_title_plus_fenced_mermaid_only_is_rejected_before_publish(self) -> None:
        response = "摘要\n===\n\n```mermaid\nmindmap\n  root((测试主题))\n```"
        self._assert_invalid_refinement_is_not_published(response)

    def test_unclosed_mermaid_fence_without_body_is_rejected_before_publish(self) -> None:
        response = "# 摘要\n\n```mermaid\nmindmap\n  root((测试主题))"
        self._assert_invalid_refinement_is_not_published(response)

    def test_unclosed_mermaid_fence_after_real_body_does_not_reject_summary(self) -> None:
        refined = "# 摘要\n\n这是经过整理的实质正文。\n\n```mermaid\nmindmap\n  root((测试主题))"
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证正文不会被 Mermaid 边界误伤。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertIn("这是经过整理的实质正文。", (out_dir / "summary.md").read_text(encoding="utf-8"))

    def test_invalid_fenced_mermaid_is_not_published_as_mindmap(self) -> None:
        responses = (
            "# 摘要\n\n这是正常正文。\n\n```mermaid\nnot a mermaid diagram\n```",
            "# 摘要\n\n这是正常正文。\n\n```mermaid\n```",
            "# 摘要\n\n这是正常正文。\n\n```mermaid\ngraph TD\n  A --> B\n```",
        )
        for refined in responses:
            with self.subTest(refined=refined):
                with tempfile.TemporaryDirectory() as temp_dir:
                    out_dir = Path(temp_dir)
                    with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                        llm, "call_llm", return_value=refined
                    ):
                        llm.refine_with_llm(
                            {"title": "测试视频", "uploader": "作者", "duration": 90},
                            "https://example.test/video",
                            out_dir,
                            "本次运行的逐字稿内容足够长，用于验证无效 Mermaid 不应生成脑图文件。",
                            "zh",
                            "gpt-test",
                            "responses",
                            12000,
                            "video",
                        )

                    self.assertEqual(
                        (out_dir / "summary.md").read_text(encoding="utf-8"),
                        refined + "\n",
                    )
                    self.assertFalse((out_dir / "mindmap.mmd").exists())

    def test_fenced_mindmap_with_root_or_indented_node_is_published(self) -> None:
        responses = (
            "```mermaid\nmindmap\n  root((测试主题))\n```",
            "```mermaid\nmindmap\n  章节一\n```",
        )
        for mermaid in responses:
            with self.subTest(mermaid=mermaid):
                refined = f"# 摘要\n\n这是正常正文。\n\n{mermaid}"
                with tempfile.TemporaryDirectory() as temp_dir:
                    out_dir = Path(temp_dir)
                    with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                        llm, "call_llm", return_value=refined
                    ):
                        llm.refine_with_llm(
                            {"title": "测试视频", "uploader": "作者", "duration": 90},
                            "https://example.test/video",
                            out_dir,
                            "本次运行的逐字稿内容足够长，用于验证合法 mindmap 仍可生成脑图文件。",
                            "zh",
                            "gpt-test",
                            "responses",
                            12000,
                            "video",
                        )

                    self.assertTrue((out_dir / "summary.md").is_file())
                    self.assertEqual(
                        (out_dir / "mindmap.mmd").read_text(encoding="utf-8"),
                        mermaid.removeprefix("```mermaid\n").removesuffix("```").rstrip() + "\n",
                    )

    def test_title_body_and_fenced_mermaid_llm_response_is_published(self) -> None:
        refined = (
            "# 摘要\n\n这是经过整理的实质正文，说明主题、方法与结论。\n\n"
            "```mermaid\nmindmap\n  root((测试主题))\n```"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证合法摘要与 Mermaid 同时发布。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")
            self.assertEqual(
                (out_dir / "mindmap.mmd").read_text(encoding="utf-8"),
                "mindmap\n  root((测试主题))\n",
            )

    def test_normal_summary_without_mermaid_is_still_published(self) -> None:
        refined = "# 摘要\n\n这是没有 Mermaid 的正常实质摘要。"
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                llm, "call_llm", return_value=refined
            ):
                llm.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "本次运行的逐字稿内容足够长，用于验证无 Mermaid 的正常摘要仍可发布。",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")
            self.assertFalse((out_dir / "mindmap.mmd").exists())

    def test_transcript_only_llm_response_is_rejected_before_publish(self) -> None:
        transcript = "第一段原始逐字稿内容。第二段原始逐字稿内容。第三段原始逐字稿内容。"
        self._assert_invalid_refinement_is_not_published(transcript, transcript)

    def test_untitled_high_copy_transcript_response_is_rejected_before_publish(self) -> None:
        transcript = (
            "第一部分讨论目标与背景，强调先建立清晰的问题边界。"
            "第二部分说明方法与步骤，要求根据证据逐项验证结论。"
            "第三部分回顾常见误区，提醒不要把中间材料当作最终交付。"
            "第四部分给出执行建议，先小范围测试再逐步扩大。"
        )
        response = "下面是整理后的内容：\n" + transcript
        self._assert_invalid_refinement_is_not_published(response, transcript)

if __name__ == "__main__":
    unittest.main()


