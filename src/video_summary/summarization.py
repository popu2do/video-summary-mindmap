from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .artifacts import read_segments_file
from .mermaid import mindmap_text
from .config import ACTIVE_DOMAIN_TERMS, ANALYSIS_SCOPE_NOTE, STOP_WORDS
from .transcript import load_segments_from_text
from .storage import TRANSCRIPT_SEGMENTS_FILENAME, internal_path

def split_sentences(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    units: list[str] = []
    buffer: list[str] = []
    buffer_len = 0
    for line in lines:
        buffer.append(line)
        buffer_len += len(line)
        if buffer_len >= 70 or re.search(r"[。！？!?；;.]$", line):
            units.append(" ".join(buffer))
            buffer = []
            buffer_len = 0
    if buffer:
        units.append(" ".join(buffer))

    parts: list[str] = []
    for unit in units or [text]:
        parts.extend(re.split(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+", unit))
    return [part.strip() for part in parts if len(part.strip()) >= 12]

def pick_key_sentences(text: str, limit: int = 10) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    freq: dict[str, int] = {}
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", text):
        freq[token.lower()] = freq.get(token.lower(), 0) + 1

    def score(sentence: str) -> float:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", sentence)
        if not tokens:
            return 0
        return sum(freq.get(token.lower(), 0) for token in tokens) / max(len(tokens), 1)

    selected = sorted(enumerate(sentences), key=lambda item: score(item[1]), reverse=True)[:limit]
    return [sentences[index] for index, _ in sorted(selected)]

def chunk_summary(text: str, chunks: int = 6) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    size = max(1, len(sentences) // chunks)
    result: list[str] = []
    for start in range(0, len(sentences), size):
        group = sentences[start : start + size]
        if group:
            result.append(group[0])
        if len(result) >= chunks:
            break
    return result

def keywords(text: str, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for token in candidate_terms(text):
        lowered = token.lower()
        if lowered in {"https", "www", "com"} or token in STOP_WORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    return [word for word, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]

def candidate_terms(text: str) -> list[str]:
    terms: list[str] = []
    for pattern in ACTIVE_DOMAIN_TERMS:
        terms.extend([pattern] * text.count(pattern))
    terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text))
    return terms

def chapterize(text: str, chapters: int = 6) -> list[dict[str, Any]]:
    timed = load_segments_from_text(text)
    if timed:
        return chapterize_segments(timed, chapters)
    units = split_sentences(text)
    if not units:
        return []
    size = max(1, len(units) // chapters)
    result: list[dict[str, Any]] = []
    for chapter_index, start in enumerate(range(0, len(units), size), 1):
        group = units[start : start + size]
        if not group:
            continue
        result.append({
            "time": None,
            "title": infer_heading(group),
            "summary": summarize_group(group),
            "items": group[:3],
        })
        if len(result) >= chapters:
            break
    return result

def chapterize_segments(segments: list[dict[str, Any]], chapters: int) -> list[dict[str, Any]]:
    size = max(1, len(segments) // chapters)
    result: list[dict[str, Any]] = []
    for start in range(0, len(segments), size):
        group = segments[start : start + size]
        texts = [str(item["text"]) for item in group if item.get("text")]
        if not texts:
            continue
        result.append({
            "time": group[0].get("start"),
            "title": infer_heading(texts),
            "summary": summarize_group(texts),
            "items": texts[:3],
        })
        if len(result) >= chapters:
            break
    return result

def infer_heading(items: list[str]) -> str:
    joined = " ".join(items[:3])
    terms = keywords(joined, 3)
    if terms:
        return "、".join(terms[:2])
    return mindmap_text(items[0], 22)

def summarize_group(items: list[str]) -> str:
    text = " ".join(items)
    picked = pick_key_sentences(text, 2)
    if picked:
        return "。".join(trim_sentence(item, 90) for item in picked) + "。"
    return trim_sentence(text, 160)

def trim_sentence(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]

def resolve_content_type(value: str, info: dict[str, Any], source: str) -> str:
    if value != "auto":
        return value
    title = str(info.get("title") or "")
    source_lower = source.lower()
    lecture_markers = ("课", "课程", "第", "节", "理论", "训练", "workshop", "lecture", "lesson", "course")
    if any(marker in title.lower() or marker in source_lower for marker in lecture_markers):
        return "lecture"
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration >= 1800:
        return "lecture"
    return "video"

def chapterize_from_files(out_dir: Path, transcript: str, chapters: int) -> list[dict[str, Any]]:
    segments_path = internal_path(out_dir, TRANSCRIPT_SEGMENTS_FILENAME)
    if segments_path.exists():
        try:
            data = json.loads(segments_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return chapterize_segments(data, chapters)
        except json.JSONDecodeError:
            pass
    return chapterize(transcript, chapters)
