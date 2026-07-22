from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support.cli import REPO_ROOT
from video_summary.outputs import OUTPUT_FILE_ROLES, OUTPUT_ROLE_LABELS


DOCUMENT_PATHS = (
    REPO_ROOT / "README.md",
)
LEGACY_ENTRY_REFERENCE = re.compile(
    r"(?:workflow[/\\](?:video_summary\.py|output)|"
    r"\.agents[/\\]skill[/\\]video-summary-mindmap[/\\]scripts[/\\]video_summary\.py)"
)


class DocumentationMigrationContractTests(unittest.TestCase):
    def read_documents(self) -> dict[Path, str]:
        return {path: path.read_text(encoding="utf-8") for path in DOCUMENT_PATHS}

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

    def test_user_documents_describe_the_flat_output_layout(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("output/<source-id>/", text, msg=relative_path)
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
                r"--reuse-transcript.{0,160}(?:必须|需|已有|existing).{0,160}transcript\.txt",
                msg=f"{relative_path} does not document the transcript precondition",
            )

    def test_reuse_transcript_documents_missing_file_fallback(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertRegex(
                text,
                r"(?s)--reuse-transcript.*(?:warning|警告).*?(?:fallback|falls back|回退).*?(?:ordinary|normal|普通)",
                msg=f"{relative_path} does not document missing-transcript fallback behavior",
            )

    def test_transcription_json_is_intermediate_metadata_not_core_delivery(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertIn("transcription.json", text, msg=relative_path)
            self.assertRegex(
                text,
                r"transcription\.json(?s:.{0,300})(?:元数据|metadata)(?s:.{0,300})(?:中间产物|intermediate)",
                msg=f"{relative_path} does not classify transcription.json as metadata/intermediate",
            )
            self.assertRegex(
                text,
                r"transcription\.json(?s:.{0,350})(?:核心交付|core delivery|primary deliverable)",
                msg=f"{relative_path} does not distinguish transcription.json from core delivery files",
            )

    def test_transcription_json_is_metadata_only_and_timestamped_outputs_are_separate(self) -> None:
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            self.assertRegex(
                text,
                r"(?is)transcription\.json(?:(?!\n\n).){0,260}(?:only stores transcription metadata|仅保存转写元数据)",
                msg=f"{relative_path} does not state that transcription.json only stores transcription metadata",
            )
            self.assertRegex(
                text,
                r"(?is)(?:does not automatically\s+include\s+timestamped\s+`segments`|不自动包含时间戳 segments)",
                msg=f"{relative_path} does not state that transcription.json does not automatically include segments",
            )
            self.assertRegex(
                text,
                r"(?is)(?:timestamped\s+`segments`|时间戳\s+segments).{0,220}`transcript_segments\.json`.{0,120}`transcript_timed\.txt`",
                msg=f"{relative_path} does not place timestamped segments in the dedicated transcript files",
            )
            self.assertNotRegex(
                text,
                r"(?is)transcription\.json(?:(?!\n\n).){0,320}(?:includes|包含).{0,40}`?segments`?",
                msg=f"{relative_path} incorrectly claims transcription.json includes segments",
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
            self.assertRegex(text, r"(?s)compact.{0,240}(?:简|离线|确定性|concise|deterministic|offline)", msg=relative_path)
            self.assertRegex(text, r"(?s)refined.{0,320}(?:结构化|章节|术语|精校|structured|chapter|term|richer)", msg=relative_path)

    def test_output_file_roles_are_defined_once_and_documented_consistently(self) -> None:
        all_files = [filename for filenames in OUTPUT_FILE_ROLES.values() for filename in filenames]
        self.assertEqual(len(all_files), len(set(all_files)))
        self.assertEqual(set(OUTPUT_FILE_ROLES), set(OUTPUT_ROLE_LABELS))
        for path, text in self.read_documents().items():
            relative_path = str(path.relative_to(REPO_ROOT))
            for role, filenames in OUTPUT_FILE_ROLES.items():
                self.assertIn(OUTPUT_ROLE_LABELS[role], text, msg=f"{relative_path} missing {role}")
                for filename in filenames:
                    self.assertIn(filename, text, msg=f"{relative_path} missing {filename}")


if __name__ == "__main__":
    unittest.main()
