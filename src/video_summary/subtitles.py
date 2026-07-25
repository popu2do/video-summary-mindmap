from __future__ import annotations

import html
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .config import PREFERRED_LANGS, TEXT_EXTENSIONS, fail
from .storage import ensure_internal_dir, internal_path
from .transcript import coerce_seconds, normalize_segment_text, normalize_segments, normalize_text

def choose_subtitle(info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    subtitle_sets = [info.get("subtitles") or {}, info.get("automatic_captions") or {}]
    for subtitles in subtitle_sets:
        for lang in PREFERRED_LANGS:
            if lang in subtitles and subtitles[lang]:
                return lang, best_subtitle_format(subtitles[lang])
        for lang, entries in subtitles.items():
            if entries:
                return lang, best_subtitle_format(entries)
    return None

def best_subtitle_format(entries: list[dict[str, Any]]) -> dict[str, Any]:
    def score(entry: dict[str, Any]) -> int:
        ext = f".{entry.get('ext', '')}".lower()
        order = [".json", ".vtt", ".srt", ".txt", ".xml", ".ass", ".ssa"]
        return order.index(ext) if ext in order else 99

    return sorted(entries, key=score)[0]

def fetch_subtitle(entry: dict[str, Any], out_dir: Path, lang: str) -> Path:
    ensure_internal_dir(out_dir)
    url = entry.get("url")
    if not url:
        fail("字幕条目没有 URL。")
    ext = f".{entry.get('ext') or 'txt'}".lower()
    if ext not in TEXT_EXTENSIONS:
        ext = ".txt"
    target = internal_path(out_dir, f"subtitle.{lang}{ext}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target

def subtitle_to_text(path: Path) -> str:
    segments = parse_subtitle_segments(path)
    if segments:
        return normalize_text("\n".join(str(item["text"]) for item in segments if item.get("text")))
    raw = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json_subtitle_to_text(raw)
    if suffix in {".vtt", ".srt"}:
        return timed_text_to_plain(raw)
    if suffix in {".ass", ".ssa"}:
        return ass_to_plain(raw)
    if suffix == ".xml":
        text = re.sub(r"<[^>]+>", "\n", raw)
        return normalize_text(html.unescape(text))
    return normalize_text(raw)

def parse_subtitle_segments(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json_subtitle_to_segments(raw)
    if suffix in {".vtt", ".srt"}:
        return timed_text_to_segments(raw)
    return []

def parse_timestamp(value: str) -> float:
    text = value.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?", text)
    if not match:
        raise ValueError(value)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000

def timed_text_to_segments(raw: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    segments: list[dict[str, Any]] = []
    time_pattern = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{1,2}[,.]\d{1,3}\s+-->\s+(\d{1,2}:)?\d{1,2}:\d{1,2}[,.]\d{1,3}")
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line and time_pattern.search(line)), -1)
        if timing_index < 0:
            continue
        timing = lines[timing_index]
        start_raw, end_raw = timing.split("-->", 1)
        end_raw = end_raw.strip().split()[0]
        text = normalize_segment_text(" ".join(lines[timing_index + 1 :]))
        if text:
            segments.append({"start": parse_timestamp(start_raw.strip()), "end": parse_timestamp(end_raw), "text": text})
    return normalize_segments(segments)

def json_subtitle_to_segments(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    if isinstance(data, dict):
        for key in ("body", "segments", "events"):
            value = data.get(key)
            if isinstance(value, list):
                return normalize_segments([row for row in (json_item_to_segment(item) for item in value) if row])
    if isinstance(data, list):
        return normalize_segments([row for row in (json_item_to_segment(item) for item in data) if row])
    return []

def json_item_to_segment(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    text = item.get("content") or item.get("text") or item.get("utf8")
    segs = item.get("segs")
    if isinstance(segs, list):
        text = "".join(str(seg.get("utf8", "")) for seg in segs if isinstance(seg, dict))
    start_seconds = json_time_seconds(item, ("start", "from", "begin", "startTime", "start_time"), ("tStartMs",))
    end_seconds = json_time_seconds(item, ("end", "to", "finish", "endTime", "end_time"), ())
    duration_seconds = json_time_seconds(item, ("duration", "dur"), ("dDurationMs",))
    if end_seconds is None and start_seconds is not None and duration_seconds is not None:
        end_seconds = start_seconds + duration_seconds
    if text and start_seconds is not None:
        return {"start": start_seconds, "end": end_seconds, "text": str(text)}
    return None

def json_time_seconds(item: dict[str, Any], second_keys: tuple[str, ...], millisecond_keys: tuple[str, ...]) -> float | None:
    for key in millisecond_keys:
        if key in item and item[key] is not None:
            try:
                return float(item[key]) / 1000
            except (TypeError, ValueError):
                return None
    return coerce_seconds(first_present(item, second_keys))

def first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None

def json_subtitle_to_text(raw: str) -> str:
    segments = json_subtitle_to_segments(raw)
    if segments:
        return normalize_text("\n".join(str(item["text"]) for item in segments if item.get("text")))
    data = json.loads(raw)
    lines: list[str] = []
    if isinstance(data, dict):
        for key in ("body", "segments", "events"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        text = item.get("content") or item.get("text") or item.get("segs")
                        if isinstance(text, list):
                            text = "".join(str(seg.get("utf8", "")) for seg in text if isinstance(seg, dict))
                        if text:
                            lines.append(str(text))
                break
    return normalize_text("\n".join(lines) if lines else raw)

def timed_text_to_plain(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT":
            continue
        if "-->" in stripped or re.fullmatch(r"\d+", stripped):
            continue
        stripped = re.sub(r"<[^>]+>", "", stripped)
        lines.append(stripped)
    return normalize_text("\n".join(lines))

def ass_to_plain(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) == 10:
            text = re.sub(r"\{[^}]*\}", "", parts[-1])
            lines.append(text.replace("\\N", "\n"))
    return normalize_text("\n".join(lines))

def format_timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "00:00"
    seconds = int(value)
    if seconds >= 3600:
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
