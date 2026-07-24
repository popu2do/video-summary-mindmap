from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from tests.support.cli import REPO_ROOT
from video_summary import artifacts, storage
from video_summary.outputs import OUTPUT_FILE_ROLES, OUTPUT_ROLE_LABELS
from video_summary.storage import OPTIONAL_ROOT_DELIVERABLES, REQUIRED_ROOT_DELIVERABLES


DOCUMENT_PATHS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / ".agents/skill/video-summary-mindmap/SKILL.md",
)
LEGACY_ENTRY_REFERENCE = re.compile(
    r"(?:workflow[/\\](?:video_summary\.py|output)|"
    r"\.agents[/\\]skill[/\\]video-summary-mindmap[/\\]scripts[/\\]video_summary\.py)"
)


class DocumentationMigrationContractTests(unittest.TestCase):
    def read_documents(self) -> dict[Path, str]:
        return {path: path.read_text(encoding="utf-8") for path in DOCUMENT_PATHS}

    def assert_delivery_decision_contract(self, text: str, relative_path: str) -> str:
        heading = re.search(r"(?im)^#{2,3} Delivery decision\s*$", text)
        self.assertIsNotNone(heading, msg=f"{relative_path} is missing the delivery decision section")
        if heading is None:
            return ""

        section_start = heading.end()
        next_heading = re.search(r"(?m)^#{1,3} ", text[section_start:])
        section_end = section_start + next_heading.start() if next_heading else len(text)
        section = text[section_start:section_end]

        exit_match = re.search(r"(?is)(?:先看 CLI 是否成功退出|check the CLI exit first)", section)
        summary_match = re.search(r"(?is)(?:再打开|then open).{0,100}output/<source-id>/summary\.md", section)
        self.assertIsNotNone(exit_match, msg=f"{relative_path} does not require a successful CLI exit first")
        self.assertIsNotNone(summary_match, msg=f"{relative_path} does not direct users to the final summary path")
        if exit_match and summary_match:
            self.assertLess(exit_match.start(), summary_match.start(), msg=relative_path)

        self.assertRegex(
            section,
            r"(?is)summary\.md.{0,120}(?:唯一必需的最终稿|only required final draft)",
            msg=f"{relative_path} does not make summary.md the only required final draft",
        )
        self.assertRegex(
            section,
            r"(?is)mindmap\.mmd.{0,160}(?:可选最终伴随物|optional final companion)",
            msg=f"{relative_path} does not classify mindmap.mmd as optional",
        )
        self.assertRegex(
            section,
            r"(?is)support/transcript\.txt.{0,140}(?:依据/支持材料|evidence/support material).{0,100}(?:不是最终稿|not the final draft)",
            msg=f"{relative_path} does not classify support/transcript.txt as support material",
        )
        self.assertRegex(
            section,
            r"(?is)_internal/.{0,120}previous_final.{0,180}(?:不交付给用户|never hand it off)",
            msg=f"{relative_path} does not exclude _internal/previous_final/ from delivery",
        )
        self.assertRegex(
            section,
            r"(?is)(?:没有|without).{0,40}--llm-refine.{0,100}(?:不产生最终稿|no final draft)",
            msg=f"{relative_path} does not state that no --llm-refine means no final draft",
        )
        return section

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

        self.assertEqual(
            wildcard_imports,
            [],
            msg="canonical CLI must not use wildcard imports:\n" + "\n".join(wildcard_imports),
        )

    def test_user_documents_only_point_to_the_canonical_cli(self) -> None:
        violations: list[str] = []
        for path, text in self.read_documents().items():
            for line_number, line in enumerate(text.splitlines(), start=1):
                if LEGACY_ENTRY_REFERENCE.search(line):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {line}")

        self.assertFalse(
            violations,
            msg="legacy workflow or skill-script entry references remain:\n"
            + "\n".join(violations),
        )
        for path, text in self.read_documents().items():
            self.assertIn("src/video_summary_cli.py", text, msg=str(path.relative_to(REPO_ROOT)))

    def test_user_documents_describe_the_draft_and_final_output_layout(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("output/<source-id>/", text, msg=relative_path)
            self.assertIn("_internal/", text, msg=relative_path)
            self.assertIn("summary.md", text, msg=relative_path)
            self.assertIn("mindmap.mmd", text, msg=relative_path)
            self.assertIn("support/transcript.txt", text, msg=relative_path)
            self.assertIn("--llm-refine", text, msg=relative_path)
            self.assertNotIn("workflow/output", text, msg=relative_path)
            self.assertNotIn("<video-id>", text, msg=relative_path)

    def test_user_documents_list_supported_input_types(self) -> None:
        required_terms = ("Bilibili", "YouTube", "local audio", "local video", ".pdf", ".doc", ".docx", "OOXML")
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            for term in required_terms:
                self.assertIn(term, text, msg=f"{relative_path} missing {term!r}")

    def test_reuse_transcript_requires_an_existing_transcript(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertRegex(
                text,
                r"--reuse-transcript.{0,320}(?:必须|需|已有|existing|already|when).{0,160}transcript\.txt",
                msg=f"{relative_path} does not document the transcript precondition",
            )

    def test_reuse_transcript_documentation_does_not_define_a_second_delivery_path(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("--reuse-transcript", text, msg=relative_path)
            self.assertIn("support/transcript.txt", text, msg=relative_path)
            self.assertIn("summary.md", text, msg=relative_path)
            self.assertIn("--llm-refine", text, msg=relative_path)
            self.assertRegex(
                text,
                r"(?is)(?:reuse-transcript).{0,420}(?:existing|已有|already|目录|directory).{0,240}transcript\.txt",
                msg=f"{relative_path} does not describe transcript reuse as support-material reuse",
            )

    def test_prepare_keeps_intermediate_material_out_of_the_user_delivery_contract(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("support/transcript.txt", text, msg=relative_path)
            self.assertIn("_internal/", text, msg=relative_path)
            self.assertRegex(
                text,
                r"(?is)(?:draft|cache|metadata|subtitle|audio|草稿|缓存|元数据|字幕|音频).{0,260}(?:_internal|内部).{0,180}(?:not|never|不是|不).{0,120}(?:final|delivery|交付|最终)",
                msg=f"{relative_path} does not separate intermediate state from delivery",
            )

    def test_subtitles_are_not_presented_as_final_delivery(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertRegex(text, r"(?is)(?:subtitle|subtitles|字幕)", msg=relative_path)
            self.assert_delivery_decision_contract(text, relative_path)

    def test_internal_metadata_is_not_core_delivery(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("metadata", text.lower(), msg=relative_path)
            section = self.assert_delivery_decision_contract(text, relative_path)
            self.assertRegex(section, r"(?is)(?:内部状态|historical internal state)", msg=relative_path)

    def test_timestamped_and_transcription_metadata_remain_internal_support_state(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("transcript", text.lower(), msg=relative_path)
            self.assertIn("_internal/", text, msg=relative_path)
            self.assertRegex(
                text,
                r"(?is)(?:transcript|metadata|segments|转写|元数据|分段).{0,700}(?:support|internal|not user delivery|not delivery|支持|内部|不是.*交付)",
                msg=f"{relative_path} does not keep support artifacts out of final delivery",
            )

    def test_user_documents_describe_local_whisper_without_removed_engine_option(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertNotIn("--transcribe-engine", text, msg=relative_path)
            self.assertNotIn("TRANSCRIBE_ENGINE", text, msg=relative_path)
            self.assertIn("--local-whisper-model", text, msg=relative_path)
            self.assertRegex(text, r"faster-whisper", msg=relative_path)

    def test_out_root_has_a_privacy_warning(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("--out-root", text, msg=relative_path)
            self.assertRegex(text, r"隐私|敏感|私有|privacy|private|sensitive", msg=relative_path)
            self.assertRegex(text, r"不要|避免|勿|do not|avoid", msg=relative_path)

    def test_templates_explain_their_different_output_roles(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("--template compact|refined", text, msg=relative_path)
            self.assertIn("compact", text, msg=relative_path)
            self.assertIn("refined", text, msg=relative_path)
            self.assertRegex(text, r"(?is)deterministic|offline|离线|确定性", msg=relative_path)
            self.assertRegex(text, r"(?is)structured|chapter|term|结构化|章节|术语", msg=relative_path)

    def test_user_facing_delivery_roles_keep_internal_drafts_out_of_delivery(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assert_delivery_decision_contract(text, relative_path)

    def test_storage_is_the_single_registry_for_output_file_contract(self) -> None:
        expected_roles = {
            "core_delivery": ("summary.md", "mindmap.mmd"),
            "supporting_material": ("support/transcript.txt",),
            "optional_derived": (
                "summary_draft.md",
                "mindmap_draft.mmd",
                "transcript_segments.json",
                "transcript_timed.txt",
            ),
            "intermediate_cache": (
                "metadata.json",
                "summary_chunks.json",
                "audio.mp3",
                "transcription.json",
            ),
        }
        storage_roles = getattr(storage, "OUTPUT_FILE_ROLES", None)
        self.assertIsInstance(storage_roles, dict, "storage must expose OUTPUT_FILE_ROLES")
        self.assertEqual(
            getattr(storage, "REQUIRED_ROOT_DELIVERABLES", None),
            ("summary.md",),
        )
        self.assertEqual(
            getattr(storage, "OPTIONAL_ROOT_DELIVERABLES", None),
            ("mindmap.mmd",),
        )
        self.assertEqual(
            getattr(storage, "ROOT_DELIVERABLES", None),
            expected_roles["core_delivery"],
        )
        self.assertEqual(
            getattr(storage, "LEGACY_FINAL_OUTPUTS", None),
            ("summary_refined.md", "mindmap_refined.mmd"),
        )
        self.assertEqual(
            getattr(storage, "ARCHIVED_OUTPUTS", None),
            expected_roles["core_delivery"] + ("summary_refined.md", "mindmap_refined.mmd"),
        )

        if isinstance(storage_roles, dict):
            for role, filenames in expected_roles.items():
                self.assertEqual(storage_roles.get(role), filenames, msg=f"storage role: {role}")

            self.assertIs(OUTPUT_FILE_ROLES, storage_roles)
            self.assertIs(artifacts.INTERNAL_ARTIFACTS, storage.INTERNAL_ARTIFACTS)
            self.assertIs(artifacts.LEGACY_ROOT_ARTIFACTS, storage.LEGACY_ROOT_ARTIFACTS)

    def test_output_file_roles_are_defined_once_and_documented_consistently(self) -> None:
        self.assertEqual(REQUIRED_ROOT_DELIVERABLES, ("summary.md",))
        self.assertEqual(OPTIONAL_ROOT_DELIVERABLES, ("mindmap.mmd",))
        expected_roles = {
            "core_delivery": REQUIRED_ROOT_DELIVERABLES + OPTIONAL_ROOT_DELIVERABLES,
            "supporting_material": ("support/transcript.txt",),
            "optional_derived": (
                "summary_draft.md",
                "mindmap_draft.mmd",
                "transcript_segments.json",
                "transcript_timed.txt",
            ),
            "intermediate_cache": ("metadata.json", "summary_chunks.json", "audio.mp3", "transcription.json"),
        }
        all_files = [filename for filenames in OUTPUT_FILE_ROLES.values() for filename in filenames]
        self.assertEqual(len(all_files), len(set(all_files)))
        self.assertEqual(OUTPUT_FILE_ROLES, expected_roles)
        self.assertEqual(set(OUTPUT_FILE_ROLES), set(OUTPUT_ROLE_LABELS))
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assert_delivery_decision_contract(text, relative_path)

    def test_previous_results_are_internal_and_excluded_from_current_delivery(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("previous_final", text, msg=relative_path)
            self.assertRegex(
                text,
                r"(?is)(?:previous_final|旧结果|历史).{0,400}(?:internal state|内部状态|not delivery|not user delivery|不是交付)",
                msg=f"{relative_path} does not keep previous results out of delivery",
            )
            self.assertRegex(
                text,
                r"(?is)transcript\.txt.{0,240}(?:依据|support(?:ing)?).{0,100}(?:材料|material).{0,180}(?:不是|not|never).{0,120}(?:最终|summary|final|交付|delivery)",
                msg=f"{relative_path} does not keep transcript.txt out of final delivery",
            )

    def test_internal_cache_is_not_a_user_delivery_or_consistency_contract(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            section = self.assert_delivery_decision_contract(text, relative_path)
            self.assertRegex(section, r"(?is)(?:cache|缓存)", msg=relative_path)

    def test_final_root_files_require_successful_llm_refinement(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assert_delivery_decision_contract(text, relative_path)


if __name__ == "__main__":
    unittest.main()
