from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support.cli import REPO_ROOT


DOCUMENT_PATHS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / ".agents/skill/video-summary-mindmap/SKILL.md",
)


def section(text: str, title: str) -> str:
    heading = re.search(
        rf"(?im)^#{{2,3}}\s+{re.escape(title)}\s*$",
        text,
    )
    if heading is None:
        raise AssertionError(f"missing heading: {title}")
    next_heading = re.search(r"(?m)^#{1,3}\s+", text[heading.end() :])
    end = heading.end() + next_heading.start() if next_heading else len(text)
    return text[heading.end() : end]


class UserDocumentationContractTests(unittest.TestCase):
    def read_documents(self) -> dict[Path, str]:
        return {path: path.read_text(encoding="utf-8") for path in DOCUMENT_PATHS}

    def test_canonical_command_is_a_final_delivery_command(self) -> None:
        for path, text in self.read_documents().items():
            canonical = section(text, "Canonical command")
            commands = re.findall(r"```powershell\s*(.*?)```", canonical, flags=re.S)
            self.assertTrue(commands, msg=f"{path} has no canonical command block")
            self.assertRegex(
                commands[0],
                r"src/video_summary_cli\.py.*--llm-refine",
                msg=f"{path} canonical command must produce summary.md",
            )

    def test_canonical_command_shows_a_local_mp4_example(self) -> None:
        for path, text in self.read_documents().items():
            canonical = section(text, "Canonical command")
            self.assertRegex(
                canonical,
                r"(?is)(?:[A-Z]:/|[A-Z]:\\)[^\n`]*\.mp4.*--llm-refine|--llm-refine[^\n`]*(?:[A-Z]:/|[A-Z]:\\)[^\n`]*\.mp4",
                msg=f"{path} canonical command must show a local MP4 final-delivery example",
            )

    def test_no_refine_is_explicitly_support_only_and_manual_review_only(self) -> None:
        for path, text in self.read_documents().items():
            support_only = section(text, "Support-only path (no --llm-refine)")
            self.assertRegex(support_only, r"(?i)support material")
            self.assertRegex(support_only, r"(?i)(manual\s+review|人工复核)")
            self.assertRegex(support_only, r"(?i)does not produce a final|不产生最终稿")

    def test_documents_have_one_command_final_path_and_optional_review_rerun(self) -> None:
        for path, text in self.read_documents().items():
            document_path = section(text, "Document shortest path")
            self.assertRegex(document_path, r"(?is)one execution.*--llm-refine")
            self.assertRegex(document_path, r"(?is)PDF.*--llm-refine")
            self.assertRegex(document_path, r"(?is)DOCX.*--llm-refine")
            self.assertRegex(
                document_path,
                r"(?is)second run.*optional.*(?:manual(?:ly)? edit|人工修改).*support/transcript",
            )

    def test_image_only_pdf_failure_contract_is_exact(self) -> None:
        for path, text in self.read_documents().items():
            failure = section(text, "Image-only PDF failure contract")
            self.assertIn("PDF 未提取到文本层，图像型 PDF 暂不支持", failure)
            self.assertRegex(failure, r"(?i)non-zero|非零退出")
            self.assertRegex(failure, r"PDF/DOCX文本提取")
            self.assertRegex(failure, r"(?is)(?:does not generate|不生成).{0,80}(?:summary\.md|最终稿)")
            self.assertRegex(failure, r"(?is)(?:does not fall back|不回退).{0,80}(?:transcription|转写)")

    def test_legacy_root_transcript_is_only_a_compatibility_note(self) -> None:
        for path, text in self.read_documents().items():
            lines = text.splitlines()
            current_heading = ""
            for line_number, line in enumerate(lines, start=1):
                heading = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
                if heading:
                    current_heading = heading.group(1)
                if re.search(r"(?i)legacy root-level transcript\.txt", line):
                    self.assertIn(
                        "compat",
                        current_heading.lower(),
                        msg=f"{path}:{line_number} exposes legacy transcript in the main flow",
                    )

    def test_documents_do_not_commit_to_odt_or_rtf(self) -> None:
        for path, text in self.read_documents().items():
            self.assertNotRegex(text, r"(?i)(?:\.(?:odt|rtf)\b|\b(?:ODT|RTF)\b)")


if __name__ == "__main__":
    unittest.main()

