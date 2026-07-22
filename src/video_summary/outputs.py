from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ANALYSIS_BASIS, ANALYSIS_SCOPE_NOTE
from .mermaid import build_mermaid
from .subtitles import format_timestamp
from .transcript import transcript_sha256
from .summarization import (
    chapterize,
    chapterize_from_files,
    chunk_summary,
    keywords,
    pick_key_sentences,
    trim_sentence,
)

OUTPUT_ROLE_LABELS = {
    "core_delivery": "核心交付",
    "optional_derived": "可选派生",
    "intermediate_cache": "中间缓存",
}

OUTPUT_FILE_ROLES = {
    "core_delivery": ("transcript.txt", "summary.md", "mindmap.mmd", "metadata.json"),
    "optional_derived": (
        "transcript_segments.json",
        "transcript_timed.txt",
        "summary_refined.md",
        "mindmap_refined.mmd",
    ),
    "intermediate_cache": ("summary_chunks.json", "audio.mp3", "transcription.json"),
}

def output_contract_lines(out_dir: Path) -> list[str]:
    lines: list[str] = []
    for role, filenames in OUTPUT_FILE_ROLES.items():
        present = [filename for filename in filenames if (out_dir / filename).exists()]
        lines.append(f"{OUTPUT_ROLE_LABELS[role]}：")
        lines.extend(f"- {filename}" for filename in present)
        if not present:
            lines.append("- 无（按需生成）")
    return lines

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
        f"# 视频精校总结：{title}",
        "",
        "## 元信息",
        f"- 来源：{source}",
        f"- 作者：{author}",
        f"- 时长：{format_duration(duration)}",
        f"- 文稿来源：{subtitle_lang or '无字幕，本地转写'}",
        f"- 分析范围：{ANALYSIS_SCOPE_NOTE}",
        "",
        "## 摘要",
        abstract,
        "",
        "### 亮点",
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
    lines.extend(["", "---", "", "## 口播逐字稿", "", transcript])
    return lines

def write_outputs(info: dict[str, Any], source: str, out_dir: Path, transcript: str, subtitle_lang: str | None, template: str) -> None:
    title = str(info.get("title") or "未命名视频")
    author = str(info.get("uploader") or info.get("channel") or "未知")
    duration = info.get("duration")
    key_points = pick_key_sentences(transcript, 10)
    terms = keywords(transcript, 12)
    chapters = chapterize_from_files(out_dir, transcript, 6)
    sections = [chapter["summary"] for chapter in chapters] or chunk_summary(transcript, 6)

    metadata = {
        "source": source,
        "title": title,
        "author": author,
        "duration": duration,
        "subtitle_language": subtitle_lang,
        "analysis_basis": ANALYSIS_BASIS,
        "word_count": len(transcript),
        "transcript_sha256": transcript_sha256(transcript),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

    if template == "refined":
        summary_lines = build_refined_summary(title, source, author, duration, subtitle_lang, transcript, key_points, terms, chapters)
    else:
        summary_lines = [
            f"# {title}",
            "",
            "## 元信息",
            f"- 来源：{source}",
            f"- 作者：{author}",
            f"- 时长：{format_duration(duration)}",
            f"- 字幕语言：{subtitle_lang or '无字幕，使用转写'}",
            f"- 分析范围：{ANALYSIS_SCOPE_NOTE}",
            "",
            "## 核心摘要",
        ]
        summary_lines.extend(f"- {item}" for item in key_points[:5])
        summary_lines.extend(["", "## 分段大纲"])
        summary_lines.extend(f"{index}. {item}" for index, item in enumerate(sections, 1))
        summary_lines.extend(["", "## 关键观点"])
        summary_lines.extend(f"- {item}" for item in key_points[5:] or key_points[:5])
        summary_lines.extend(["", "## 高频术语"])
        summary_lines.append("、".join(terms) if terms else "未识别")
        summary_lines.extend(["", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    (out_dir / "summary.md").write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
    (out_dir / "mindmap.mmd").write_text(build_mermaid(title, sections, key_points, terms) + "\n", encoding="utf-8")
