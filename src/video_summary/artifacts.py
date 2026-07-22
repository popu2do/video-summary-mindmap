from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .subtitles import format_timestamp
from .transcript import (
    transcript_sha256,
    apply_domain_replacements_to_segments,
    load_segments_from_text,
    normalize_segments,
)

def write_transcript_artifacts(
    out_dir: Path,
    transcript: str,
    segments: list[dict[str, Any]] | None,
    meta: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    segment_paths = (out_dir / "transcript_segments.json", out_dir / "transcript_timed.txt")
    if segments:
        clean_segments = normalize_segments(segments)
        (out_dir / "transcript_segments.json").write_text(
            json.dumps(clean_segments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "transcript_timed.txt").write_text(
            "\n".join(f"[{format_timestamp(row['start'])}] {row['text']}" for row in clean_segments) + "\n",
            encoding="utf-8",
        )
    else:
        for segment_path in segment_paths:
            segment_path.unlink(missing_ok=True)
    if meta is not None:
        metadata = dict(meta)
        metadata["transcript_sha256"] = transcript_sha256(transcript)
        (out_dir / "transcription.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

def _transcript_cache_is_current(out_dir: Path, transcript: str) -> bool:
    metadata_path = out_dir / "metadata.json"
    if not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(metadata, dict) and metadata.get("transcript_sha256") == transcript_sha256(transcript)

def _clear_transcript_derived_cache(out_dir: Path) -> None:
    for filename in (
        "transcript_segments.json",
        "transcript_timed.txt",
        "summary_chunks.json",
        "transcription.json",
        "summary_refined.md",
        "mindmap_refined.mmd",
    ):
        (out_dir / filename).unlink(missing_ok=True)

def refresh_existing_segment_artifacts(out_dir: Path, transcript: str) -> None:
    if not _transcript_cache_is_current(out_dir, transcript):
        _clear_transcript_derived_cache(out_dir)
        write_transcript_artifacts(out_dir, transcript, load_segments_from_text(transcript))
        return

    segments_path = out_dir / "transcript_segments.json"
    if not segments_path.exists():
        write_transcript_artifacts(out_dir, transcript, load_segments_from_text(transcript))
        return
    try:
        data = json.loads(segments_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        write_transcript_artifacts(out_dir, transcript, load_segments_from_text(transcript))
        return
    write_transcript_artifacts(
        out_dir,
        transcript,
        apply_domain_replacements_to_segments(data) if isinstance(data, list) else load_segments_from_text(transcript),
    )

def load_existing_chunk_summaries(out_dir: Path) -> list[dict[str, Any]]:
    path = out_dir / "summary_chunks.json"
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
    sorted_items = sorted(chunk_summaries, key=lambda item: int(item.get("index", 0)))
    (out_dir / "summary_chunks.json").write_text(json.dumps(sorted_items, ensure_ascii=False, indent=2), encoding="utf-8")

def read_segments_file(out_dir: Path) -> list[dict[str, Any]]:
    segments_path = out_dir / "transcript_segments.json"
    if not segments_path.exists():
        return []
    try:
        data = json.loads(segments_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return normalize_segments(data) if isinstance(data, list) else []
