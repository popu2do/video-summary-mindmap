from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import zipfile

import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_summary import cli as canonical_cli
from video_summary import llm as llm_module
from video_summary.outputs import final_delivery_ready
from video_summary.sources import local_source_id
from unittest import mock

from tests.support.cli import FIXTURES_DIR, assert_cli_succeeded, run_canonical_cli


SOURCE_FIXTURE = FIXTURES_DIR / "offline_document.docx"
SOURCE_ID = local_source_id(SOURCE_FIXTURE)
OFFLINE_TRANSCRIPT = (
    "这是一个离线测试文档，用于验证 transcript、摘要和脑图产物。\n"
    "第二段说明架构迁移后的 canonical CLI 应保持本地文档处理优先级。"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


class CanonicalCliContractTests(unittest.TestCase):
    def test_clean_discovery_process_can_import_src_package(self) -> None:
        """Regression: unittest discovery must not require a user-provided PYTHONPATH."""
        child_env = os.environ.copy()
        child_env.pop("PYTHONPATH", None)
        child_env["PYTHONNOUSERSITE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import tests; import video_summary; print(video_summary.__file__)",
            ],
            cwd=REPO_ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn(str(REPO_ROOT / "src"), result.stdout)

    def _assert_main_reports_stage_error(self, stage: str, patch_target: str, source: Path, *extra_args: str) -> None:
        message = f"回归测试原始原因：{stage}"
        with tempfile.TemporaryDirectory(prefix="video-summary-stage-error-") as temp_dir:
            workspace = Path(temp_dir)
            argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(workspace / "output"),
                *extra_args,
            ]
            stderr = io.StringIO()
            previous_argv = sys.argv
            try:
                sys.argv = argv
                with mock.patch.object(canonical_cli, patch_target, side_effect=RuntimeError(message)):
                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            canonical_cli.main()
            finally:
                sys.argv = previous_argv

        error = stderr.getvalue()
        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn(f"ERROR: 阶段={stage}；", error)
        self.assertIn(message, error)
        self.assertNotIn("Traceback", error)

    def test_stage_errors_keep_original_reason_without_traceback(self) -> None:
        self._assert_main_reports_stage_error("元数据", "extract_info", SOURCE_FIXTURE)

    def test_online_subtitle_and_audio_errors_are_stage_wrapped(self) -> None:
        info = {
            "id": "online-test",
            "title": "在线测试",
            "subtitles": {},
            "automatic_captions": {},
        }
        with tempfile.TemporaryDirectory(prefix="video-summary-online-stage-error-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                "https://example.test/video",
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "extract_info", return_value=info), mock.patch.object(
                    canonical_cli, "download_audio", side_effect=RuntimeError("音频获取原始原因")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("ERROR: 阶段=在线字幕与音频获取；", stderr.getvalue())
        self.assertIn("音频获取原始原因", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_document_extraction_errors_are_stage_wrapped(self) -> None:
        self._assert_main_reports_stage_error("PDF/DOCX文本提取", "extract_document_text", SOURCE_FIXTURE)

    def test_document_errors_hide_local_parent_paths_but_keep_filename_and_stage(self) -> None:
        cases = (
            ("损坏报告.pdf", "PDF 文件损坏或无法读取"),
            ("不支持格式.doc", "仅支持 OOXML 格式"),
            ("解析失败.docx", "DOC 文档 XML 解析失败"),
        )
        for filename, expected_reason in cases:
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory(prefix="video-summary-document-error-又一层-") as temp_dir:
                    workspace = Path(temp_dir)
                    source = workspace / "private" / "nested" / filename
                    source.parent.mkdir(parents=True)
                    if source.suffix == ".docx":
                        with zipfile.ZipFile(source, "w") as archive:
                            archive.writestr("word/document.xml", "<not valid")
                    else:
                        source.write_bytes(b"not a valid document")

                    previous_argv = sys.argv
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        str(source),
                        "--out-root",
                        str(workspace / "test-output"),
                    ]
                    stderr = io.StringIO()
                    try:
                        pdf_module = types.SimpleNamespace(
                            PdfReader=mock.Mock(side_effect=ValueError("损坏 PDF"))
                        )
                        import_context = (
                            mock.patch.dict(sys.modules, {"pypdf": pdf_module})
                            if source.suffix == ".pdf"
                            else contextlib.nullcontext()
                        )
                        with import_context, contextlib.redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as raised:
                                canonical_cli.main()
                    finally:
                        sys.argv = previous_argv

                    error = stderr.getvalue()
                    normalized_error = error.replace("\\", "/")
                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
                    self.assertIn(expected_reason, error)
                    self.assertIn(filename, error)
                    self.assertNotIn(str(source.parent), error)
                    self.assertNotRegex(normalized_error, r"(?i)(?:[a-z]:/|/users/)")

    def test_late_stage_failure_archives_stale_final_immediately_after_out_dir_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-late-stage-stale-final-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            (output_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            (output_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.object(
                    canonical_cli, "extract_document_text", side_effect=RuntimeError("文档提取失败")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            archive = output_dir / "_internal" / "previous_final"
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", stderr.getvalue())
            self.assertIn("文档提取失败", stderr.getvalue())
            self.assertIn("_internal/previous_final/", stderr.getvalue())
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertEqual((archive / "summary.md").read_text(encoding="utf-8"), "旧摘要\n")
            self.assertEqual((archive / "mindmap.mmd").read_text(encoding="utf-8"), "旧脑图\n")
            self.assertEqual((archive / "summary_refined.md").read_text(encoding="utf-8"), "旧兼容摘要\n")
            self.assertEqual((archive / "mindmap_refined.mmd").read_text(encoding="utf-8"), "旧兼容脑图\n")

    def test_local_transcription_artifacts_have_single_write_owner(self) -> None:
        from video_summary.artifacts import write_transcript_artifacts

        with tempfile.TemporaryDirectory(prefix="video-summary-local-transcription-artifacts-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "sample.mp3"
            source.write_bytes(b"audio placeholder")
            output_root = workspace / "output"
            info = {
                "id": "sample",
                "title": "本地音频测试",
                "uploader": "本地文件",
                "duration": None,
                "subtitles": {},
                "automatic_captions": {},
                "_local_path": str(source),
            }
            transcript = "本地转写内容足够长，用于验证转写模块是 transcript artifact 的唯一写入者。"
            segments = [{"start": 0.0, "end": 8.0, "text": "本地转写内容足够长"}]

            def transcribe_and_write(
                audio: Path, out_dir: Path, local_model: str, language: str
            ) -> str:
                write_transcript_artifacts(
                    out_dir,
                    transcript,
                    segments,
                    {
                        "engine": "test-local",
                        "model": local_model,
                        "requested_language": language,
                    },
                )
                return transcript

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(output_root),
                "--template",
                "compact",
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "extract_info", return_value=info), mock.patch.object(
                    canonical_cli, "download_audio", return_value=source
                ) as download_audio, mock.patch.object(
                    canonical_cli, "transcribe_audio", side_effect=transcribe_and_write
                ) as transcribe_audio, mock.patch.object(
                    canonical_cli, "refresh_existing_segment_artifacts"
                ) as refresh, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_dir = output_root / local_source_id(source)
            download_audio.assert_called_once()
            transcribe_audio.assert_called_once()
            refresh.assert_not_called()
            self.assertTrue((output_dir / "support" / "transcript.txt").is_file())
            self.assertTrue((output_dir / "_internal" / "transcript_segments.json").is_file())
            self.assertTrue((output_dir / "_internal" / "transcription.json").is_file())

    def test_local_transcription_errors_are_stage_wrapped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-local-transcription-error-") as temp_dir:
            audio = Path(temp_dir) / "sample.mp3"
            audio.write_bytes(b"audio placeholder")
            self._assert_main_reports_stage_error("本地转写", "transcribe_audio", audio)

    def test_output_generation_errors_are_stage_wrapped(self) -> None:
        self._assert_main_reports_stage_error("输出生成", "write_outputs", SOURCE_FIXTURE)

    def test_llm_refinement_errors_are_stage_wrapped(self) -> None:
        self._assert_main_reports_stage_error("LLM精校", "refine_with_llm", SOURCE_FIXTURE, "--llm-refine")

    def test_force_transcribe_and_reuse_transcript_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-conflicting-flags-") as temp_dir:
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--force-transcribe",
                "--reuse-transcript",
                cwd=Path(temp_dir),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: 阶段=参数校验；", result.stderr)
        self.assertIn("--force-transcribe", result.stderr)
        self.assertIn("--reuse-transcript", result.stderr)
        self.assertIn("不能同时使用", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_canonical_cli_does_not_expose_external_transcription_engine(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-transcribe-help-") as temp_dir:
            result = run_canonical_cli("--help", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        self.assertNotIn("--transcribe-engine", result.stdout)
        self.assertNotIn("Codex transcribe skill", result.stdout)

    def test_canonical_cli_help_states_draft_and_final_delivery_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-delivery-help-") as temp_dir:
            result = run_canonical_cli("--help", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        self.assertIn("默认不产生最终稿", result.stdout)
        self.assertIn("只有 --llm-refine 成功后才发布 summary.md", result.stdout)
        self.assertIn("support/transcript.txt", result.stdout)
        self.assertIn("_internal/", result.stdout)
        self.assertIn("不是最终交付", result.stdout)
        self.assertIn("refined", result.stdout)
        self.assertIn("内部草稿模板", result.stdout)
        self.assertIn("不是最终稿", result.stdout)

    def test_canonical_cli_does_not_expose_pdf_ocr_option(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-pdf-ocr-help-") as temp_dir:
            result = run_canonical_cli("--help", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        self.assertNotIn("--pdf-ocr", result.stdout)
        self.assertNotIn("Windows OCR", result.stdout)

    def test_image_only_pdf_fails_readably_without_media_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-image-pdf-unsupported-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "image-only.pdf"
            source.write_bytes(b"%PDF-image-only")
            output_root = workspace / "output"
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(output_root),
                "--template",
                "compact",
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            fake_pypdf = types.ModuleType("pypdf")

            class Page:
                def extract_text(self):
                    return ""

            class PdfReader:
                def __init__(self, path):
                    self.pages = [Page()]

            fake_pypdf.PdfReader = PdfReader
            try:
                with mock.patch.dict(sys.modules, {"pypdf": fake_pypdf}), mock.patch.object(
                    canonical_cli, "download_audio"
                ) as download_audio, mock.patch.object(canonical_cli, "transcribe_audio") as transcribe_audio, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_dir = output_root / local_source_id(source)
            error = stderr.getvalue()
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
            self.assertIn("图像型 PDF", error)
            self.assertIn("文本层", error)
            self.assertNotIn("Traceback", error)
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertFalse((output_dir / "transcript.txt").exists())
            download_audio.assert_not_called()
            transcribe_audio.assert_not_called()

    def test_legacy_openai_engine_env_does_not_break_cli_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-legacy-engine-") as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".local.env").write_text(
                "TRANSCRIBE_ENGINE=openai\n",
                encoding="utf-8",
            )
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                cwd=workspace,
            )

        assert_cli_succeeded(self, result)

    def test_transcription_api_always_uses_local_path_for_legacy_engine_env(self) -> None:
        from video_summary import transcription

        with tempfile.TemporaryDirectory(prefix="video-summary-transcribe-api-") as temp_dir:
            audio = Path(temp_dir) / "audio.mp3"
            out_dir = Path(temp_dir) / "output"
            with mock.patch.dict(os.environ, {"TRANSCRIBE_ENGINE": "openai"}), mock.patch.object(
                transcription,
                "transcribe_audio_local",
                return_value="本地转写结果",
            ) as local_transcribe:
                result = transcription.transcribe_audio(audio, out_dir, "tiny", "auto")

        self.assertEqual(result, "本地转写结果")
        local_transcribe.assert_called_once_with(audio, out_dir, "tiny", "auto")

    def test_transcription_module_has_no_external_codex_script_dependency(self) -> None:
        transcription_source = (
            Path(__file__).resolve().parents[2] / "src" / "video_summary" / "transcription.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "TRANSCRIBE_CLI",
            ".codex/skills/transcribe",
            "subprocess",
            "sys.executable",
        ):
            self.assertNotIn(forbidden, transcription_source)

    def test_canonical_cli_help_describes_supported_sources_and_output_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-help-") as temp_dir:
            result = run_canonical_cli("--help", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        for expected in (
            "Bilibili/YouTube URL",
            "本地音频/视频",
            "PDF",
            "OOXML Word",
            "PATH/<source-id>/",
            "compact",
            "refined",
            "离线",
            "LLM",
            "可选 Mermaid 脑图",
            "语义精校",
            "仅复用已有",
            "两处均缺失时直接失败",
            "transcript.txt",
            "不能与",
        ):
            self.assertIn(expected, result.stdout)

    def test_source_id_detail_stays_in_docs_while_cli_help_stays_compact(self) -> None:
        """Keep CLI help concise; README/SKILL carry the full local source-id contract."""
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-help-") as temp_dir:
            result = run_canonical_cli("--help", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        self.assertIn("PATH/<source-id>/", result.stdout)
        for document in (REPO_ROOT / "README.md", REPO_ROOT / ".agents/skill/video-summary-mindmap/SKILL.md"):
            text = document.read_text(encoding="utf-8")
            self.assertIn("--reuse-transcript", text, msg=str(document))
            self.assertIn("--force-transcribe", text, msg=str(document))
            self.assertIn("不能同时使用", text, msg=str(document))
            self.assertIn("ERROR: 阶段=", text, msg=str(document))
            self.assertIn("--out-root", text, msg=str(document))

    def test_reuse_transcript_missing_both_locations_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-missing-legacy-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--reuse-transcript", result.stderr)
            self.assertIn("support/transcript.txt", result.stderr)
            self.assertIn("旧版根层 transcript.txt", result.stderr)
            self.assertFalse((workspace / "output" / SOURCE_ID / "support" / "transcript.txt").exists())

    def test_default_output_root_is_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-default-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)

            assert_cli_succeeded(self, result)
            self.assertTrue((workspace / "output" / SOURCE_ID).is_dir())

    def test_explicit_out_root_is_used_without_falling_back_to_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-explicit-") as temp_dir:
            workspace = Path(temp_dir)
            explicit_root = workspace / "custom-artifacts"
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--out-root",
                str(explicit_root),
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertTrue((explicit_root / SOURCE_ID).is_dir())
            self.assertFalse((workspace / "output").exists())

    def test_without_llm_refine_is_draft_only_and_rejects_final_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-only-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                cwd=workspace,
            )

            output_dir = workspace / "output" / SOURCE_ID
            assert_cli_succeeded(self, result)
            message = result.stdout + result.stderr
            self.assertIn("未生成最终稿", message)
            self.assertIn("_internal/summary_draft.md", message)
            self.assertIn("_internal/mindmap_draft.mmd", message)
            self.assertIn("--llm-refine", message)
            self.assertEqual(
                (output_dir / "support" / "transcript.txt").read_text(encoding="utf-8"),
                OFFLINE_TRANSCRIPT,
            )
            self.assertTrue((output_dir / "_internal" / "summary_draft.md").read_text(encoding="utf-8").strip())
            self.assertTrue((output_dir / "_internal" / "mindmap_draft.mmd").read_text(encoding="utf-8").strip())
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())

            metadata = json.loads((output_dir / "_internal" / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("source"))
            self.assertTrue(metadata.get("title"))
            self.assertIsInstance(metadata.get("word_count"), int)

    def test_llm_refine_success_publishes_only_final_root_files(self) -> None:
        refined = "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-publish-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            (output_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), contextlib.redirect_stdout(io.StringIO()):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

            root_files = {path.name for path in output_dir.iterdir() if path.is_file()}
            nested_files = {
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file() and path.parent != output_dir
            }
            self.assertEqual(root_files, {"summary.md", "mindmap.mmd"})
            self.assertIn("_internal/summary_draft.md", nested_files)
            self.assertIn("_internal/mindmap_draft.mmd", nested_files)
            self.assertEqual(
                (output_dir / "summary.md").read_text(encoding="utf-8").strip(),
                "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```",
            )
            self.assertIn("root((主题))", (output_dir / "mindmap.mmd").read_text(encoding="utf-8"))
            self.assertFalse((output_dir / "summary_refined.md").exists())
            self.assertFalse((output_dir / "mindmap_refined.mmd").exists())
            self.assertFalse((output_dir / "_internal" / "previous_final").exists())

    def test_final_delivery_rejects_unknown_root_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-root-directory-contract-") as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "summary.md").write_text("# valid final summary\n", encoding="utf-8")
            (out_dir / "support").mkdir()
            (out_dir / "_internal").mkdir()
            (out_dir / "unexpected").mkdir()

            self.assertFalse(final_delivery_ready(out_dir))

    def test_successful_publish_keeps_only_allowed_root_delivery_files(self) -> None:
        cases = (
            (
                "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```",
                {"summary.md", "mindmap.mmd"},
            ),
            ("# 只有正文的最终摘要\n\n这里没有 Mermaid 脑图。", {"summary.md"}),
        )
        for refined, expected_root_files in cases:
            with self.subTest(expected_root_files=expected_root_files):
                with tempfile.TemporaryDirectory(prefix="video-summary-root-delivery-contract-") as temp_dir:
                    workspace = Path(temp_dir)
                    source = workspace / "unreadable.docx"
                    output_root = workspace / "output"
                    output_dir = output_root / local_source_id(source)
                    output_dir.mkdir(parents=True)
                    (output_dir / "transcript.txt").write_text("旧根层 transcript，足够长的复用文本用于成功发布契约验证。\n", encoding="utf-8")
                    (output_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
                    (output_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
                    (output_dir / "mindmap.mmd").write_text("旧最终脑图\n", encoding="utf-8")
                    (output_dir / "unexpected.txt").write_text("未知残留\n", encoding="utf-8")

                    previous_argv = sys.argv
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        str(source),
                        "--template",
                        "compact",
                        "--reuse-transcript",
                        "--llm-refine",
                        "--out-root",
                        str(output_root),
                    ]
                    try:
                        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                            llm_module, "call_llm", return_value=refined
                        ), contextlib.redirect_stdout(io.StringIO()):
                            canonical_cli.main()
                    finally:
                        sys.argv = previous_argv

                    root_files = {path.name for path in output_dir.iterdir() if path.is_file()}
                    self.assertEqual(root_files, expected_root_files)
                    self.assertTrue((output_dir / "support" / "transcript.txt").is_file())
                    self.assertFalse((output_dir / "summary_refined.md").exists())
                    self.assertFalse((output_dir / "mindmap_refined.mmd").exists())
                    self.assertFalse((output_dir / "transcript.txt").exists())
                    self.assertFalse((output_dir / "unexpected.txt").exists())
                    if expected_root_files == {"summary.md"}:
                        self.assertFalse((output_dir / "mindmap.mmd").exists())
                    else:
                        self.assertTrue((output_dir / "mindmap.mmd").is_file())

    def test_new_run_moves_legacy_root_subtitles_under_internal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-new-run-subtitle-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            legacy_subtitle = output_dir / "subtitle.zh-Hans.vtt"
            legacy_subtitle.write_text("WEBVTT\n\n旧字幕\n", encoding="utf-8")

            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=workspace)

            assert_cli_succeeded(self, result)
            self.assertFalse(legacy_subtitle.exists())
            self.assertEqual(
                (output_dir / "_internal" / "subtitle.zh-Hans.vtt").read_text(encoding="utf-8"),
                "WEBVTT\n\n旧字幕\n",
            )
            root_subtitles = [path.name for path in output_dir.glob("subtitle.*") if path.is_file()]
            self.assertEqual(root_subtitles, [])

    def test_draft_only_rerun_hides_stale_final_files_in_previous_final_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-stale-final-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("上次最终摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("mindmap\n  root((上次最终脑图))\n", encoding="utf-8")

            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=workspace)

            assert_cli_succeeded(self, result)
            message = result.stdout + result.stderr
            archive = output_dir / "_internal" / "previous_final"
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertEqual((archive / "summary.md").read_text(encoding="utf-8"), "上次最终摘要\n")
            self.assertEqual((archive / "mindmap.mmd").read_text(encoding="utf-8"), "mindmap\n  root((上次最终脑图))\n")
            self.assertIn("_internal/previous_final/", message)
            self.assertIn("旧最终稿", message)
            self.assertIn("transcript.txt", message)

    def test_llm_refine_failure_hides_stale_final_files_and_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-failure-stale-final-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("上次最终摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("mindmap\n  root((上次最终脑图))\n", encoding="utf-8")
            (output_dir / "summary_refined.md").write_text("上次兼容摘要\n", encoding="utf-8")
            (output_dir / "mindmap_refined.mmd").write_text("mindmap\n  root((上次兼容脑图))\n", encoding="utf-8")

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", side_effect=RuntimeError("LLM 请求失败")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_dir = workspace / "output" / SOURCE_ID
            archive = output_dir / "_internal" / "previous_final"
            self.assertNotEqual(raised.exception.code, 0)
            error = stderr.getvalue()
            self.assertIn("ERROR: 阶段=LLM精校；", error)
            self.assertIn("LLM 请求失败", error)
            self.assertIn("_internal/previous_final/", error)
            self.assertIn("旧最终稿", error)
            self.assertNotIn("Traceback", error)
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertEqual((archive / "summary.md").read_text(encoding="utf-8"), "上次最终摘要\n")
            self.assertEqual((archive / "mindmap.mmd").read_text(encoding="utf-8"), "mindmap\n  root((上次最终脑图))\n")
            self.assertEqual((archive / "summary_refined.md").read_text(encoding="utf-8"), "上次兼容摘要\n")
            self.assertEqual((archive / "mindmap_refined.mmd").read_text(encoding="utf-8"), "mindmap\n  root((上次兼容脑图))\n")

    def test_llm_failure_reports_legacy_archived_finals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-failure-legacy-archive-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary_refined.md").write_text("上次兼容摘要\n", encoding="utf-8")
            (output_dir / "mindmap_refined.mmd").write_text("上次兼容脑图\n", encoding="utf-8")

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", side_effect=RuntimeError("LLM 请求失败")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            error = stderr.getvalue()
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=LLM精校；", error)
            self.assertIn("LLM 请求失败", error)
            self.assertIn("_internal/previous_final/", error)
            self.assertIn("旧最终稿", error)
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())

    def test_llm_refine_publishes_summary_without_mindmap(self) -> None:
        refined = "# 只有正文的最终摘要\n\n这里没有 Mermaid 脑图。"
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-summary-only-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stdout = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), contextlib.redirect_stdout(stdout):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_contract = stdout.getvalue().splitlines()
            self.assertIn("核心交付：", output_contract)
            self.assertIn("- summary.md", output_contract)
            self.assertNotIn("- mindmap.mmd", output_contract)

            output_dir = workspace / "output" / SOURCE_ID
            self.assertEqual((output_dir / "summary.md").read_text(encoding="utf-8"), refined + "\n")
            self.assertFalse((output_dir / "mindmap.mmd").exists())

    def test_llm_refine_summary_only_explains_mindmap_not_generated(self) -> None:
        refined = "# 只有正文的最终摘要\n\n这里没有 Mermaid 脑图。"
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-summary-only-message-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stdout = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), contextlib.redirect_stdout(stdout):
                    result = canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_dir = workspace / "output" / SOURCE_ID
            self.assertIsNone(result)
            self.assertTrue((output_dir / "summary.md").is_file())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertIn(
                "脑图：未生成（LLM 未返回有效 Mermaid，按需生成）",
                stdout.getvalue(),
            )

    def test_unreadable_pdf_reports_human_stage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-unreadable-pdf-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "broken.pdf"
            source.write_bytes(b"not a readable pdf")
            fake_pypdf = types.ModuleType("pypdf")

            class PdfReader:
                def __init__(self, path: str) -> None:
                    raise ValueError("xref table not found")

            fake_pypdf.PdfReader = PdfReader
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(sys.modules, {"pypdf": fake_pypdf}), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            error = stderr.getvalue()
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
            self.assertIn("PDF 文件损坏或无法读取", error)
            self.assertNotIn("xref table not found", error)

    def test_empty_pdf_reports_document_text_too_short(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-empty-pdf-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "empty.pdf"
            source.write_bytes(b"%PDF-empty")
            fake_pypdf = types.ModuleType("pypdf")

            class Page:
                def extract_text(self) -> str:
                    return ""

            class PdfReader:
                def __init__(self, path: str) -> None:
                    self.pages = [Page()]

            fake_pypdf.PdfReader = PdfReader
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(sys.modules, {"pypdf": fake_pypdf}), mock.patch.object(
                    canonical_cli, "download_audio", return_value=workspace / "audio.mp3"
                ), mock.patch.object(canonical_cli, "transcribe_audio", return_value=""), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            error = stderr.getvalue()
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
            self.assertIn("图像型 PDF", error)
            self.assertIn("文本层", error)
            self.assertNotIn("转写文本过短", error)

    def test_empty_docx_reports_document_text_too_short(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-empty-docx-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "empty.docx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                    "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                    "<w:body></w:body></w:document>",
                )

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.object(
                    canonical_cli, "download_audio", return_value=workspace / "audio.mp3"
                ), mock.patch.object(canonical_cli, "transcribe_audio", return_value=""), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            error = stderr.getvalue()
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
            self.assertIn("文档文本为空或过短", error)
            self.assertNotIn("转写文本过短", error)

    def test_empty_documents_short_circuit_before_audio_or_transcription(self) -> None:
        for suffix in (".pdf", ".docx"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory(
                prefix=f"video-summary-empty-document-short-circuit-{suffix[1:]}-"
            ) as temp_dir:
                workspace = Path(temp_dir)
                source = workspace / f"empty{suffix}"
                fake_pypdf = None
                if suffix == ".pdf":
                    source.write_bytes(b"%PDF-empty")
                    fake_pypdf = types.ModuleType("pypdf")

                    class Page:
                        def extract_text(self) -> str:
                            return ""

                    class PdfReader:
                        def __init__(self, path: str) -> None:
                            self.pages = [Page()]

                    fake_pypdf.PdfReader = PdfReader
                else:
                    with zipfile.ZipFile(source, "w") as archive:
                        archive.writestr(
                            "word/document.xml",
                            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                            "<w:body></w:body></w:document>",
                        )

                previous_argv = sys.argv
                sys.argv = [
                    str(REPO_ROOT / "src" / "video_summary_cli.py"),
                    str(source),
                    "--out-root",
                    str(workspace / "output"),
                ]
                stderr = io.StringIO()
                try:
                    document_module = (
                        mock.patch.dict(sys.modules, {"pypdf": fake_pypdf})
                        if fake_pypdf is not None
                        else contextlib.nullcontext()
                    )
                    with document_module, mock.patch.object(
                        canonical_cli, "download_audio", return_value=workspace / "audio.mp3"
                    ) as download_audio, mock.patch.object(
                        canonical_cli, "transcribe_audio", return_value=""
                    ) as transcribe_audio, contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            canonical_cli.main()
                finally:
                    sys.argv = previous_argv

                error = stderr.getvalue()
                self.assertNotEqual(raised.exception.code, 0)
                self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", error)
                if suffix == ".pdf":
                    self.assertIn("图像型 PDF", error)
                    self.assertIn("文本层", error)
                else:
                    self.assertIn("文档文本为空或过短，无法生成摘要", error)
                self.assertNotIn("阶段=在线字幕与音频获取", error)
                self.assertNotIn("阶段=本地转写", error)
                download_audio.assert_not_called()
                transcribe_audio.assert_not_called()

    def test_draft_only_files_stay_under_internal_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-files-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)

            output_dir = workspace / "output" / SOURCE_ID
            root_files = {path.name for path in output_dir.iterdir() if path.is_file()}
            nested_files = {
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file() and path.parent != output_dir
            }

        assert_cli_succeeded(self, result)
        self.assertEqual(root_files, set(), msg=f"root files: {sorted(root_files)}")
        self.assertTrue(nested_files, msg="internal artifacts were not written under _internal/")
        self.assertTrue(
            all(relative_path.startswith(("_internal/", "support/")) for relative_path in nested_files),
            msg=f"unexpected files: {sorted(nested_files)}",
        )
        self.assertIn("_internal/metadata.json", nested_files)
        self.assertIn("_internal/summary_draft.md", nested_files)
        self.assertIn("_internal/mindmap_draft.mmd", nested_files)

    def test_draft_only_message_explains_final_publication_requirement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-output-roles-") as temp_dir:
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        message = result.stdout + result.stderr
        self.assertIn("未生成最终稿", message)
        self.assertIn("_internal/summary_draft.md", message)
        self.assertIn("_internal/mindmap_draft.mmd", message)
        self.assertIn("--llm-refine", message)

    def test_same_stem_local_sources_use_distinct_reusable_output_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            sources = [
                workspace / "same-name.pdf",
                workspace / "same-name.docx",
                workspace / "same-name.mp4",
            ]
            source_ids = {source: local_source_id(source) for source in sources}
            expected_ids = set(source_ids.values())

            for source, source_id in source_ids.items():
                source.write_bytes(b"not a valid source")
                output_dir = output_root / source_id
                output_dir.mkdir(parents=True)
                (output_dir / "transcript.txt").write_text(
                    f"这是 {source.suffix} 的预置逐字稿，用于验证 source-id 隔离。",
                    encoding="utf-8",
                )

            for source in sources:
                result = run_canonical_cli(
                    str(source),
                    "--out-root",
                    str(output_root),
                    "--reuse-transcript",
                    "--template",
                    "compact",
                    cwd=workspace,
                )
                assert_cli_succeeded(self, result)

            self.assertEqual(
                {path.name for path in output_root.iterdir() if path.is_dir()},
                expected_ids,
            )
            for source_id in expected_ids:
                output_dir = output_root / source_id
                self.assertTrue((output_dir / "_internal" / "summary_draft.md").exists())
                self.assertTrue((output_dir / "_internal" / "mindmap_draft.mmd").exists())
                self.assertFalse((output_dir / "summary.md").exists())
                self.assertFalse((output_dir / "mindmap.mmd").exists())

    def test_same_stem_and_extension_local_sources_use_distinct_reusable_output_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-collision-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            sources = [
                workspace / "left" / "same-name.docx",
                workspace / "right" / "same-name.docx",
            ]
            source_ids = {source: local_source_id(source) for source in sources}

            for source, source_id in source_ids.items():
                source.parent.mkdir(parents=True)
                source.write_bytes(b"not a valid source")
                output_dir = output_root / source_id
                output_dir.mkdir(parents=True)
                (output_dir / "transcript.txt").write_text(
                    f"这是 {source.parent.name} 目录中的预置逐字稿，用于验证同名同扩展隔离。",
                    encoding="utf-8",
                )

            for source in sources:
                result = run_canonical_cli(
                    str(source),
                    "--out-root",
                    str(output_root),
                    "--reuse-transcript",
                    "--template",
                    "compact",
                    cwd=workspace,
                )
                assert_cli_succeeded(self, result)

            self.assertEqual(
                {path.name for path in output_root.iterdir() if path.is_dir()},
                set(source_ids.values()),
            )
            self.assertNotEqual(*source_ids.values())
            for source_id in source_ids.values():
                output_dir = output_root / source_id
                self.assertTrue((output_dir / "_internal" / "summary_draft.md").exists())
                self.assertTrue((output_dir / "_internal" / "mindmap_draft.mmd").exists())
                self.assertFalse((output_dir / "summary.md").exists())
                self.assertFalse((output_dir / "mindmap.mmd").exists())

    def test_reuse_run_moves_legacy_root_subtitles_under_internal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-subtitle-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "unreadable.docx"
            source.write_bytes(b"not an OOXML document")
            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            output_dir.mkdir(parents=True)
            (output_dir / "transcript.txt").write_text("复用逐字稿内容足够长，用于验证旧根级字幕会迁移到内部目录。", encoding="utf-8")
            legacy_subtitle = output_dir / "subtitle.zh-Hans.vtt"
            legacy_subtitle.write_text("WEBVTT\n\n复用旧字幕\n", encoding="utf-8")

            result = run_canonical_cli(
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertFalse(legacy_subtitle.exists())
            self.assertEqual(
                (output_dir / "_internal" / "subtitle.zh-Hans.vtt").read_text(encoding="utf-8"),
                "WEBVTT\n\n复用旧字幕\n",
            )
            root_subtitles = [path.name for path in output_dir.glob("subtitle.*") if path.is_file()]
            self.assertEqual(root_subtitles, [])

    def test_reuse_transcript_rebuilds_segments_from_current_text_for_chapters_and_llm(self) -> None:
        old_segment_text = "旧分段内容：不应出现在本轮章节或 LLM 提示中。"
        current_transcript = (
            "[00:00] 新文本第一段：本轮 transcript 才是复用模式的唯一事实来源。\n"
            "[00:10] 新文本第二段：章节和 LLM 提示必须使用当前文本。\n"
        )
        expected_segment_texts = [
            "新文本第一段：本轮 transcript 才是复用模式的唯一事实来源。",
            "新文本第二段：章节和 LLM 提示必须使用当前文本。",
        ]

        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-refresh-derived-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "unreadable.docx"
            source.write_bytes(b"not an OOXML document")
            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            internal_dir = output_dir / "_internal"
            internal_dir.mkdir(parents=True)
            (output_dir / "transcript.txt").write_text(current_transcript, encoding="utf-8")
            (internal_dir / "transcript_segments.json").write_text(
                json.dumps(
                    [{"start": 0.0, "end": 8.0, "text": old_segment_text}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            prompts: list[str] = []

            def fake_call_llm(prompt: str, model: str, api_kind: str) -> str:
                prompts.append(prompt)
                if "Chunk transcript:" in prompt:
                    return "# 分段精校结果\n\n分段摘要正文。"
                return "# 最终精修稿\n\n最终摘要正文。"

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                "--content-type",
                "lecture",
                "--llm-refine",
                "--llm-max-chars",
                "60",
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", side_effect=fake_call_llm
                ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

            segments = json.loads(
                (internal_dir / "transcript_segments.json").read_text(encoding="utf-8")
            )
            timed_transcript = (internal_dir / "transcript_timed.txt").read_text(encoding="utf-8")
            draft_summary = (internal_dir / "summary_draft.md").read_text(encoding="utf-8")

            self.assertEqual([item["text"] for item in segments], expected_segment_texts)
            self.assertIn("新文本第一段", timed_transcript)
            self.assertIn("新文本第二段", timed_transcript)
            self.assertNotIn(old_segment_text, timed_transcript)
            self.assertNotIn(old_segment_text, draft_summary)
            self.assertTrue(prompts)
            self.assertTrue(any("新文本第一段" in prompt for prompt in prompts))
            self.assertTrue(all(old_segment_text not in prompt for prompt in prompts))

    def test_reuse_transcript_rejects_any_url_scheme_before_output_or_network_access(self) -> None:
        url_sources = (
            "ftp://example.test/video",
            "file:///private/video.mp4",
            "gopher://example.test/video",
            "custom:video-resource",
        )
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-url-schemes-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            for source in url_sources:
                with self.subTest(source=source):
                    previous_argv = sys.argv
                    stderr = io.StringIO()
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        source,
                        "--out-root",
                        str(output_root),
                        "--reuse-transcript",
                    ]
                    try:
                        with mock.patch.object(
                            canonical_cli,
                            "source_id_without_access",
                            side_effect=AssertionError("source-id accessed"),
                        ), mock.patch.object(
                            canonical_cli,
                            "extract_info",
                            side_effect=AssertionError("network accessed"),
                        ), contextlib.redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as raised:
                                canonical_cli.main()
                    finally:
                        sys.argv = previous_argv

                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("ERROR: 阶段=输出准备；", stderr.getvalue())
                    self.assertIn("--reuse-transcript 仅支持本地文件", stderr.getvalue())
                    self.assertNotIn("source-id accessed", stderr.getvalue())
                    self.assertNotIn("network accessed", stderr.getvalue())
                    self.assertFalse(output_root.exists())

    def test_reuse_transcript_rejects_online_url_before_output_or_network_access(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-online-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            previous_argv = sys.argv
            stderr = io.StringIO()
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                "https://example.test/video",
                "--out-root",
                str(output_root),
                "--reuse-transcript",
            ]
            try:
                with mock.patch.object(canonical_cli, "source_id_without_access", side_effect=AssertionError("source-id accessed")), mock.patch.object(
                    canonical_cli, "extract_info", side_effect=AssertionError("network accessed")
                ), mock.patch.object(
                    canonical_cli, "download_audio", side_effect=AssertionError("network accessed")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=输出准备；", stderr.getvalue())
            self.assertIn("--reuse-transcript 仅支持本地文件", stderr.getvalue())
            self.assertNotIn("source-id accessed", stderr.getvalue())
            self.assertNotIn("network accessed", stderr.getvalue())
            self.assertFalse(output_root.exists())


    def test_reuse_transcript_does_not_read_the_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "unreadable.docx"
            source.write_bytes(b"not an OOXML document")

            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            output_dir.mkdir(parents=True)
            transcript = "这是预先存在的离线逐字稿，用于验证复用模式不读取源文件。"
            (output_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

            result = run_canonical_cli(
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertEqual(
                (output_dir / "support" / "transcript.txt").read_text(encoding="utf-8"),
                transcript,
            )
            self.assertTrue((output_dir / "_internal" / "summary_draft.md").exists())
            self.assertTrue((output_dir / "_internal" / "mindmap_draft.mmd").exists())
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())


    def test_llm_success_stdout_names_final_summary_and_mindmap(self) -> None:
        refined = "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"
        with tempfile.TemporaryDirectory(prefix="video-summary-stdout-final-names-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stdout = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), contextlib.redirect_stdout(stdout):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

        lines = stdout.getvalue().splitlines()
        self.assertIn("最终稿：summary.md", lines)
        self.assertIn("脑图：mindmap.mmd", lines)

    def test_llm_summary_only_stdout_names_final_summary_and_missing_mindmap(self) -> None:
        refined = "# 只有正文的最终摘要\n\n这里没有 Mermaid 脑图。"
        with tempfile.TemporaryDirectory(prefix="video-summary-stdout-summary-only-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stdout = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), contextlib.redirect_stdout(stdout):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

        message = stdout.getvalue()
        self.assertIn("最终稿：summary.md", message)
        self.assertIn("脑图：未生成（LLM 未返回有效 Mermaid，按需生成）", message)

    def test_no_llm_stdout_marks_transcript_and_internal_files_as_non_final(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-stdout-draft-only-contract-") as temp_dir:
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        message = result.stdout + result.stderr
        self.assertIn("最终稿：未生成", message)
        self.assertIn("support/transcript.txt：依据材料，不是最终稿", message)
        self.assertIn("_internal/summary_draft.md：内部草稿，不是最终稿", message)
        self.assertIn("_internal/mindmap_draft.mmd：内部草稿，不是最终稿", message)
        self.assertIn("_internal/*：内部状态（草稿/缓存/元数据），全部不是最终稿", message)

    def test_llm_failure_error_marks_transcript_and_internal_files_as_non_final(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-stderr-failure-contract-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", side_effect=RuntimeError("LLM 请求失败")
                ), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

        self.assertNotEqual(raised.exception.code, 0)
        error = stderr.getvalue()
        self.assertIn("最终稿：未生成", error)
        self.assertIn("support/transcript.txt：依据材料，不是最终稿", error)
        self.assertIn("_internal/summary_draft.md：内部草稿，不是最终稿", error)
        self.assertIn("_internal/mindmap_draft.mmd：内部草稿，不是最终稿", error)
        self.assertIn("_internal/*：内部状态（草稿/缓存/元数据），全部不是最终稿", error)

    def test_post_publish_archive_cleanup_failure_is_warning_after_final_publish(self) -> None:
        refined = "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```"
        with tempfile.TemporaryDirectory(prefix="video-summary-post-publish-cleanup-failure-") as temp_dir:
            workspace = Path(temp_dir)
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                "--llm-refine",
                "--out-root",
                str(workspace / "output"),
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
                    llm_module, "call_llm", return_value=refined
                ), mock.patch.object(
                    llm_module,
                    "clear_previous_final_outputs",
                    side_effect=OSError("模拟归档清理失败"),
                ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = canonical_cli.main()
            finally:
                sys.argv = previous_argv

            output_dir = workspace / "output" / SOURCE_ID
            self.assertIsNone(result)
            self.assertTrue((output_dir / "summary.md").is_file())
            self.assertTrue((output_dir / "mindmap.mmd").is_file())

        message = stdout.getvalue() + stderr.getvalue()
        self.assertIn("最终稿已发布但后续归档清理失败", message)
        self.assertIn("summary.md", message)
        self.assertNotIn("本次未生成最终稿", message)


    def test_new_document_run_removes_stale_reusable_transcript_before_early_failure(self) -> None:
        for extension in (".pdf", ".docx"):
            with self.subTest(extension=extension):
                with tempfile.TemporaryDirectory(
                    prefix=f"video-summary-stale-transcript-{extension[1:]}-"
                ) as temp_dir:
                    workspace = Path(temp_dir)
                    source = workspace / f"broken{extension}"
                    source.write_bytes(b"broken document")
                    output_root = workspace / "artifacts"
                    output_dir = output_root / local_source_id(source)
                    output_dir.mkdir(parents=True)
                    (output_dir / "transcript.txt").write_text(
                        "上一轮旧 transcript，不得在本轮早期失败后继续可复用。",
                        encoding="utf-8",
                    )
                    for filename in (
                        "summary_draft.md",
                        "mindmap_draft.mmd",
                        "metadata.json",
                        "transcript_segments.json",
                        "transcript_timed.txt",
                        "summary_chunks.json",
                        "transcription.json",
                        "audio.mp3",
                    ):
                        target = output_dir / filename
                        if target.suffix == ".mp3":
                            target.write_bytes(b"stale audio")
                        else:
                            target.write_text(f"旧内部状态：{filename}\n", encoding="utf-8")

                    previous_argv = sys.argv
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        str(source),
                        "--out-root",
                        str(output_root),
                    ]
                    stderr = io.StringIO()
                    try:
                        with mock.patch.object(
                            canonical_cli, "extract_document_text", return_value="太短"
                        ) as extract:
                            with mock.patch.object(canonical_cli, "download_audio") as download_audio:
                                with mock.patch.object(canonical_cli, "transcribe_audio") as transcribe_audio:
                                    with contextlib.redirect_stderr(stderr):
                                        with self.assertRaises(SystemExit) as raised:
                                            canonical_cli.main()
                    finally:
                        sys.argv = previous_argv

                    root_files = {path.name for path in output_dir.iterdir() if path.is_file()}
                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", stderr.getvalue())
                    self.assertEqual(root_files, set(), msg=f"stale root files: {sorted(root_files)}")
                    self.assertFalse((output_dir / "transcript.txt").exists())
                    extract.assert_called_once()
                    download_audio.assert_not_called()
                    transcribe_audio.assert_not_called()

    def test_early_document_short_failure_cleans_legacy_root_intermediates(self) -> None:
        intermediate_files = (
            "metadata.json",
            "transcription.json",
            "transcript_segments.json",
            "transcript_timed.txt",
            "summary_chunks.json",
            "audio.mp3",
        )
        with tempfile.TemporaryDirectory(prefix="video-summary-early-document-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            for filename in intermediate_files:
                path = output_dir / filename
                if path.suffix == ".mp3":
                    path.write_bytes(b"legacy audio")
                else:
                    path.write_text(f"legacy {filename}\n", encoding="utf-8")
            (output_dir / "summary.md").write_text("旧最终摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧最终脑图\n", encoding="utf-8")

            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(SOURCE_FIXTURE),
                "--out-root",
                str(workspace / "output"),
            ]
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "extract_document_text", return_value="太短"), mock.patch.object(
                    canonical_cli, "download_audio", return_value=workspace / "audio.mp3"
                ) as download_audio, mock.patch.object(
                    canonical_cli, "transcribe_audio", return_value="足够长的转写文本"
                ) as transcribe_audio, contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            archive = output_dir / "_internal" / "previous_final"
            root_files = {path.name for path in output_dir.iterdir() if path.is_file()}
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", stderr.getvalue())
            self.assertIn("文档文本为空或过短，无法生成摘要", stderr.getvalue())
            self.assertEqual(root_files, set(), msg=f"legacy root files: {sorted(root_files)}")
            for filename in intermediate_files:
                self.assertFalse((output_dir / filename).exists())
            self.assertFalse((output_dir / "summary.md").exists())
            self.assertFalse((output_dir / "mindmap.mmd").exists())
            self.assertEqual((archive / "summary.md").read_text(encoding="utf-8"), "旧最终摘要\n")
            self.assertEqual((archive / "mindmap.mmd").read_text(encoding="utf-8"), "旧最终脑图\n")
            download_audio.assert_not_called()
            transcribe_audio.assert_not_called()


    def test_reuse_missing_both_transcript_locations_fails_before_source_access(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-missing-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "not-readable.docx"
            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            output_dir.mkdir(parents=True)

            previous_argv = sys.argv
            stderr = io.StringIO()
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
            ]
            try:
                with mock.patch.object(canonical_cli, "extract_info", side_effect=AssertionError("source accessed")):
                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            canonical_cli.main()
            finally:
                sys.argv = previous_argv

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("--reuse-transcript", stderr.getvalue())
            self.assertIn("support/transcript.txt", stderr.getvalue())
            self.assertNotIn("source accessed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
