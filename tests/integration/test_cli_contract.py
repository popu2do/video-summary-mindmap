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

from tests.support.cli import FIXTURES_DIR, assert_cli_succeeded, run_canonical_cli, temporary_test_directory


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

    def test_late_stage_failure_preserves_existing_delivery_and_does_not_archive_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-late-stage-stale-final-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            (output_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            (output_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(SOURCE_FIXTURE), "--out-root", str(workspace / "output")]
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "extract_document_text", side_effect=RuntimeError("文档提取失败")), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", stderr.getvalue())
            self.assertIn("文档提取失败", stderr.getvalue())
            self.assertEqual((output_dir / "summary.md").read_text(encoding="utf-8"), "旧摘要\n")
            self.assertEqual((output_dir / "mindmap.mmd").read_text(encoding="utf-8"), "旧脑图\n")
            self.assertEqual((output_dir / "notes.txt").read_text(encoding="utf-8"), "用户文件\n")
            self.assertFalse((output_dir / "summary_refined.md").exists())
            self.assertFalse((output_dir / "_internal" / "previous_final").exists())

    def test_local_transcription_artifacts_are_written_in_the_run_workspace(self) -> None:
        from video_summary.artifacts import write_transcript_artifacts

        with tempfile.TemporaryDirectory(prefix="video-summary-local-transcription-artifacts-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "sample.mp3"
            source.write_bytes(b"audio placeholder")
            output_root = workspace / "output"
            transcript = "本地转写内容足够长，用于验证转写产物只属于本次运行工作区。"
            artifact_dirs: list[Path] = []

            def transcribe_and_write(audio: Path, run_dir: Path, local_model: str, language: str) -> str:
                artifact_dirs.append(run_dir)
                write_transcript_artifacts(run_dir, transcript, [{"start": 0.0, "end": 8.0, "text": transcript}], {"engine": "test-local"})
                return transcript

            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(source), "--out-root", str(output_root), "--template", "compact"]
            try:
                with mock.patch.object(canonical_cli, "load_local_env"), mock.patch.object(canonical_cli, "load_domain_config"), mock.patch.object(canonical_cli, "transcribe_audio", side_effect=transcribe_and_write), mock.patch.object(canonical_cli, "download_audio", return_value=source), mock.patch.object(canonical_cli, "choose_subtitle", return_value=None), contextlib.redirect_stdout(io.StringIO()):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv

            self.assertEqual(len(artifact_dirs), 1)
            self.assertNotEqual(artifact_dirs[0].parent, output_root)
            self.assertTrue(output_root.is_dir())
            self.assertEqual(list(output_root.iterdir()), [])

    def test_local_transcription_failure_leaves_no_retired_transcription_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-local-transcription-failure-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "sample.mp3"
            source.write_bytes(b"audio placeholder")
            output_root = workspace / "output"
            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(source), "--out-root", str(output_root)]
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "download_audio", return_value=source), mock.patch.object(canonical_cli, "choose_subtitle", return_value=None), mock.patch.object(canonical_cli, "transcribe_audio", side_effect=RuntimeError("本地转写失败")), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("ERROR: 阶段=本地转写；", stderr.getvalue())
            self.assertIn("本地转写失败", stderr.getvalue())
            self.assertTrue(output_root.is_dir())
            self.assertEqual(list(output_root.iterdir()), [])

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
        result = run_canonical_cli("-h", cwd=Path(tempfile.mkdtemp(prefix="video-summary-help-")))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        help_text = result.stdout
        self.assertIn("只有 --llm-refine 成功后才发布 summary.md", help_text)
        self.assertIn("只写入临时工作区", help_text)
        self.assertIn("PATH/<source-id>/", help_text)
        self.assertIn("summary.md", help_text)
        self.assertIn("mindmap.mmd", help_text)

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
            "复用用户显式提供的本地转写 PATH",
            "不能与",
        ):
            self.assertIn(expected, result.stdout)
        self.assertIn("--reuse-transcript PATH", result.stdout)
        self.assertNotIn("未提供 PATH", result.stdout)
        self.assertNotIn("support/transcript", result.stdout)

    def test_source_id_is_path_derived_and_cli_help_names_the_output_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-help-") as temp_dir:
            workspace = Path(temp_dir)
            left = workspace / "left" / "same-name.docx"
            right = workspace / "right" / "same-name.docx"
            left.parent.mkdir()
            right.parent.mkdir()
            left.write_bytes(b"left")
            right.write_bytes(b"right")
            self.assertNotEqual(local_source_id(left), local_source_id(right))
            result = run_canonical_cli("-h", cwd=workspace)
        self.assertEqual(result.returncode, 0)
        self.assertIn("PATH/<source-id>/", result.stdout)
        self.assertNotIn("previous_final", result.stdout)

    def test_reuse_transcript_requires_explicit_path_during_argument_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-missing-legacy-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            (output_dir / "support").mkdir(parents=True)
            support_transcript = output_dir / "support" / "transcript.txt"
            root_transcript = output_dir / "transcript.txt"
            support_transcript.write_text("持久化 support 转写，不得被隐式复用。", encoding="utf-8")
            root_transcript.write_text("持久化根层转写，不得被隐式复用。", encoding="utf-8")

            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR: 阶段=参数校验；", result.stderr)
            self.assertIn("--reuse-transcript 必须显式提供本地转写文件路径", result.stderr)
            self.assertNotIn("阶段=输出准备", result.stderr)
            self.assertNotIn("support/transcript", result.stderr)
            self.assertEqual(support_transcript.read_text(encoding="utf-8"), "持久化 support 转写，不得被隐式复用。")
            self.assertEqual(root_transcript.read_text(encoding="utf-8"), "持久化根层转写，不得被隐式复用。")

    def test_default_output_root_is_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-default-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)
            assert_cli_succeeded(self, result)
            output_root = workspace / "output"
            self.assertTrue(output_root.is_dir())
            self.assertEqual(list(output_root.iterdir()), [])
            self.assertIn(str(output_root / SOURCE_ID), result.stdout)

    def test_explicit_out_root_is_used_without_falling_back_to_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-explicit-") as temp_dir:
            workspace = Path(temp_dir)
            explicit_root = workspace / "custom-artifacts"
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--out-root", str(explicit_root), cwd=workspace)
            assert_cli_succeeded(self, result)
            self.assertTrue(explicit_root.is_dir())
            self.assertEqual(list(explicit_root.iterdir()), [])
            self.assertFalse((workspace / "output").exists())

    def test_without_llm_refine_is_draft_only_and_rejects_final_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-only-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=workspace)
            assert_cli_succeeded(self, result)
            message = result.stdout + result.stderr
            output_dir = workspace / "output" / SOURCE_ID
            self.assertIn("未生成最终稿", message)
            self.assertIn("临时转写、分段数据和内部草稿：已清理", message)
            self.assertIn("--llm-refine", message)
            self.assertFalse(output_dir.exists())
            self.assertTrue((workspace / "output").is_dir())

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
            self.assertEqual(nested_files, set())
            self.assertFalse((output_dir / "support").exists())
            self.assertFalse((output_dir / "_internal").exists())
            self.assertEqual(
                (output_dir / "summary.md").read_text(encoding="utf-8").strip(),
                "# 精校摘要\n\n这里是一行最小实质摘要正文。\n\n```mermaid\nmindmap\n  root((主题))\n```",
            )
            self.assertIn("root((主题))", (output_dir / "mindmap.mmd").read_text(encoding="utf-8"))
            self.assertFalse((output_dir / "summary_refined.md").exists())
            self.assertFalse((output_dir / "mindmap_refined.mmd").exists())
            self.assertFalse((output_dir / "_internal" / "previous_final").exists())

    def test_final_delivery_preserves_unknown_root_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-unknown-root-") as temp_dir:
            out_dir = Path(temp_dir)
            unknown_dir = out_dir / "user-material"
            unknown_dir.mkdir(parents=True)
            (unknown_dir / "notes.txt").write_text("用户内容\n", encoding="utf-8")
            self.assertFalse(final_delivery_ready(out_dir))
            (out_dir / "summary.md").write_text("# 摘要\n", encoding="utf-8")
            self.assertTrue(final_delivery_ready(out_dir))
            self.assertEqual((unknown_dir / "notes.txt").read_text(encoding="utf-8"), "用户内容\n")

    def test_successful_publish_exposes_only_final_files_and_preserves_unknown_user_files(self) -> None:
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
                    reuse_transcript = workspace / "reuse-transcript.txt"
                    reuse_transcript.write_text("显式本地转写，足够长的复用文本用于成功发布契约验证。\n", encoding="utf-8")
                    (output_dir / "summary_refined.md").write_text("旧兼容摘要\n", encoding="utf-8")
                    (output_dir / "mindmap_refined.mmd").write_text("旧兼容脑图\n", encoding="utf-8")
                    (output_dir / "mindmap.mmd").write_text("旧最终脑图\n", encoding="utf-8")
                    (output_dir / "unexpected.txt").write_text("用户笔记，不得删除\n", encoding="utf-8")
                    user_dir = output_dir / "user-data" / "nested"
                    user_dir.mkdir(parents=True)
                    (user_dir / "keep.json").write_text("{\"keep\": true}\n", encoding="utf-8")

                    previous_argv = sys.argv
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        str(source),
                        "--template",
                        "compact",
                        "--reuse-transcript",
                        str(reuse_transcript),
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
                    self.assertEqual(root_files, expected_root_files | {"unexpected.txt"})
                    self.assertFalse((output_dir / "support").exists())
                    self.assertFalse((output_dir / "_internal").exists())
                    self.assertFalse((output_dir / "summary_refined.md").exists())
                    self.assertFalse((output_dir / "mindmap_refined.mmd").exists())
                    self.assertFalse((output_dir / "transcript.txt").exists())
                    self.assertEqual(
                        (output_dir / "unexpected.txt").read_text(encoding="utf-8"),
                        "用户笔记，不得删除\n",
                    )
                    self.assertEqual(
                        (output_dir / "user-data" / "nested" / "keep.json").read_text(encoding="utf-8"),
                        "{\"keep\": true}\n",
                    )
                    published_paths = {
                        path.relative_to(output_dir).as_posix()
                        for path in output_dir.rglob("*")
                        if path.is_file()
                    }
                    self.assertNotIn("summary_draft.md", published_paths)
                    self.assertNotIn("transcript_segments.json", published_paths)
                    if expected_root_files == {"summary.md"}:
                        self.assertFalse((output_dir / "mindmap.mmd").exists())
                    else:
                        self.assertTrue((output_dir / "mindmap.mmd").is_file())

    def test_new_run_removes_legacy_root_subtitles_without_archiving_them(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-subtitle-cleanup-") as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "subtitle.zh-Hans.vtt").write_text("WEBVTT\n", encoding="utf-8")
            (out_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            canonical_cli.prepare_output_directory(out_dir) if hasattr(canonical_cli, "prepare_output_directory") else None
            from video_summary.outputs import prepare_output_directory
            prepare_output_directory(out_dir)
            self.assertFalse((out_dir / "subtitle.zh-Hans.vtt").exists())
            self.assertFalse((out_dir / "_internal").exists())
            self.assertTrue((out_dir / "notes.txt").exists())

    def test_draft_only_rerun_preserves_current_delivery_and_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-rerun-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            (output_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            (output_dir / "summary_refined.md").write_text("旧兼容稿\n", encoding="utf-8")
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)
            assert_cli_succeeded(self, result)
            self.assertEqual((output_dir / "summary.md").read_text(encoding="utf-8"), "旧摘要\n")
            self.assertEqual((output_dir / "mindmap.mmd").read_text(encoding="utf-8"), "旧脑图\n")
            self.assertEqual((output_dir / "notes.txt").read_text(encoding="utf-8"), "用户文件\n")
            self.assertFalse((output_dir / "summary_refined.md").exists())
            self.assertFalse((output_dir / "_internal").exists())
            self.assertFalse((output_dir / "support").exists())

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
            self.assertNotIn("previous_final", error)
            self.assertNotIn("Traceback", error)
            self.assertFalse(output_dir.exists())
            self.assertFalse(archive.exists())

    def test_llm_failure_does_not_create_legacy_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-failure-no-archive-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(SOURCE_FIXTURE), "--out-root", str(workspace / "output"), "--llm-refine"]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm_module, "call_llm", return_value="好的。"), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit):
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv
            self.assertNotIn("previous_final", stderr.getvalue())
            self.assertFalse((output_dir / "_internal" / "previous_final").exists())
            self.assertFalse(output_dir.exists())

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
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(source), "--out-root", str(workspace / "output")]
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
            self.assertIn("图像型 PDF", error)
            self.assertIn("文本层", error)
            self.assertFalse((workspace / "output" / local_source_id(source)).exists())
            self.assertEqual(list((workspace / "output").iterdir()), [])

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

    def test_draft_only_files_are_removed_with_the_run_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=workspace)
            assert_cli_succeeded(self, result)
            output_root = workspace / "output"
            self.assertTrue(output_root.is_dir())
            self.assertEqual(list(output_root.iterdir()), [])
            self.assertNotIn("support/", result.stdout)
            self.assertNotIn("_internal/", result.stdout)

    def test_draft_only_message_explains_final_publication_requirement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-draft-message-") as temp_dir:
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=Path(temp_dir))
        assert_cli_succeeded(self, result)
        message = result.stdout + result.stderr
        self.assertIn("未生成最终稿", message)
        self.assertIn("已随运行结束清理", message)
        self.assertIn("如需发布最终稿，请使用 --llm-refine", message)

    def test_same_stem_local_sources_use_distinct_reusable_output_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            sources = [workspace / "same-name.pdf", workspace / "same-name.docx", workspace / "same-name.mp4"]
            source_ids = {source: local_source_id(source) for source in sources}
            reuse_paths = {}
            for source, source_id in source_ids.items():
                source.write_bytes(b"fixture")
                output_dir = output_root / source_id
                output_dir.mkdir(parents=True)
                reuse_paths[source] = workspace / f"reuse-{source.suffix[1:]}.txt"
                reuse_paths[source].write_text(f"这是 {source.suffix} 的显式本地逐字稿，用于验证 source-id 隔离。", encoding="utf-8")
            for source, source_id in source_ids.items():
                result = run_canonical_cli(
                    str(source),
                    "--out-root",
                    str(output_root),
                    "--reuse-transcript",
                    str(reuse_paths[source]),
                    cwd=workspace,
                )
                assert_cli_succeeded(self, result)
                self.assertIn(str(output_root / source_id), result.stdout)
            self.assertEqual(list(output_root.iterdir()), [])

    def test_same_stem_and_extension_local_sources_use_distinct_reusable_output_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-source-id-collision-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "artifacts"
            sources = [workspace / "left" / "same-name.docx", workspace / "right" / "same-name.docx"]
            source_ids = {}
            reuse_paths = {}
            for source in sources:
                source.parent.mkdir(parents=True)
                source.write_bytes(b"fixture")
                source_ids[source] = local_source_id(source)
                output_dir = output_root / source_ids[source]
                output_dir.mkdir(parents=True)
                reuse_paths[source] = workspace / f"{source.parent.name}-transcript.txt"
                reuse_paths[source].write_text("这是同名同扩展文件的显式本地逐字稿内容，长度足够用于复用测试。", encoding="utf-8")
            self.assertNotEqual(*source_ids.values())
            for source, source_id in source_ids.items():
                result = run_canonical_cli(
                    str(source),
                    "--out-root",
                    str(output_root),
                    "--reuse-transcript",
                    str(reuse_paths[source]),
                    cwd=workspace,
                )
                assert_cli_succeeded(self, result)
                self.assertIn(str(output_root / source_id), result.stdout)
            self.assertEqual(list(output_root.iterdir()), [])

    def test_reuse_run_removes_legacy_root_subtitles_without_archiving_them(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-subtitle-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "unreadable.docx"
            source.write_bytes(b"not an OOXML document")
            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            output_dir.mkdir(parents=True)
            reuse_transcript = workspace / "reuse-transcript.txt"
            reuse_transcript.write_text("显式本地复用逐字稿内容足够长，用于验证旧根级字幕会被清理。", encoding="utf-8")
            legacy_subtitle = output_dir / "subtitle.zh-Hans.vtt"
            legacy_subtitle.write_text("WEBVTT\n", encoding="utf-8")
            result = run_canonical_cli(
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                str(reuse_transcript),
                cwd=workspace,
            )
            assert_cli_succeeded(self, result)
            self.assertFalse(legacy_subtitle.exists())
            self.assertFalse((output_dir / "support").exists())
            self.assertFalse((output_dir / "_internal").exists())

    def test_reuse_transcript_rebuilds_segments_from_current_text_for_chapters_and_llm(self) -> None:
        old_segment_text = "旧分段内容：不应出现在本轮章节或 LLM 提示中。"
        current_transcript = "[00:00] 新文本第一段：本轮 transcript 才是复用模式的唯一事实来源。\n[00:10] 新文本第二段：章节和 LLM 提示必须使用当前文本。\n"
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-refresh-derived-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "unreadable.docx"
            source.write_bytes(b"not an OOXML document")
            output_root = workspace / "artifacts"
            output_dir = output_root / local_source_id(source)
            output_dir.mkdir(parents=True)
            reuse_transcript = workspace / "reuse-transcript.txt"
            reuse_transcript.write_text(current_transcript, encoding="utf-8")
            (output_dir / "_internal").mkdir()
            (output_dir / "_internal" / "transcript_segments.json").write_text(json.dumps([{"start": 0.0, "end": 8.0, "text": old_segment_text}], ensure_ascii=False), encoding="utf-8")
            prompts: list[str] = []
            def fake_call_llm(prompt: str, model: str, api_kind: str) -> str:
                prompts.append(prompt)
                return "# 最终精修稿\n\n最终摘要正文。"
            previous_argv = sys.argv
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                str(reuse_transcript),
                "--llm-refine",
            ]
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm_module, "call_llm", side_effect=fake_call_llm), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    canonical_cli.main()
            finally:
                sys.argv = previous_argv
            self.assertTrue(prompts)
            self.assertTrue(any("新文本第一段" in prompt for prompt in prompts))
            self.assertTrue(all(old_segment_text not in prompt for prompt in prompts))
            self.assertTrue((output_dir / "summary.md").is_file())
            self.assertFalse((output_dir / "_internal").exists())
            self.assertFalse((output_dir / "support").exists())

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
            reuse_transcript = workspace / "reuse-transcript.txt"
            reuse_transcript.write_text("显式本地转写，用于验证 URL 输入仍在输出准备阶段被拒绝。", encoding="utf-8")
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
                        str(reuse_transcript),
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
            reuse_transcript = workspace / "reuse-transcript.txt"
            reuse_transcript.write_text("显式本地转写，用于验证在线 URL 不能进入复用流程。", encoding="utf-8")
            previous_argv = sys.argv
            stderr = io.StringIO()
            sys.argv = [
                str(REPO_ROOT / "src" / "video_summary_cli.py"),
                "https://example.test/video",
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                str(reuse_transcript),
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
            transcript = "这是显式本地离线逐字稿，用于验证复用模式不读取源文件。"
            reuse_transcript = workspace / "reuse-transcript.txt"
            reuse_transcript.write_text(transcript, encoding="utf-8")
            result = run_canonical_cli(
                str(source),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                str(reuse_transcript),
                "--template",
                "compact",
                cwd=workspace,
            )
            assert_cli_succeeded(self, result)
            self.assertFalse(output_dir.exists())
            self.assertNotIn("文档文本为空或过短", result.stderr)


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
        with tempfile.TemporaryDirectory(prefix="video-summary-no-llm-output-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)
            assert_cli_succeeded(self, result)
            message = result.stdout + result.stderr
            self.assertIn("最终稿：未生成", message)
            self.assertIn("临时转写、分段数据和内部草稿：已清理", message)
            self.assertEqual(list((workspace / "output").iterdir()), [])

    def test_llm_failure_error_marks_transcript_and_internal_files_as_non_final(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-llm-failure-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            (output_dir / "summary.md").write_text("旧摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧脑图\n", encoding="utf-8")
            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(SOURCE_FIXTURE), "--out-root", str(workspace / "output"), "--llm-refine"]
            stderr = io.StringIO()
            try:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(llm_module, "call_llm", return_value="# 摘要\n\n抱歉，我无法完成这个请求。"), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("LLM精校", stderr.getvalue())
            self.assertFalse(output_dir.exists())

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

                    root_files = (
                        {path.name for path in output_dir.iterdir() if path.is_file()}
                        if output_dir.exists()
                        else set()
                    )
                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("ERROR: 阶段=PDF/DOCX文本提取；", stderr.getvalue())
                    self.assertEqual(root_files, set(), msg=f"stale root files: {sorted(root_files)}")
                    self.assertFalse((output_dir / "transcript.txt").exists())
                    extract.assert_called_once()
                    download_audio.assert_not_called()
                    transcribe_audio.assert_not_called()

    def test_early_document_short_failure_cleans_legacy_root_intermediates(self) -> None:
        intermediate_files = ("metadata.json", "transcription.json", "transcript_segments.json", "transcript_timed.txt", "summary_chunks.json", "audio.mp3")
        with tempfile.TemporaryDirectory(prefix="video-summary-early-document-cleanup-") as temp_dir:
            workspace = Path(temp_dir)
            output_dir = workspace / "output" / SOURCE_ID
            output_dir.mkdir(parents=True)
            for filename in intermediate_files:
                path = output_dir / filename
                path.write_bytes(b"legacy audio") if path.suffix == ".mp3" else path.write_text("legacy\n", encoding="utf-8")
            (output_dir / "summary.md").write_text("旧最终摘要\n", encoding="utf-8")
            (output_dir / "mindmap.mmd").write_text("旧最终脑图\n", encoding="utf-8")
            previous_argv = sys.argv
            sys.argv = [str(REPO_ROOT / "src" / "video_summary_cli.py"), str(SOURCE_FIXTURE), "--out-root", str(workspace / "output")]
            stderr = io.StringIO()
            try:
                with mock.patch.object(canonical_cli, "extract_document_text", return_value="太短"), mock.patch.object(canonical_cli, "download_audio") as download_audio, mock.patch.object(canonical_cli, "transcribe_audio") as transcribe_audio, contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        canonical_cli.main()
            finally:
                sys.argv = previous_argv
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("文档文本为空或过短", stderr.getvalue())
            self.assertEqual((output_dir / "summary.md").read_text(encoding="utf-8"), "旧最终摘要\n")
            self.assertEqual((output_dir / "mindmap.mmd").read_text(encoding="utf-8"), "旧最终脑图\n")
            self.assertFalse(any((output_dir / name).exists() for name in intermediate_files))
            self.assertFalse((output_dir / "_internal" / "previous_final").exists())
            download_audio.assert_not_called()
            transcribe_audio.assert_not_called()


    def test_reuse_transcript_missing_or_unreadable_path_is_reported_clearly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-missing-") as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "not-readable.docx"
            output_root = workspace / "artifacts"
            cases = (
                workspace / "missing-transcript.txt",
                workspace / "transcript-directory",
            )
            cases[1].mkdir()

            for transcript_path in cases:
                with self.subTest(transcript_path=transcript_path):
                    previous_argv = sys.argv
                    stderr = io.StringIO()
                    sys.argv = [
                        str(REPO_ROOT / "src" / "video_summary_cli.py"),
                        str(source),
                        "--out-root",
                        str(output_root),
                        "--reuse-transcript",
                        str(transcript_path),
                    ]
                    try:
                        with mock.patch.object(canonical_cli, "extract_info", side_effect=AssertionError("source accessed")):
                            with contextlib.redirect_stderr(stderr):
                                with self.assertRaises(SystemExit) as raised:
                                    canonical_cli.main()
                    finally:
                        sys.argv = previous_argv

                    error = stderr.getvalue()
                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn("ERROR: 阶段=输出准备；", error)
                    self.assertIn("--reuse-transcript 指定的本地转写文件不存在或不可读", error)
                    self.assertIn(transcript_path.name, error)
                    self.assertNotIn("source accessed", error)
                    self.assertNotIn("support/transcript", error)
                    self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
