from __future__ import annotations

from pathlib import Path

SUMMARY_FILENAME = "summary.md"
MINDMAP_FILENAME = "mindmap.mmd"
TRANSCRIPT_FILENAME = "transcript.txt"
SUPPORT_DIRNAME = "support"
TRANSCRIPT_RELATIVE_PATH = f"{SUPPORT_DIRNAME}/{TRANSCRIPT_FILENAME}"
SUMMARY_DRAFT_FILENAME = "summary_draft.md"
# Kept as a legacy name so old files can be cleaned safely; the pipeline no
# longer generates this draft because nothing consumes it.
MINDMAP_DRAFT_FILENAME = "mindmap_draft.mmd"
# Kept as legacy cleanup names; these files have no current consumers.
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

# Only these internal files have a current consumer during the workflow.
DRAFT_OUTPUTS = (SUMMARY_DRAFT_FILENAME,)
INTERNAL_ARTIFACTS = (TRANSCRIPT_SEGMENTS_FILENAME,)

# These names are retained solely so old runs are cleaned and never mistaken
# for current output. They are not part of the active output contract.
EPHEMERAL_INTERNAL_ARTIFACTS = (
    MINDMAP_DRAFT_FILENAME,
    METADATA_FILENAME,
    TRANSCRIPT_TIMED_FILENAME,
    TRANSCRIPTION_FILENAME,
    SUMMARY_CHUNKS_FILENAME,
    AUDIO_FILENAME,
)
ALL_INTERNAL_ARTIFACTS = INTERNAL_ARTIFACTS + EPHEMERAL_INTERNAL_ARTIFACTS
RUN_ARTIFACTS = DRAFT_OUTPUTS + ALL_INTERNAL_ARTIFACTS

LEGACY_FINAL_OUTPUTS = (LEGACY_SUMMARY_FILENAME, LEGACY_MINDMAP_FILENAME)
LEGACY_ROOT_ARTIFACTS = ALL_INTERNAL_ARTIFACTS + LEGACY_FINAL_OUTPUTS
ARCHIVED_OUTPUTS = ROOT_DELIVERABLES + LEGACY_FINAL_OUTPUTS

OUTPUT_FILE_ROLES = {
    "core_delivery": ROOT_DELIVERABLES,
}

INTERNAL_DIRNAME = "_internal"
PREVIOUS_FINAL_DIRNAME = "previous_final"


def support_dir(out_dir: Path) -> Path:
    """Return the support directory path without creating it."""
    return out_dir / SUPPORT_DIRNAME


def ensure_support_dir(out_dir: Path) -> Path:
    path = support_dir(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_path(out_dir: Path) -> Path:
    return support_dir(out_dir) / TRANSCRIPT_FILENAME


def legacy_transcript_path(out_dir: Path) -> Path:
    return out_dir / TRANSCRIPT_FILENAME


def internal_dir(out_dir: Path) -> Path:
    """Return the internal directory path without creating it."""
    return out_dir / INTERNAL_DIRNAME


def ensure_internal_dir(out_dir: Path) -> Path:
    path = internal_dir(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def internal_path(out_dir: Path, filename: str) -> Path:
    return internal_dir(out_dir) / filename


def previous_final_dir(out_dir: Path) -> Path:
    return internal_dir(out_dir) / PREVIOUS_FINAL_DIRNAME


def ensure_previous_final_dir(out_dir: Path) -> Path:
    path = previous_final_dir(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
