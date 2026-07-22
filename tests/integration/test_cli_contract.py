from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_summary import cli as canonical_cli
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
            "语义精校",
            "优先复用",
            "缺失时警告并回退普通处理",
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
        self.assertNotIn("SHA-256", result.stdout)
        for document in (REPO_ROOT / "README.md", REPO_ROOT / ".agents/skill/video-summary-mindmap/SKILL.md"):
            text = document.read_text(encoding="utf-8")
            self.assertRegex(text, r"(?s)安全化文件名.*扩展名.*SHA-256.*前 8 位", msg=str(document))
            self.assertIn("--reuse-transcript", text, msg=str(document))
            self.assertIn("--force-transcribe", text, msg=str(document))
            self.assertIn("不能同时使用", text, msg=str(document))
            self.assertIn("ERROR: 阶段=", text, msg=str(document))
            self.assertIn("--out-root", text, msg=str(document))

    def test_reuse_transcript_without_llm_refine_removes_stale_refined_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-stale-refined-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "output"
            first_result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--out-root",
                str(output_root),
                "--template",
                "refined",
                cwd=workspace,
            )
            assert_cli_succeeded(self, first_result)

            output_dir = output_root / SOURCE_ID
            (output_dir / "summary_refined.md").write_text("旧精校摘要", encoding="utf-8")
            (output_dir / "mindmap_refined.mmd").write_text("旧精校脑图", encoding="utf-8")
            (output_dir / "transcript.txt").write_text(
                (output_dir / "transcript.txt").read_text(encoding="utf-8") + "\n用户编辑后的内容。",
                encoding="utf-8",
            )

            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                "--template",
                "refined",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertFalse((output_dir / "summary_refined.md").exists())
            self.assertFalse((output_dir / "mindmap_refined.mmd").exists())
            self.assertTrue((output_dir / "summary.md").exists())
            self.assertTrue((output_dir / "mindmap.mmd").exists())
            self.assertEqual(
                {path.name for path in output_root.iterdir() if path.is_dir()},
                {SOURCE_ID},
            )

    def test_reuse_transcript_removes_stale_transcription_metadata_after_edit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-stale-transcription-") as temp_dir:
            workspace = Path(temp_dir)
            output_root = workspace / "output"
            first_result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--out-root",
                str(output_root),
                cwd=workspace,
            )
            assert_cli_succeeded(self, first_result)

            output_dir = output_root / SOURCE_ID
            transcription_path = output_dir / "transcription.json"
            transcription_path.write_text("旧转写元数据", encoding="utf-8")
            (output_dir / "transcript.txt").write_text(
                (output_dir / "transcript.txt").read_text(encoding="utf-8") + "\n用户编辑后的新转写内容。",
                encoding="utf-8",
            )

            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--out-root",
                str(output_root),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertFalse(transcription_path.exists())

    def test_reuse_transcript_warns_when_transcript_is_missing_without_changing_success_flow(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-reuse-warning-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--reuse-transcript",
                "--template",
                "compact",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            self.assertIn("--reuse-transcript", result.stderr)
            self.assertIn("transcript.txt", result.stderr)
            self.assertTrue((workspace / "output" / SOURCE_ID / "transcript.txt").exists())

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

    def test_offline_document_generates_complete_transcript_summary_and_mindmap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-offline-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(
                str(SOURCE_FIXTURE),
                "--template",
                "compact",
                cwd=workspace,
            )

            assert_cli_succeeded(self, result)
            output_dir = workspace / "output" / SOURCE_ID
            self.assertEqual(
                (output_dir / "transcript.txt").read_text(encoding="utf-8"),
                OFFLINE_TRANSCRIPT,
            )
            self.assertTrue((output_dir / "summary.md").read_text(encoding="utf-8").strip())
            self.assertTrue((output_dir / "mindmap.mmd").read_text(encoding="utf-8").strip())

            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("source"))
            self.assertTrue(metadata.get("title"))
            self.assertIsInstance(metadata.get("word_count"), int)

    def test_output_contains_the_core_flat_file_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-files-") as temp_dir:
            workspace = Path(temp_dir)
            result = run_canonical_cli(str(SOURCE_FIXTURE), cwd=workspace)

            assert_cli_succeeded(self, result)
            output_dir = workspace / "output" / SOURCE_ID
            actual_files = {path.name for path in output_dir.iterdir() if path.is_file()}

        self.assertTrue(
            {
                "metadata.json",
                "transcript.txt",
                "summary.md",
                "mindmap.mmd",
            }.issubset(actual_files),
            msg=f"actual files: {sorted(actual_files)}",
        )

    def test_final_prompt_exposes_output_roles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-output-roles-") as temp_dir:
            result = run_canonical_cli(str(SOURCE_FIXTURE), "--template", "compact", cwd=Path(temp_dir))

        assert_cli_succeeded(self, result)
        for label in ("核心交付", "可选派生", "中间缓存"):
            self.assertIn(label, result.stdout)
        for filename in ("transcript.txt", "summary.md", "mindmap.mmd", "metadata.json"):
            self.assertIn(filename, result.stdout)

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
                self.assertTrue((output_dir / "summary.md").exists())
                self.assertTrue((output_dir / "mindmap.mmd").exists())

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
                self.assertTrue((output_dir / "summary.md").exists())
                self.assertTrue((output_dir / "mindmap.mmd").exists())

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
                (output_dir / "transcript.txt").read_text(encoding="utf-8"),
                transcript,
            )
            self.assertTrue((output_dir / "summary.md").exists())
            self.assertTrue((output_dir / "mindmap.mmd").exists())


if __name__ == "__main__":
    unittest.main()
