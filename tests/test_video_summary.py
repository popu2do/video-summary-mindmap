from __future__ import annotations

import io
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_CANDIDATES = (
    ROOT / "scripts" / "video_summary.py",
    ROOT / ".agents" / "skill" / "video-summary-mindmap" / "scripts" / "video_summary.py",
)
SCRIPT = next(path for path in SCRIPT_CANDIDATES if path.exists())


def load_module():
    spec = importlib.util.spec_from_file_location("video_summary_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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
            timed = (out_dir / "transcript_timed.txt").read_text(encoding="utf-8")
            chapters = self.module.chapterize_from_files(out_dir, "文本", 2)
        self.assertIn("[00:10]", timed)
        self.assertEqual(chapters[0]["time"], 10)

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
            metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
            summary = (out_dir / "summary.md").read_text(encoding="utf-8")
        self.assertEqual(metadata["analysis_basis"], "subtitle_or_audio_only")
        self.assertIn("仅基于字幕/音频转写", summary)

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
            segments = json.loads((out_dir / "transcript_segments.json").read_text(encoding="utf-8"))
            timed = (out_dir / "transcript_timed.txt").read_text(encoding="utf-8")
        self.assertEqual(segments[0]["start"], 12.0)
        self.assertIn("[01:05]", timed)


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
