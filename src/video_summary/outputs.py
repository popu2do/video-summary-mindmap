from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import ANALYSIS_SCOPE_NOTE
from .mermaid import build_mermaid
from .storage import (
    ARCHIVED_OUTPUTS,
    EPHEMERAL_INTERNAL_ARTIFACTS,
    RUN_ARTIFACTS,
    LEGACY_FINAL_OUTPUTS,
    ROOT_DELIVERABLES,
    REQUIRED_ROOT_DELIVERABLES,
    INTERNAL_DIRNAME,
    SUPPORT_DIRNAME,
    SUMMARY_DRAFT_FILENAME,
    SUMMARY_FILENAME,
    TRANSCRIPT_FILENAME,
    SUBTITLE_GLOB,
    OUTPUT_FILE_ROLES,
    internal_path,
    ensure_internal_dir,
    previous_final_dir,
)
from .subtitles import format_timestamp
from .sources import is_document_source, safe_display_name, source_origin_label
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


def archive_previous_final_outputs(out_dir: Path, workspace_dir: Path | None = None) -> None:
    """Copy known previous finals to a private run workspace when requested."""
    if workspace_dir is None:
        return
    existing = [out_dir / filename for filename in ARCHIVED_OUTPUTS if (out_dir / filename).is_file()]
    if not existing:
        return

    archive_dir = workspace_dir / "previous_final"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for source in existing:
        (archive_dir / source.name).write_bytes(source.read_bytes())


def _is_symlink_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _cleanup_root(out_dir: Path) -> Path | None:
    if _is_symlink_or_junction(out_dir):
        return None
    return out_dir.resolve(strict=False)


def _is_safe_cleanup_target(path: Path, source_root: Path) -> bool:
    if _is_symlink_or_junction(path):
        return False
    try:
        path.resolve(strict=False).relative_to(source_root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _unlink_file(path: Path, source_root: Path) -> None:
    if not _is_safe_cleanup_target(path, source_root):
        return
    if path.is_file():
        path.unlink(missing_ok=True)


def _remove_if_empty(path: Path, source_root: Path) -> None:
    if not _is_safe_cleanup_target(path, source_root):
        return
    try:
        path.rmdir()
    except OSError:
        pass


def _clear_known_output_artifacts(out_dir: Path) -> None:
    """Remove only explicitly named artifacts produced by older tool runs."""
    source_root = _cleanup_root(out_dir)
    if source_root is None:
        return

    root_files = (
        TRANSCRIPT_FILENAME,
        *RUN_ARTIFACTS,
        *LEGACY_FINAL_OUTPUTS,
    )
    for filename in root_files:
        _unlink_file(out_dir / filename, source_root)
    for path in out_dir.glob(SUBTITLE_GLOB):
        _unlink_file(path, source_root)

    support = out_dir / SUPPORT_DIRNAME
    _unlink_file(support / TRANSCRIPT_FILENAME, source_root)
    _remove_if_empty(support, source_root)

    internal = out_dir / INTERNAL_DIRNAME
    for filename in RUN_ARTIFACTS:
        _unlink_file(internal / filename, source_root)
    previous = previous_final_dir(out_dir)
    for filename in ARCHIVED_OUTPUTS:
        _unlink_file(previous / filename, source_root)
    _remove_if_empty(previous, source_root)
    _remove_if_empty(internal, source_root)


def clear_previous_final_outputs(out_dir: Path) -> None:
    """Clean known historical artifacts without touching unknown user files."""
    _clear_known_output_artifacts(out_dir)


def output_contract_lines(out_dir: Path) -> list[str]:
    lines: list[str] = []
    for role, filenames in OUTPUT_FILE_ROLES.items():
        present = [filename for filename in filenames if (out_dir / filename).exists()]
        lines.append(f"{OUTPUT_ROLE_LABELS[role]}：")
        lines.extend(f"- {filename}" for filename in present)
        if not present:
            lines.append("- 无（按需生成）")
    return lines


def final_delivery_ready(out_dir: Path) -> bool:
    if not out_dir.is_dir():
        return False
    for filename in ROOT_DELIVERABLES:
        path = out_dir / filename
        if path.is_file() and not path.read_text(encoding="utf-8", errors="ignore").strip():
            return False
    return (out_dir / SUMMARY_FILENAME).is_file()


def migrate_root_subtitles(out_dir: Path) -> None:
    """Remove explicitly named legacy subtitle files; never create output internals."""
    source_root = _cleanup_root(out_dir)
    if source_root is None:
        return
    for path in out_dir.glob(SUBTITLE_GLOB):
        _unlink_file(path, source_root)


def migrate_root_internal_files(out_dir: Path) -> None:
    """Clean explicitly named legacy internals without moving unknown files."""
    _clear_known_output_artifacts(out_dir)


def prepare_output_directory(
    out_dir: Path,
    reuse_transcript: bool = False,
    ensure_layout: bool = True,
) -> None:
    """Prepare a delivery directory while preserving unknown user files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_known_output_artifacts(out_dir)


def clear_ephemeral_internal_artifacts(out_dir: Path) -> None:
    """Remove internal files that have no consumer after a run stage."""
    source_root = _cleanup_root(out_dir)
    if source_root is None:
        return
    for filename in EPHEMERAL_INTERNAL_ARTIFACTS:
        _unlink_file(internal_path(out_dir, filename), source_root)
        _unlink_file(out_dir / filename, source_root)


def build_abstract(
    key_points: list[str],
    chapters: list[dict[str, Any]],
    content_label: str = "视频",
) -> str:
    seeds = key_points[:3] or [chapter["summary"] for chapter in chapters[:3]]
    text = "；".join(trim_sentence(seed, 80) for seed in seeds if seed)
    return text + "。" if text else f"本{content_label}围绕核心主题展开，建议结合依据材料进一步精校。"


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
    content_label = "文档" if is_document_source(source) else "视频"
    abstract = build_abstract(key_points, chapters, content_label)
    lines = [
        f"# {content_label}精校总结：{title}", "", "## 元信息", f"- 来源：{source}",
        f"- 作者：{author}", f"- 时长：{format_duration(duration)}",
        f"- 文稿来源：{source_origin_label(source, subtitle_lang)}",
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
    lines.extend(["", "---", "", f"## {content_label}章节总结 ｜ {title}", "", abstract])
    for index, chapter in enumerate(chapters, 1):
        time_label = format_timestamp(chapter.get("time")) if chapter.get("time") is not None else f"章节 {index}"
        lines.extend(["", f"### [{time_label}] - {chapter['title']}", "", chapter["summary"]])
    sections = [chapter["summary"] for chapter in chapters]
    lines.extend(["", "---", "", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    return lines


def write_outputs(info: dict[str, Any], source: str, out_dir: Path, transcript: str, subtitle_lang: str | None, template: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_internal_dir(out_dir)
    title = str(info.get("title") or ("未命名文档" if is_document_source(source) else "未命名视频"))
    author = str(info.get("uploader") or info.get("channel") or "未知")
    display_name = safe_display_name(source, info)
    duration = info.get("duration")
    key_points = pick_key_sentences(transcript, 10)
    terms = keywords(transcript, 12)
    chapters = chapterize_from_files(out_dir, transcript, 6)
    sections = [chapter["summary"] for chapter in chapters] or chunk_summary(transcript, 6)

    clear_ephemeral_internal_artifacts(out_dir)

    if template == "refined":
        summary_lines = build_refined_summary(title, display_name, author, duration, subtitle_lang, transcript, key_points, terms, chapters)
    else:
        summary_lines = [
            f"# {title}", "", "## 元信息", f"- 来源：{display_name}", f"- 作者：{author}",
            f"- 时长：{format_duration(duration)}", f"- 字幕语言：{source_origin_label(source, subtitle_lang)}",
            f"- 分析范围：{ANALYSIS_SCOPE_NOTE}", "", "## 核心摘要",
        ]
        summary_lines.extend(f"- {item}" for item in key_points[:5])
        summary_lines.extend(["", "## 分段大纲"])
        summary_lines.extend(f"{index}. {item}" for index, item in enumerate(sections, 1))
        summary_lines.extend(["", "## 关键观点"])
        summary_lines.extend(f"- {item}" for item in key_points[5:] or key_points[:5])
        summary_lines.extend(["", "## 高频术语", "、".join(terms) if terms else "未识别", "", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    internal_path(out_dir, SUMMARY_DRAFT_FILENAME).write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
