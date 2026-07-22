from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import write_transcript_artifacts
from .config import fail
from .transcript import normalize_text


def transcribe_audio(audio: Path, out_dir: Path, local_model: str, language: str) -> str:
    """Transcribe audio through the project's local faster-whisper path."""
    return transcribe_audio_local(audio, out_dir, local_model, language)


def transcribe_audio_local(audio: Path, out_dir: Path, model_name: str, language: str) -> str:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        fail("没有字幕；本地转写还需要安装 faster-whisper。")

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    transcribe_options: dict[str, Any] = {"vad_filter": True}
    if language != "auto":
        transcribe_options["language"] = language
    segments, info = model.transcribe(str(audio), **transcribe_options)
    lines: list[str] = []
    segment_rows: list[dict[str, Any]] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(text)
            segment_rows.append({"start": segment.start, "end": segment.end, "text": text})
    transcript = normalize_text("\n".join(lines))
    local_meta = {
        "engine": "faster-whisper",
        "model": model_name,
        "requested_language": language,
        "detected_language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
    }
    write_transcript_artifacts(out_dir, transcript, segment_rows, local_meta)
    return transcript
