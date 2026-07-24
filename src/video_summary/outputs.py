from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import ANALYSIS_BASIS, ANALYSIS_SCOPE_NOTE
from .mermaid import build_mermaid
from .storage import (
    ARCHIVED_OUTPUTS,
    DRAFT_OUTPUTS,
    INTERNAL_ARTIFACTS,
    LEGACY_FINAL_OUTPUTS,
    METADATA_FILENAME,
    MINDMAP_DRAFT_FILENAME,
    ROOT_DELIVERABLES,
    REQUIRED_ROOT_DELIVERABLES,
    INTERNAL_DIRNAME,
    SUPPORT_DIRNAME,
    SUMMARY_CHUNKS_FILENAME,
    SUMMARY_DRAFT_FILENAME,
    TRANSCRIPT_RELATIVE_PATH,
    legacy_transcript_path,
    transcript_path,
    SUBTITLE_GLOB,
    OUTPUT_FILE_ROLES,
    internal_path,
    previous_final_dir,
)
from .subtitles import format_timestamp
from .sources import safe_display_name
from .summarization import (
    chapterize_from_files,
    chunk_summary,
    keywords,
    pick_key_sentences,
    trim_sentence,
)

OUTPUT_ROLE_LABELS = {
    "core_delivery": "核心交付",
    "supporting_material": "依据材料/支持材料",
    "optional_derived": "内部派生",
    "intermediate_cache": "内部缓存",
}

FINAL_OUTPUTS = ROOT_DELIVERABLES
REQUIRED_FINAL_OUTPUTS = REQUIRED_ROOT_DELIVERABLES
_ALLOWED_ROOT_DIRECTORIES = {SUPPORT_DIRNAME, INTERNAL_DIRNAME}


def archive_previous_final_outputs(out_dir: Path) -> None:
    existing = [out_dir / filename for filename in ARCHIVED_OUTPUTS if (out_dir / filename).is_file()]
    if not existing:
        return

    archive_dir = previous_final_dir(out_dir)
    moved: list[tuple[Path, Path]] = []
    try:
        for source in existing:
            target = archive_dir / source.name
            os.replace(source, target)
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            if target.exists():
                os.replace(target, source)
        raise


def _clear_root_non_delivery_files(out_dir: Path) -> None:
    for path in out_dir.iterdir():
        if path.name in ROOT_DELIVERABLES and path.is_file():
            continue
        if path.name in _ALLOWED_ROOT_DIRECTORIES and path.is_dir():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.is_file() or path.is_symlink():
            path.unlink()


def clear_previous_final_outputs(out_dir: Path) -> None:
    archive_dir = out_dir / "_internal" / "previous_final"
    if archive_dir.is_dir():
        for filename in ARCHIVED_OUTPUTS:
            (archive_dir / filename).unlink(missing_ok=True)
        try:
            archive_dir.rmdir()
        except OSError:
            pass
    _clear_root_non_delivery_files(out_dir)


def output_contract_lines(out_dir: Path) -> list[str]:
    lines: list[str] = []
    for role, filenames in OUTPUT_FILE_ROLES.items():
        base = out_dir if role in {"core_delivery", "supporting_material"} else out_dir / "_internal"
        present = [filename for filename in filenames if (base / filename).exists()]
        lines.append(f"{OUTPUT_ROLE_LABELS[role]}：")
        root_role = role in {"core_delivery", "supporting_material"}
        lines.extend(
            f"- {filename if root_role else '_internal/' + filename}"
            for filename in present
        )
        if not present:
            lines.append("- 无（按需生成）")
    return lines


def final_delivery_ready(out_dir: Path) -> bool:
    if not out_dir.is_dir():
        return False
    allowed_entries = set(ROOT_DELIVERABLES) | _ALLOWED_ROOT_DIRECTORIES
    for path in out_dir.iterdir():
        if path.name not in allowed_entries:
            return False
        if path.name in ROOT_DELIVERABLES and not path.is_file():
            return False
        if path.name in _ALLOWED_ROOT_DIRECTORIES and not path.is_dir():
            return False
    for filename in ROOT_DELIVERABLES:
        path = out_dir / filename
        if path.is_file() and not path.read_text(encoding="utf-8", errors="ignore").strip():
            return False
    for filename in REQUIRED_FINAL_OUTPUTS:
        if not (out_dir / filename).is_file():
            return False
    return True


def migrate_root_subtitles(out_dir: Path) -> None:
    root_subtitles = [path for path in out_dir.glob(SUBTITLE_GLOB) if path.is_file()]
    if not root_subtitles:
        return

    moved: list[tuple[Path, Path]] = []
    try:
        for source in root_subtitles:
            target = internal_path(out_dir, source.name)
            os.replace(source, target)
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            if target.exists():
                os.replace(target, source)
        raise


def migrate_root_internal_files(out_dir: Path) -> None:
    """Hide legacy root drafts and artifacts before any later stage can fail."""
    moved: list[tuple[Path, Path]] = []
    for filename in DRAFT_OUTPUTS + INTERNAL_ARTIFACTS:
        source = out_dir / filename
        if not source.is_file():
            continue
        target = internal_path(out_dir, filename)
        if target.exists():
            source.unlink()
            continue
        try:
            os.replace(source, target)
            moved.append((source, target))
        except Exception:
            for original, migrated in reversed(moved):
                if migrated.exists():
                    os.replace(migrated, original)
            raise


def prepare_output_directory(out_dir: Path, reuse_transcript: bool = False) -> None:
    """Start a run with only explicitly reusable material left in place."""
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_previous_final_outputs(out_dir)
    migrate_root_subtitles(out_dir)

    # Derived files describe the previous run, so never carry them into a new
    # run.  The current transcript is the sole exception when reuse is
    # explicitly requested; it will be used to rebuild all derived files.
    stale_artifacts = DRAFT_OUTPUTS + INTERNAL_ARTIFACTS
    for filename in stale_artifacts:
        (out_dir / filename).unlink(missing_ok=True)
        internal_path(out_dir, filename).unlink(missing_ok=True)
    if not reuse_transcript:
        transcript_path(out_dir).unlink(missing_ok=True)
        legacy_transcript_path(out_dir).unlink(missing_ok=True)


def build_abstract(key_points: list[str], chapters: list[dict[str, Any]]) -> str:
    seeds = key_points[:3] or [chapter["summary"] for chapter in chapters[:3]]
    text = "；".join(trim_sentence(seed, 80) for seed in seeds if seed)
    return text + "。" if text else "本视频围绕核心主题展开，建议结合逐字稿进一步精校。"


def build_questions(terms: list[str], key_points: list[str]) -> list[str]:
    first = terms[0] if terms else "核心概念"
    second = terms[1] if len(terms) > 1 else "实践方法"
    third = terms[2] if len(terms) > 2 else "认知误区"
    return [
        f"{first}真正解决的是什么问题？",
        f"{second}在实际场景中应该如何判断和使用？",
        f"哪些{third}会导致行动偏差？",
    ][: max(2, min(3, len(key_points) or 2))]


def explain_term(term: str, key_points: list[str], chapters: list[dict[str, Any]]) -> str:
    corpus = key_points + [chapter["summary"] for chapter in chapters]
    for item in corpus:
        if term in item:
            return trim_sentence(item, 110)
    return "文稿中的高频概念，建议结合上下文进一步人工精校。"


def format_time_suffix(chapters: list[dict[str, Any]], index: int) -> str:
    if not chapters:
        return ""
    chapter = chapters[min(index, len(chapters) - 1)]
    value = chapter.get("time")
    return f" [{format_timestamp(value)}]" if value is not None else ""


def format_duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "未知"
    seconds = int(value)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def build_refined_summary(
    title: str,
    source: str,
    author: str,
    duration: Any,
    subtitle_lang: str | None,
    transcript: str,
    key_points: list[str],
    terms: list[str],
    chapters: list[dict[str, Any]],
) -> list[str]:
    abstract = build_abstract(key_points, chapters)
    lines = [
        f"# 视频精校总结：{title}", "", "## 元信息", f"- 来源：{source}",
        f"- 作者：{author}", f"- 时长：{format_duration(duration)}",
        f"- 文稿来源：{subtitle_lang or '无字幕，本地转写'}",
        f"- 分析范围：{ANALYSIS_SCOPE_NOTE}", "", "## 摘要", abstract, "", "### 亮点",
    ]
    lines.extend(f"- {trim_sentence(point, 92)}{format_time_suffix(chapters, index)}" for index, point in enumerate(key_points[:5]))
    lines.extend(["", "### 思考"])
    for index, question in enumerate(build_questions(terms, key_points), 1):
        lines.append(f"{index}. **{question}**")
        answer = key_points[index - 1] if index - 1 < len(key_points) else abstract
        lines.append(f"   - {trim_sentence(answer, 120)}")
    lines.extend(["", "### 术语解释"])
    for term in terms[:6]:
        lines.append(f"- **{term}**：{explain_term(term, key_points, chapters)}")
    lines.extend(["", "---", "", f"## 视频章节总结 ｜ {title}", "", abstract])
    for index, chapter in enumerate(chapters, 1):
        time_label = format_timestamp(chapter.get("time")) if chapter.get("time") is not None else f"章节 {index}"
        lines.extend(["", f"### [{time_label}] - {chapter['title']}", "", chapter["summary"]])
    sections = [chapter["summary"] for chapter in chapters]
    lines.extend(["", "---", "", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    return lines


def write_outputs(info: dict[str, Any], source: str, out_dir: Path, transcript: str, subtitle_lang: str | None, template: str) -> None:
    title = str(info.get("title") or "未命名视频")
    author = str(info.get("uploader") or info.get("channel") or "未知")
    display_name = safe_display_name(source, info)
    duration = info.get("duration")
    key_points = pick_key_sentences(transcript, 10)
    terms = keywords(transcript, 12)
    chapters = chapterize_from_files(out_dir, transcript, 6)
    sections = [chapter["summary"] for chapter in chapters] or chunk_summary(transcript, 6)

    metadata = {
        "source": display_name,
        "display_name": display_name,
        "title": title,
        "author": author,
        "duration": duration,
        "subtitle_language": subtitle_lang,
        "analysis_basis": ANALYSIS_BASIS,
        "word_count": len(transcript),
    }
    internal_path(out_dir, METADATA_FILENAME).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    if template == "refined":
        summary_lines = build_refined_summary(title, display_name, author, duration, subtitle_lang, transcript, key_points, terms, chapters)
    else:
        summary_lines = [
            f"# {title}", "", "## 元信息", f"- 来源：{display_name}", f"- 作者：{author}",
            f"- 时长：{format_duration(duration)}", f"- 字幕语言：{subtitle_lang or '无字幕，使用转写'}",
            f"- 分析范围：{ANALYSIS_SCOPE_NOTE}", "", "## 核心摘要",
        ]
        summary_lines.extend(f"- {item}" for item in key_points[:5])
        summary_lines.extend(["", "## 分段大纲"])
        summary_lines.extend(f"{index}. {item}" for index, item in enumerate(sections, 1))
        summary_lines.extend(["", "## 关键观点"])
        summary_lines.extend(f"- {item}" for item in key_points[5:] or key_points[:5])
        summary_lines.extend(["", "## 高频术语", "、".join(terms) if terms else "未识别", "", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    internal_path(out_dir, SUMMARY_DRAFT_FILENAME).write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
    internal_path(out_dir, MINDMAP_DRAFT_FILENAME).write_text(build_mermaid(title, sections, key_points, terms) + "\n", encoding="utf-8")
