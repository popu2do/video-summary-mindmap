from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.support.cli import temporary_test_directory
from video_summary import cli
from video_summary import config
from video_summary import storage


class EntrypointAndStorageTests(unittest.TestCase):
    def test_default_output_root_is_project_root_output_from_arbitrary_cwd(self) -> None:
        with temporary_test_directory(prefix="cwd-") as temp_dir:
            child_env = os.environ.copy()
            child_env["PYTHONPATH"] = str(SRC_ROOT)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from video_summary.config import default_output_root; print(default_output_root())",
                ],
                cwd=temp_dir,
                env=child_env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(Path(result.stdout.strip()), REPO_ROOT / "output")

    def test_explicit_env_file_is_loaded_without_printing_values(self) -> None:
        with temporary_test_directory(prefix="env-") as temp_dir:
            env_path = Path(temp_dir) / ".local.env"
            env_path.write_text("ENTRYPOINT_TEST_TOKEN=fixture-only\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = config.load_local_env(env_path)
                self.assertEqual(loaded, env_path)
                self.assertEqual(os.environ["ENTRYPOINT_TEST_TOKEN"], "fixture-only")

    def test_default_env_resolution_ignores_cwd_and_uses_code_derived_locations(self) -> None:
        with temporary_test_directory(prefix="stable-env-") as temp_dir:
            root = Path(temp_dir)
            cwd = root / "caller"
            project_root = root / "repo"
            workspace_root = root / "workspace"
            cwd.mkdir()
            project_root.mkdir()
            workspace_root.mkdir()
            (cwd / config.LOCAL_ENV_FILENAME).write_text(
                "ENTRYPOINT_ENV_ORIGIN=cwd\n", encoding="utf-8"
            )
            (workspace_root / config.LOCAL_ENV_FILENAME).write_text(
                "ENTRYPOINT_ENV_ORIGIN=workspace\n", encoding="utf-8"
            )
            with mock.patch.object(config, "PROJECT_ROOT", project_root), \
                    mock.patch.object(config, "WORKSPACE_ROOT", workspace_root), \
                    mock.patch("video_summary.config.Path.cwd", return_value=cwd), \
                    mock.patch.dict(os.environ, {}, clear=True):
                loaded = config.load_local_env()
                self.assertEqual(loaded, workspace_root / config.LOCAL_ENV_FILENAME)
                self.assertEqual(os.environ["ENTRYPOINT_ENV_ORIGIN"], "workspace")

    def test_explicit_missing_env_file_is_a_business_error(self) -> None:
        with temporary_test_directory(prefix="missing-env-") as temp_dir:
            missing = Path(temp_dir) / "missing.env"
            with self.assertRaises(config.UserFacingError) as raised:
                config.load_local_env(missing)
        self.assertIn("显式 env 文件不存在", str(raised.exception))

    def test_cli_reports_explicit_env_file_failure_at_configuration_stage(self) -> None:
        with temporary_test_directory(prefix="missing-cli-env-") as temp_dir:
            missing = Path(temp_dir) / "missing.env"
            stderr = io.StringIO()
            argv = ["video_summary_cli.py", "fixture.mp4", "--env-file", str(missing)]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("ERROR: 阶段=配置；显式 env 文件不存在", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_explicit_unreadable_env_file_is_a_business_error(self) -> None:
        with temporary_test_directory(prefix="unreadable-env-") as temp_dir:
            env_path = Path(temp_dir) / ".local.env"
            env_path.write_text("ENTRYPOINT_UNREADABLE=fixture-only\n", encoding="utf-8")
            with mock.patch.object(
                Path,
                "read_text",
                side_effect=OSError("access denied"),
            ):
                with self.assertRaises(config.UserFacingError) as raised:
                    config.load_local_env(env_path)
            self.assertIn("无法读取显式 env 文件", str(raised.exception))

    def test_reloading_explicit_env_does_not_leave_previous_loaded_values(self) -> None:
        with temporary_test_directory(prefix="reload-env-") as temp_dir:
            root = Path(temp_dir)
            first = root / "first.env"
            second = root / "second.env"
            first.write_text(
                "ENTRYPOINT_OLD_ONLY=old\nENTRYPOINT_SHARED=first\n",
                encoding="utf-8",
            )
            second.write_text(
                "ENTRYPOINT_NEW_ONLY=new\nENTRYPOINT_SHARED=second\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                config.load_local_env(first)
                config.load_local_env(second)
                self.assertNotIn("ENTRYPOINT_OLD_ONLY", os.environ)
                self.assertEqual(os.environ["ENTRYPOINT_SHARED"], "second")
                self.assertEqual(os.environ["ENTRYPOINT_NEW_ONLY"], "new")

    def test_user_facing_error_is_a_library_exception_not_process_exit(self) -> None:
        self.assertTrue(issubclass(config.UserFacingError, Exception))
        self.assertFalse(issubclass(config.UserFacingError, SystemExit))
        with self.assertRaises(config.UserFacingError):
            config.fail("fixture failure")

    def test_failed_domain_load_clears_previous_global_state(self) -> None:
        with temporary_test_directory(prefix="domain-") as temp_dir:
            references_dir = Path(temp_dir)
            (references_dir / "domain_terms.json").write_text(
                '{"known":{"known_terms":["旧词"],"replacements":{"错词":"旧词"}}}',
                encoding="utf-8",
            )
            with mock.patch.object(config, "REFERENCES_DIR", references_dir):
                config.ACTIVE_DOMAIN_TERMS.clear()
                config.ACTIVE_DOMAIN_REPLACEMENTS.clear()
                try:
                    config.load_domain_config("known")
                    with self.assertRaises(config.UserFacingError):
                        config.load_domain_config("missing")
                    self.assertEqual(config.ACTIVE_DOMAIN_TERMS, [])
                    self.assertEqual(config.ACTIVE_DOMAIN_REPLACEMENTS, {})
                finally:
                    config.ACTIVE_DOMAIN_TERMS.clear()
                    config.ACTIVE_DOMAIN_REPLACEMENTS.clear()

    def test_storage_path_queries_are_pure_and_ensure_functions_create_directories(self) -> None:
        with temporary_test_directory(prefix="storage-") as temp_dir:
            out_dir = Path(temp_dir) / "source"
            self.assertEqual(storage.support_dir(out_dir), out_dir / "support")
            self.assertEqual(storage.transcript_path(out_dir), out_dir / "support" / "transcript.txt")
            self.assertEqual(storage.internal_dir(out_dir), out_dir / "_internal")
            self.assertEqual(storage.internal_path(out_dir, "metadata.json"), out_dir / "_internal" / "metadata.json")
            self.assertEqual(storage.previous_final_dir(out_dir), out_dir / "_internal" / "previous_final")
            self.assertFalse(out_dir.exists())

            storage.ensure_support_dir(out_dir)
            storage.ensure_internal_dir(out_dir)
            storage.ensure_previous_final_dir(out_dir)

            self.assertTrue((out_dir / "support").is_dir())
            self.assertTrue((out_dir / "_internal").is_dir())
            self.assertTrue((out_dir / "_internal" / "previous_final").is_dir())

    def test_document_extraction_failure_removes_new_empty_source_directory(self) -> None:
        with temporary_test_directory(prefix="failure-") as temp_dir:
            out_root = Path(temp_dir) / "output"
            source = Path(temp_dir) / "input.docx"
            source.write_bytes(b"fixture")
            stderr = io.StringIO()
            argv = [
                "video_summary_cli.py",
                str(source),
                "--out-root",
                str(out_root),
            ]
            with mock.patch.object(cli, "load_local_env"), \
                    mock.patch.object(cli, "load_domain_config"), \
                    mock.patch.object(cli, "extract_info", return_value={"title": "输入", "id": "fixture"}), \
                    mock.patch.object(cli, "slug_from_info", return_value="fixture-docx"), \
                    mock.patch.object(cli, "local_source_path", return_value=source), \
                    mock.patch.object(cli, "extract_document_text", side_effect=config.UserFacingError("文档提取失败")), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("文档提取失败", stderr.getvalue())
            self.assertFalse((out_root / "fixture-docx").exists())

    def test_existing_final_is_preserved_when_new_run_fails(self) -> None:
        with temporary_test_directory(prefix="existing-") as temp_dir:
            out_root = Path(temp_dir) / "output"
            out_dir = out_root / "fixture-docx"
            out_dir.mkdir(parents=True)
            (out_dir / "summary.md").write_text("旧最终稿\n", encoding="utf-8")
            (out_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            source = Path(temp_dir) / "input.docx"
            source.write_bytes(b"fixture")
            stderr = io.StringIO()
            argv = ["video_summary_cli.py", str(source), "--out-root", str(out_root)]
            with mock.patch.object(cli, "load_local_env"), mock.patch.object(cli, "load_domain_config"), mock.patch.object(cli, "extract_info", return_value={"title": "输入", "id": "fixture"}), mock.patch.object(cli, "slug_from_info", return_value="fixture-docx"), mock.patch.object(cli, "local_source_path", return_value=source), mock.patch.object(cli, "extract_document_text", side_effect=config.UserFacingError("文档提取失败")), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("文档提取失败", stderr.getvalue())
            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), "旧最终稿\n")
            self.assertEqual((out_dir / "notes.txt").read_text(encoding="utf-8"), "用户文件\n")
            self.assertFalse((out_dir / "_internal" / "previous_final").exists())

    def test_failure_after_creating_empty_internal_dir_removes_new_source_directory(self) -> None:
        with temporary_test_directory(prefix="nested-failure-") as temp_dir:
            workspace = Path(temp_dir)
            out_root = workspace / "output"
            source = workspace / "input.mp4"
            source.write_bytes(b"fixture")
            stderr = io.StringIO()

            def fail_after_creating_internal(_source: str, out_dir: Path, _cookies: str | None) -> Path:
                storage.ensure_internal_dir(out_dir)
                raise RuntimeError("下载失败")

            argv = [
                "video_summary_cli.py",
                str(source),
                "--out-root",
                str(out_root),
            ]
            with mock.patch.object(cli, "load_local_env"), \
                    mock.patch.object(cli, "load_domain_config"), \
                    mock.patch.object(cli, "extract_info", return_value={"title": "输入", "id": "fixture"}), \
                    mock.patch.object(cli, "slug_from_info", return_value="fixture-mp4"), \
                    mock.patch.object(cli, "local_source_path", return_value=source), \
                    mock.patch.object(cli, "choose_subtitle", return_value=None), \
                    mock.patch.object(cli, "download_audio", side_effect=fail_after_creating_internal), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("下载失败", stderr.getvalue())
            self.assertFalse((out_root / "fixture-mp4").exists())


    def test_existing_empty_source_directory_is_removed_after_repeat_failure(self) -> None:
        with temporary_test_directory(prefix="repeat-empty-") as temp_dir:
            workspace = Path(temp_dir)
            out_root = workspace / "output"
            out_dir = out_root / "fixture-mp4"
            (out_dir / "_internal").mkdir(parents=True)
            source = workspace / "input.mp4"
            source.write_bytes(b"fixture")
            stderr = io.StringIO()

            def fail_after_creating_internal(_source: str, out_dir: Path, _cookies: str | None) -> Path:
                storage.ensure_internal_dir(out_dir)
                raise RuntimeError("重复运行下载失败")

            argv = [
                "video_summary_cli.py",
                str(source),
                "--out-root",
                str(out_root),
            ]
            with mock.patch.object(cli, "load_local_env"), \
                    mock.patch.object(cli, "load_domain_config"), \
                    mock.patch.object(cli, "extract_info", return_value={"title": "输入", "id": "fixture"}), \
                    mock.patch.object(cli, "slug_from_info", return_value="fixture-mp4"), \
                    mock.patch.object(cli, "local_source_path", return_value=source), \
                    mock.patch.object(cli, "choose_subtitle", return_value=None), \
                    mock.patch.object(cli, "download_audio", side_effect=fail_after_creating_internal), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("重复运行下载失败", stderr.getvalue())
            self.assertFalse(out_dir.exists())


if __name__ == "__main__":
    unittest.main()
