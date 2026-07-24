from __future__ import annotations

from pathlib import Path

SUMMARY_FILENAME = "summary.md"
MINDMAP_FILENAME = "mindmap.mmd"
TRANSCRIPT_FILENAME = "transcript.txt"
SUPPORT_DIRNAME = "support"
TRANSCRIPT_RELATIVE_PATH = f"{SUPPORT_DIRNAME}/{TRANSCRIPT_FILENAME}"
SUMMARY_DRAFT_FILENAME = "summary_draft.md"
MINDMAP_DRAFT_FILENAME = "mindmap_draft.mmd"
METADATA_FILENAME = "metadata.json"
TRANSCRIPT_SEGMENTS_FILENAME = "transcript_segments.json"
TRANSCRIPT_TIMED_FILENAME = "transcript_timed.txt"
SUMMARY_CHUNKS_FILENAME = "summary_chunks.json"
AUDIO_FILENAME = "audio.mp3"
TRANSCRIPTION_FILENAME = "transcription.json"
LEGACY_SUMMARY_FILENAME = "summary_refined.md"
LEGACY_MINDMAP_FILENAME = "mindmap_refined.mmd"
SUBTITLE_GLOB = "subtitle.*"

REQUIRED_ROOT_DELIVERABLES = (SUMMARY_FILENAME,)
OPTIONAL_ROOT_DELIVERABLES = (MINDMAP_FILENAME,)
ROOT_DELIVERABLES = REQUIRED_ROOT_DELIVERABLES + OPTIONAL_ROOT_DELIVERABLES
DRAFT_OUTPUTS = (SUMMARY_DRAFT_FILENAME, MINDMAP_DRAFT_FILENAME)
INTERNAL_ARTIFACTS = (
    METADATA_FILENAME,
    TRANSCRIPT_SEGMENTS_FILENAME,
    TRANSCRIPT_TIMED_FILENAME,
    TRANSCRIPTION_FILENAME,
    SUMMARY_CHUNKS_FILENAME,
    AUDIO_FILENAME,
)
LEGACY_FINAL_OUTPUTS = (LEGACY_SUMMARY_FILENAME, LEGACY_MINDMAP_FILENAME)
LEGACY_ROOT_ARTIFACTS = INTERNAL_ARTIFACTS + LEGACY_FINAL_OUTPUTS
ARCHIVED_OUTPUTS = ROOT_DELIVERABLES + LEGACY_FINAL_OUTPUTS

OUTPUT_FILE_ROLES = {
    "core_delivery": ROOT_DELIVERABLES,
    "supporting_material": (TRANSCRIPT_RELATIVE_PATH,),
    "optional_derived": DRAFT_OUTPUTS + (TRANSCRIPT_SEGMENTS_FILENAME, TRANSCRIPT_TIMED_FILENAME),
    "intermediate_cache": (
        METADATA_FILENAME,
        SUMMARY_CHUNKS_FILENAME,
        AUDIO_FILENAME,
        TRANSCRIPTION_FILENAME,
    ),
}

INTERNAL_DIRNAME = "_internal"
PREVIOUS_FINAL_DIRNAME = "previous_final"


def support_dir(out_dir: Path) -> Path:
    path = out_dir / SUPPORT_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_path(out_dir: Path) -> Path:
    return support_dir(out_dir) / TRANSCRIPT_FILENAME


def legacy_transcript_path(out_dir: Path) -> Path:
    return out_dir / TRANSCRIPT_FILENAME


def internal_dir(out_dir: Path) -> Path:
    path = out_dir / INTERNAL_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def internal_path(out_dir: Path, filename: str) -> Path:
    return internal_dir(out_dir) / filename


def previous_final_dir(out_dir: Path) -> Path:
    path = internal_dir(out_dir) / PREVIOUS_FINAL_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path
