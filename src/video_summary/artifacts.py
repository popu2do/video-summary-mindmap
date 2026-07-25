from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import (
    LEGACY_ROOT_ARTIFACTS,
    SUMMARY_CHUNKS_FILENAME,
    TRANSCRIPT_FILENAME,
    TRANSCRIPT_SEGMENTS_FILENAME,
    ensure_internal_dir,
    ensure_support_dir,
    internal_path,
    legacy_transcript_path,
    transcript_path,
)
from .transcript import load_segments_from_text, normalize_segments


def _remove_legacy_root_artifacts(out_dir: Path) -> None:
    for filename in LEGACY_ROOT_ARTIFACTS:
        (out_dir / filename).unlink(missing_ok=True)


def write_transcript_artifacts(
    out_dir: Path,
    transcript: str,
    segments: list[dict[str, Any]] | None,
    meta: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_support_dir(out_dir)
    ensure_internal_dir(out_dir)
    _remove_legacy_root_artifacts(out_dir)
    transcript_path(out_dir).write_text(transcript, encoding="utf-8")
    legacy_transcript_path(out_dir).unlink(missing_ok=True)
    segments_path = internal_path(out_dir, TRANSCRIPT_SEGMENTS_FILENAME)
    if segments:
        clean_segments = normalize_segments(segments)
        segments_path.write_text(json.dumps(clean_segments, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        segments_path.unlink(missing_ok=True)


def refresh_existing_segment_artifacts(out_dir: Path, transcript: str) -> None:
    """Rebuild derived transcript files from the current support transcript only."""
    write_transcript_artifacts(out_dir, transcript, load_segments_from_text(transcript))


def load_existing_chunk_summaries(out_dir: Path) -> list[dict[str, Any]]:
    path = internal_path(out_dir, SUMMARY_CHUNKS_FILENAME)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    result: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("index"), int) and isinstance(item.get("summary"), str):
            result.append(item)
    return result


def write_chunk_summaries(out_dir: Path, chunk_summaries: list[dict[str, Any]]) -> None:
    ensure_internal_dir(out_dir)
    sorted_items = sorted(chunk_summaries, key=lambda item: int(item.get("index", 0)))
    internal_path(out_dir, SUMMARY_CHUNKS_FILENAME).write_text(
        json.dumps(sorted_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_segments_file(out_dir: Path) -> list[dict[str, Any]]:
    segments_path = internal_path(out_dir, TRANSCRIPT_SEGMENTS_FILENAME)
    if not segments_path.exists():
        return []
    try:
        data = json.loads(segments_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return normalize_segments(data) if isinstance(data, list) else []
