from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def load_module() -> types.SimpleNamespace:
    """Expose the canonical src package APIs under the regression test seam."""
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    from video_summary import artifacts, config, documents, llm, mermaid, outputs, sources
    from video_summary import subtitles, summarization, transcription

    return types.SimpleNamespace(
        extract_document_text=documents.extract_document_text,
        parse_subtitle_segments=subtitles.parse_subtitle_segments,
        json_subtitle_to_segments=subtitles.json_subtitle_to_segments,
        write_transcript_artifacts=artifacts.write_transcript_artifacts,
        refresh_existing_segment_artifacts=artifacts.refresh_existing_segment_artifacts,
        fetch_subtitle=subtitles.fetch_subtitle,
        chapterize_from_files=summarization.chapterize_from_files,
        load_domain_config=config.load_domain_config,
        references_dir=config.REFERENCES_DIR,
        local_source_id=sources.local_source_id,
        slug_from_info=sources.slug_from_info,
        keywords=summarization.keywords,
        transcribe_audio_local=transcription.transcribe_audio_local,
        default_transcribe_language=config.default_transcribe_language,
        write_outputs=outputs.write_outputs,
        prepare_output_directory=outputs.prepare_output_directory,
        build_llm_prompt=llm.build_llm_prompt,
        build_lecture_chunk_prompt=llm.build_lecture_chunk_prompt,
        urllib=llm.urllib,
        time=llm.time,
        os=llm.os,
        call_llm=llm.call_llm,
        llm_module=llm,
        refine_with_llm=llm.refine_with_llm,
        should_chunk_lecture=llm.should_chunk_lecture,
        split_transcript_for_llm=llm.split_transcript_for_llm,
        write_chunk_summaries=artifacts.write_chunk_summaries,
        load_existing_chunk_summaries=artifacts.load_existing_chunk_summaries,
        build_mermaid=mermaid.build_mermaid,
        json=json,
    )

class VideoSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_extract_docx_text_from_ooxml_container(self) -> None:
        import zipfile

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.doc"
            document_xml = (
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                "<w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>"
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document_xml)
            text = self.module.extract_document_text(path)
        self.assertEqual(text, "第一段\n第二段")

    def test_extract_pdf_text_uses_pypdf(self) -> None:
        fake_pypdf = types.ModuleType("pypdf")

        class Page:
            def extract_text(self):
                return "PDF 第一页"

        class PdfReader:
            def __init__(self, path):
                self.pages = [Page()]

        fake_pypdf.PdfReader = PdfReader
        original = sys.modules.get("pypdf")
        sys.modules["pypdf"] = fake_pypdf
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "sample.pdf"
                path.write_bytes(b"%PDF-fake")
                text = self.module.extract_document_text(path)
        finally:
            if original is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = original
        self.assertEqual(text, "PDF 第一页")

    def test_extract_image_only_pdf_is_rejected_without_ocr(self) -> None:
        from video_summary.config import UserFacingError

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
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "image-only.pdf"
                path.write_bytes(b"%PDF-image-only")
                with self.assertRaises(UserFacingError) as raised:
                    self.module.extract_document_text(path)
        finally:
            if original is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = original

        self.assertIn("图像型 PDF", raised.exception.message)
        self.assertIn("文本层", raised.exception.message)

    def test_vtt_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.vtt"
            path.write_text(
                "WEBVTT\n\n00:01.000 --> 00:03.500\n第一句\n\n00:04.000 --> 00:06.000\n第二句\n",
                encoding="utf-8",
            )
            segments = self.module.parse_subtitle_segments(path)
        self.assertEqual(segments[0]["start"], 1.0)
        self.assertEqual(segments[0]["end"], 3.5)
        self.assertEqual(segments[0]["text"], "第一句")

    def test_srt_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.srt"
            path.write_text(
                "1\n00:00:02,000 --> 00:00:04,000\nHello world\n\n2\n00:00:05,000 --> 00:00:06,000\nNext line\n",
                encoding="utf-8",
            )
            segments = self.module.parse_subtitle_segments(path)
        self.assertEqual(segments[1]["start"], 5.0)
        self.assertEqual(segments[1]["text"], "Next line")

    def test_json_segments(self) -> None:
        raw = {
            "events": [
                {"tStartMs": 1200, "dDurationMs": 800, "segs": [{"utf8": "JSON 字幕"}]},
            ]
        }
        segments = self.module.json_subtitle_to_segments(json.dumps(raw, ensure_ascii=False))
        self.assertEqual(segments, [{"start": 1.2, "end": 2.0, "text": "JSON 字幕"}])

    def test_json_millisecond_timestamp_over_100_seconds(self) -> None:
        raw = {
            "events": [
                {"tStartMs": 123456, "dDurationMs": 1500, "segs": [{"utf8": "长视频 JSON 字幕"}]},
            ]
        }
        segments = self.module.json_subtitle_to_segments(json.dumps(raw, ensure_ascii=False))
        self.assertEqual(segments[0]["start"], 123.456)
        self.assertEqual(segments[0]["end"], 124.956)

    def test_timed_transcript_and_chapter_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            segments = [
                {"start": 10, "end": 20, "text": "这是第一段足够长的字幕内容，用于生成章节摘要。"},
                {"start": 70, "end": 80, "text": "这是第二段足够长的字幕内容，用于生成章节摘要。"},
            ]
            self.module.write_transcript_artifacts(out_dir, "文本", segments)
            timed = (out_dir / "_internal" / "transcript_timed.txt").read_text(encoding="utf-8")
            chapters = self.module.chapterize_from_files(out_dir, "文本", 2)
        self.assertIn("[00:10]", timed)
        self.assertEqual(chapters[0]["time"], 10)

    def test_local_source_ids_distinguish_same_name_and_extension_in_different_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-unit-") as temp_dir:
            root = Path(temp_dir)
            left = root / "left" / "same-name.docx"
            right = root / "right" / "same-name.docx"

            self.assertNotEqual(
                self.module.local_source_id(left),
                self.module.local_source_id(right),
            )
            self.assertEqual(
                self.module.local_source_id(left),
                self.module.local_source_id(Path(str(left))),
            )
            self.assertNotIn("left", self.module.local_source_id(left))
            self.assertNotIn("right", self.module.local_source_id(right))

    def test_online_source_ids_keep_platform_identifier_behavior(self) -> None:
        self.assertEqual(
            self.module.slug_from_info(
                {"id": "BV1abc123", "display_id": "video-title"},
                "https://www.bilibili.com/video/BV1abc123/",
            ),
            "BV1abc123",
        )

    def test_runtime_references_are_inside_src_package(self) -> None:
        expected = SRC_ROOT / "video_summary" / "references"

        self.assertEqual(self.module.references_dir, expected)
        self.assertTrue((expected / "domain_terms.json").is_file())
        self.assertTrue((expected / "lecture_prompt.md").is_file())
        self.assertTrue((expected / "refined_prompt.md").is_file())
        self.assertNotIn(".agents", str(self.module.references_dir))

    def test_domain_terms_are_opt_in(self) -> None:
        self.module.load_domain_config("general")
        self.assertNotIn("情绪价值", self.module.keywords("情绪价值 情绪价值", 3))
        self.module.load_domain_config("zh-social")
        self.assertIn("情绪价值", self.module.keywords("情绪价值 情绪价值", 3))

    def test_auto_language_does_not_pin_zh(self) -> None:
        calls = []

        class Segment:
            start = 0
            end = 1
            text = " hello "

        class Info:
            language = "en"
            language_probability = 0.9

        class WhisperModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, audio, **kwargs):
                calls.append(kwargs)
                return [Segment()], Info()

        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = WhisperModel
        original = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = fake_module
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                self.module.transcribe_audio_local(Path(temp_dir) / "audio.mp3", Path(temp_dir), "tiny", "auto")
        finally:
            if original is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = original
        self.assertEqual(calls, [{"vad_filter": True}])

    def test_default_language_is_auto_and_env_can_override(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.module.default_transcribe_language(), "auto")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_LANGUAGE": "zh"}, clear=True):
            self.assertEqual(self.module.default_transcribe_language(), "zh")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_LANGUAGE": "chinese"}, clear=True):
            self.assertEqual(self.module.default_transcribe_language(), "auto")

    def test_fetched_subtitles_are_internal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = "WEBVTT\n\n00:00.000 --> 00:01.000\n字幕内容\n".encode("utf-8")
            with mock.patch.object(self.module.urllib.request, "urlopen", return_value=response):
                target = self.module.fetch_subtitle(
                    {"url": "https://example.test/subtitle", "ext": "vtt"},
                    out_dir,
                    "zh-Hans",
                )

            self.assertEqual(target, out_dir / "_internal" / "subtitle.zh-Hans.vtt")
            self.assertTrue(target.is_file())
            self.assertEqual(list(out_dir.glob("subtitle.*")), [])

    def test_outputs_include_analysis_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            transcript = "这是第一段足够长的字幕内容，用于生成摘要和范围提示。" * 4
            self.module.write_outputs(
                {"title": "测试视频", "uploader": "作者", "duration": 90},
                "https://example.test/video",
                out_dir,
                transcript,
                "zh",
                "compact",
            )
            metadata = json.loads((out_dir / "_internal" / "metadata.json").read_text(encoding="utf-8"))
            summary = (out_dir / "_internal" / "summary_draft.md").read_text(encoding="utf-8")
        self.assertEqual(metadata["analysis_basis"], "subtitle_or_audio_or_document_text")
        self.assertIn("仅基于字幕、音频转写或文档文本", summary)

    def test_llm_prompt_declares_audio_only_basis(self) -> None:
        prompt = self.module.build_llm_prompt(
            title="标题",
            source="https://example.test/video",
            author="作者",
            duration="00:01:00",
            transcript="逐字稿",
            subtitle_lang=None,
            draft_summary="草稿",
            content_type="video",
        )
        chunk_prompt = self.module.build_lecture_chunk_prompt(
            title="标题",
            source="https://example.test/video",
            author="作者",
            duration="00:01:00",
            subtitle_lang=None,
            chunk_index=1,
            chunk_count=2,
            chunk={"start": 0, "end": 10, "text": "分段逐字稿"},
        )
        self.assertIn("no OCR, screenshots, or visual scene understanding", prompt)
        self.assertIn("no OCR, screenshots, or visual scene understanding", chunk_prompt)
        self.assertIn("分析范围：仅基于字幕/音频转写", prompt)
        document_prompt = self.module.build_llm_prompt(
            title="扫描文档",
            source="D:/Documents/scanned.pdf",
            author="作者",
            duration="未知",
            transcript="OCR 文档正文",
            subtitle_lang=None,
            draft_summary="草稿",
            content_type="video",
        )
        self.assertIn("document text from a text-layer PDF or OOXML document", document_prompt)
        self.assertIn("no audio transcription, OCR", document_prompt)
        self.assertNotIn("including optional PDF OCR", document_prompt)

    def test_call_llm_retries_429_then_succeeds(self) -> None:
        response = FakeResponse({"choices": [{"message": {"content": "成功"}}]})
        error = self.http_error(429, "rate limit")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True), \
                mock.patch.object(self.module.urllib.request, "urlopen", side_effect=[error, response]) as urlopen, \
                mock.patch.object(self.module.time, "sleep") as sleep:
            result = self.module.call_llm("prompt", "model", "chat")
        self.assertEqual(result, "成功")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_call_llm_retries_502_then_succeeds(self) -> None:
        response = FakeResponse({"choices": [{"message": {"content": "成功"}}]})
        error = self.http_error(502, "bad gateway")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True), \
                mock.patch.object(self.module.urllib.request, "urlopen", side_effect=[error, response]) as urlopen, \
                mock.patch.object(self.module.time, "sleep") as sleep:
            result = self.module.call_llm("prompt", "model", "chat")
        self.assertEqual(result, "成功")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_call_llm_does_not_retry_401(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True), \
                mock.patch.object(self.module.urllib.request, "urlopen", side_effect=self.http_error(401, "unauthorized")) as urlopen, \
                mock.patch.object(self.module.time, "sleep") as sleep:
            with self.assertRaises(SystemExit):
                self.module.call_llm("prompt", "model", "chat")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_call_llm_fails_after_retry_limit(self) -> None:
        errors = [self.http_error(502, f"bad gateway {index}") for index in range(3)]
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True), \
                mock.patch.object(self.module.urllib.request, "urlopen", side_effect=errors) as urlopen, \
                mock.patch.object(self.module.time, "sleep") as sleep:
            with self.assertRaises(SystemExit):
                self.module.call_llm("prompt", "model", "chat")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def http_error(self, status: int, detail: str):
        return self.module.urllib.error.HTTPError(
            "https://example.test",
            status,
            detail,
            {},
            io.BytesIO(detail.encode("utf-8")),
        )

    def test_lecture_should_chunk_before_default_request_limit(self) -> None:
        self.assertTrue(self.module.should_chunk_lecture("x" * 12001, 60000))
        self.assertFalse(self.module.should_chunk_lecture("x" * 12000, 60000))

    def test_long_lecture_split_uses_all_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            segments = [
                {"start": 0, "end": 10, "text": "第一段课程内容很长"},
                {"start": 20, "end": 30, "text": "第二段课程内容很长"},
                {"start": 40, "end": 50, "text": "第三段课程内容很长"},
            ]
            self.module.write_transcript_artifacts(out_dir, "文本", segments)
            chunks = self.module.split_transcript_for_llm(out_dir, "文本", 28)
        joined = "\n".join(chunk["text"] for chunk in chunks)
        self.assertGreater(len(chunks), 1)
        self.assertIn("第一段课程内容很长", joined)
        self.assertIn("第三段课程内容很长", joined)

    def test_chunk_summaries_are_incremental_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            self.module.write_chunk_summaries(out_dir, [{"index": 1, "start": 0, "end": 10, "summary": "已完成"}])
            loaded = self.module.load_existing_chunk_summaries(out_dir)
        self.assertEqual(loaded, [{"index": 1, "start": 0, "end": 10, "summary": "已完成"}])

    def test_mermaid_text_strips_fragile_characters(self) -> None:
        mermaid = self.module.build_mermaid("标题(测试)", ["章节`一`"], ['观点"二"'], ["术语[三]"])
        self.assertNotIn("标题(测试)", mermaid)
        self.assertNotIn("`", mermaid)
        self.assertNotIn('"', mermaid)
        self.assertNotIn("[三]", mermaid)

    def test_reuse_transcript_refreshes_timed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            transcript = "[00:12] 复用逐字稿第一段内容足够长。\n[01:05] 复用逐字稿第二段内容足够长。"
            self.module.refresh_existing_segment_artifacts(out_dir, transcript)
            segments = json.loads((out_dir / "_internal" / "transcript_segments.json").read_text(encoding="utf-8"))
            timed = (out_dir / "_internal" / "transcript_timed.txt").read_text(encoding="utf-8")
        self.assertEqual(segments[0]["start"], 12.0)
        self.assertIn("[01:05]", timed)

    def test_offline_outputs_are_internal_drafts_until_llm_refinement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            self.module.write_outputs(
                {"title": "测试视频", "uploader": "作者", "duration": 90},
                "https://example.test/video",
                out_dir,
                "逐字稿内容足够长，用于生成中间摘要和脑图草稿。",
                "zh",
                "compact",
            )
            self.assertTrue((out_dir / "_internal" / "summary_draft.md").exists())
            self.assertTrue((out_dir / "_internal" / "mindmap_draft.mmd").exists())
            self.assertFalse((out_dir / "summary.md").exists())
            self.assertFalse((out_dir / "mindmap.mmd").exists())
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_new_output_clears_previous_summary_chunk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            internal = out_dir / "_internal"
            internal.mkdir(parents=True)
            stale_cache = internal / "summary_chunks.json"
            stale_cache.write_text(
                '[{"index": 1, "summary": "旧逐字稿的摘要"}]',
                encoding="utf-8",
            )

            self.module.prepare_output_directory(out_dir)
            self.module.write_outputs(
                {"title": "测试视频", "uploader": "作者", "duration": 90},
                "https://example.test/video",
                out_dir,
                "新逐字稿内容足够长，用于验证每轮新输出不复用旧分块缓存。",
                "zh",
                "compact",
            )

            self.assertFalse(stale_cache.exists())

    def test_llm_refinement_failure_archives_existing_final_files_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            summary = out_dir / "summary.md"
            mindmap = out_dir / "mindmap.mmd"
            summary.write_text("既有最终摘要\n", encoding="utf-8")
            mindmap.write_text("mindmap\n  root((既有最终脑图))\n", encoding="utf-8")

            self.module.prepare_output_directory(out_dir)
            self.module.write_outputs(
                {"title": "测试视频", "uploader": "作者", "duration": 90},
                "https://example.test/video",
                out_dir,
                "逐字稿内容足够长，用于生成本次运行的内部草稿。",
                "zh",
                "compact",
            )
            archive = out_dir / "_internal" / "previous_final"
            self.assertFalse(summary.exists())
            self.assertFalse(mindmap.exists())

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                self.module.llm_module, "call_llm", side_effect=RuntimeError("LLM 请求失败")
            ):
                with self.assertRaises(Exception):
                    self.module.refine_with_llm(
                        {"title": "测试视频", "uploader": "作者", "duration": 90},
                        "https://example.test/video",
                        out_dir,
                        "逐字稿",
                        "zh",
                        "gpt-test",
                        "responses",
                        12000,
                        "video",
                    )

            self.assertFalse(summary.exists())
            self.assertFalse(mindmap.exists())
            self.assertEqual((archive / "summary.md").read_text(encoding="utf-8"), "既有最终摘要\n")
            self.assertEqual((archive / "mindmap.mmd").read_text(encoding="utf-8"), "mindmap\n  root((既有最终脑图))\n")

    def test_llm_refinement_publishes_only_the_final_summary_and_mindmap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            internal = out_dir / "_internal"
            internal.mkdir(parents=True)
            (internal / "summary_draft.md").write_text("离线摘要草稿", encoding="utf-8")
            (internal / "mindmap_draft.mmd").write_text("mindmap\n  root((草稿))\n", encoding="utf-8")
            refined = "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                self.module.llm_module, "call_llm", return_value=refined
            ):
                self.module.refine_with_llm(
                    {"title": "测试视频", "uploader": "作者", "duration": 90},
                    "https://example.test/video",
                    out_dir,
                    "逐字稿",
                    "zh",
                    "gpt-test",
                    "responses",
                    12000,
                    "video",
                )

            root_files = {path.name for path in out_dir.iterdir() if path.is_file()}
            self.assertEqual(root_files, {"summary.md", "mindmap.mmd"})
            self.assertIn("精校摘要", (out_dir / "summary.md").read_text(encoding="utf-8"))
            self.assertIn("mindmap", (out_dir / "mindmap.mmd").read_text(encoding="utf-8"))


    def test_refined_draft_excludes_transcript_section(self) -> None:
        from video_summary.outputs import build_refined_summary

        transcript = "这是不应拼入精校草稿的完整逐字稿内容。"
        lines = build_refined_summary(
            "测试主题",
            "课程.pdf",
            "作者",
            90,
            None,
            transcript,
            ["核心结论"],
            ["核心概念"],
            [{"title": "第一章", "summary": "章节摘要", "time": 0}],
        )

        draft = "\n".join(lines)
        self.assertIn("## 思维导图", draft)
        self.assertNotIn("## 口播逐字稿", draft)
        self.assertNotIn(transcript, draft)

    def test_new_transcript_artifacts_are_written_under_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            transcript = "新输出逐字稿内容足够长，用于验证 support 目录契约。"

            self.module.write_transcript_artifacts(out_dir, transcript, None)

            self.assertEqual((out_dir / "support" / "transcript.txt").read_text(encoding="utf-8"), transcript)
            self.assertFalse((out_dir / "transcript.txt").exists())

    def test_safe_display_name_hides_local_parent_path_in_metadata_and_draft(self) -> None:
        from video_summary.sources import safe_display_name

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "private" / "课程内部.pdf"
            source.parent.mkdir()
            source.write_bytes(b"source")
            out_dir = Path(temp_dir) / "output"
            transcript = "这是足够长的文档文本，用于验证用户可见来源名称不会泄露本地父路径。"

            self.module.write_outputs(
                {"title": source.stem, "uploader": "本地文件", "duration": None},
                str(source),
                out_dir,
                transcript,
                None,
                "compact",
            )

            metadata = json.loads((out_dir / "_internal" / "metadata.json").read_text(encoding="utf-8"))
            draft = (out_dir / "_internal" / "summary_draft.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["source"], safe_display_name(str(source)))
            self.assertNotIn(str(source.parent), metadata["source"])
            self.assertNotIn(str(source.parent), draft)

    def test_final_transcript_sections_are_removed_for_every_input_type(self) -> None:
        from video_summary import llm

        generated = (
            "# 精校摘要\n\n"
            "## 核心结论\n正文。\n\n"
            "## 口播逐字稿\n完整逐字稿内容。\n\n"
            "### 逐字稿片段\n更多原文。\n\n"
            "## 结论\n保留。"
        )
        sources = (
            "https://example.test/video",
            r"C:\Videos\lesson.mp4",
            r"C:\Documents\lesson.pdf",
            r"C:\Documents\lesson.docx",
        )

        for source in sources:
            with self.subTest(source=source):
                cleaned = llm._prepare_final_summary(generated, source)
                self.assertIn("核心结论", cleaned)
                self.assertIn("结论", cleaned)
                self.assertNotIn("口播逐字稿", cleaned)
                self.assertNotIn("逐字稿片段", cleaned)
                self.assertNotIn("完整逐字稿内容", cleaned)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
