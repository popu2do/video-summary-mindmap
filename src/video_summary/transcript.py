from __future__ import annotations

import hashlib
import html
import re
from typing import Any

from .config import ACTIVE_DOMAIN_REPLACEMENTS

def transcript_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def normalize_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_text = None
    for item in segments:
        text = normalize_segment_text(str(item.get("text") or ""))
        start = coerce_seconds(item.get("start"))
        end = coerce_seconds(item.get("end"))
        if not text or start is None or text == previous_text:
            continue
        row: dict[str, Any] = {"start": start, "end": end if end is not None else start, "text": text}
        result.append(row)
        previous_text = text
    return result

def normalize_segment_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = text.replace("\\N", " ")
    return re.sub(r"\s+", " ", text).strip()

def coerce_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000 if seconds > 100000 else seconds
    if isinstance(value, str) and value.strip():
        from .subtitles import parse_timestamp
        try:
            return parse_timestamp(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return None
    return None

def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    deduped: list[str] = []
    previous = None
    for line in lines:
        if line != previous:
            deduped.append(line)
        previous = line
    return "\n".join(deduped).strip()

def normalize_asr_text(text: str) -> str:
    for source, target in ACTIVE_DOMAIN_REPLACEMENTS.items():
        text = text.replace(source, target)
    return text

def load_segments_from_text(text: str) -> list[dict[str, Any]]:
    from .subtitles import parse_timestamp
    segments: list[dict[str, Any]] = []
    timed_line = re.compile(r"^\[(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<text>.+)$")
    for line in text.splitlines():
        match = timed_line.match(line.strip())
        if not match:
            continue
        try:
            start = parse_timestamp(match.group("time"))
        except ValueError:
            continue
        segments.append({"start": start, "end": start, "text": match.group("text")})
    return normalize_segments(segments)


def apply_domain_replacements_to_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not ACTIVE_DOMAIN_REPLACEMENTS:
        return segments
    updated: list[dict[str, Any]] = []
    for item in segments:
        row = dict(item)
        row["text"] = normalize_asr_text(str(row.get("text") or ""))
        updated.append(row)
    return normalize_segments(updated)
