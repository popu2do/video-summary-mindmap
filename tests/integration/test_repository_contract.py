from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tests.support.cli import REPO_ROOT
from video_summary import outputs, storage
from video_summary.outputs import OUTPUT_FILE_ROLES, OUTPUT_ROLE_LABELS


class RepositoryContractTests(unittest.TestCase):
    def test_canonical_cli_avoids_wildcard_imports(self) -> None:
        cli_path = REPO_ROOT / "src" / "video_summary" / "cli.py"
        tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
        wildcard_imports = [
            f"line {node.lineno}: from {node.module or ''} import *"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name == "*"
        ]
        self.assertEqual(wildcard_imports, [])

    def test_root_delivery_contract_contains_only_summary_and_optional_mindmap(self) -> None:
        self.assertEqual(storage.ROOT_DELIVERABLES, ("summary.md", "mindmap.mmd"))
        self.assertEqual(storage.REQUIRED_ROOT_DELIVERABLES, ("summary.md",))
        self.assertEqual(storage.OPTIONAL_ROOT_DELIVERABLES, ("mindmap.mmd",))
        self.assertEqual(OUTPUT_FILE_ROLES, {"core_delivery": storage.ROOT_DELIVERABLES})
        self.assertEqual(set(OUTPUT_ROLE_LABELS), {"core_delivery", "supporting_material", "optional_derived", "intermediate_cache"})

    def test_output_preparation_preserves_unknown_user_files_and_current_finals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-contract-prepare-") as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "summary.md").write_text("既有最终摘要\n", encoding="utf-8")
            (out_dir / "mindmap.mmd").write_text("mindmap\n", encoding="utf-8")
            (out_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
            (out_dir / "summary_refined.md").write_text("旧兼容文件\n", encoding="utf-8")
            (out_dir / "support").mkdir()
            (out_dir / "support" / "transcript.txt").write_text("旧转写\n", encoding="utf-8")

            outputs.prepare_output_directory(out_dir)

            self.assertEqual((out_dir / "summary.md").read_text(encoding="utf-8"), "既有最终摘要\n")
            self.assertEqual((out_dir / "mindmap.mmd").read_text(encoding="utf-8"), "mindmap\n")
            self.assertEqual((out_dir / "notes.txt").read_text(encoding="utf-8"), "用户文件\n")
            self.assertFalse((out_dir / "summary_refined.md").exists())
            self.assertFalse((out_dir / "support").exists())

    def test_final_delivery_requires_nonempty_summary_but_not_mindmap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="video-summary-contract-final-") as temp_dir:
            out_dir = Path(temp_dir)
            self.assertFalse(outputs.final_delivery_ready(out_dir))
            (out_dir / "summary.md").write_text("\n", encoding="utf-8")
            self.assertFalse(outputs.final_delivery_ready(out_dir))
            (out_dir / "summary.md").write_text("# 摘要\n", encoding="utf-8")
            self.assertTrue(outputs.final_delivery_ready(out_dir))
            (out_dir / "mindmap.mmd").write_text("mindmap\n", encoding="utf-8")
            self.assertTrue(outputs.final_delivery_ready(out_dir))

    def test_runtime_workspace_is_not_part_of_the_output_contract(self) -> None:
        runtime_path = REPO_ROOT / "src" / "video_summary" / "runtime.py"
        text = runtime_path.read_text(encoding="utf-8")
        self.assertIn("tempfile.mkdtemp", text)
        self.assertNotIn("support/transcript.txt", text)
        self.assertNotIn("previous_final", text)


if __name__ == "__main__":
    unittest.main()
