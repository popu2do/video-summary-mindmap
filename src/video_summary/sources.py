from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .config import DOCUMENT_EXTENSIONS, fail

def slug_from_info(info: dict[str, Any], source: str) -> str:
    local_path = info.get("_local_path")
    if local_path:
        return local_source_id(Path(str(local_path)))
    for key in ("id", "display_id"):
        value = str(info.get(key) or "").strip()
        if value:
            return safe_filename(value)
    match = re.search(r"(BV[0-9A-Za-z]+)", source)
    if match:
        return match.group(1)
    return "video"

def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned[:120] or "video"

def local_source_id(path: Path) -> str:
    normalized_path = os.path.normcase(str(path.expanduser().resolve(strict=False)))
    path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:8]
    stem = safe_filename(path.stem)
    extension = path.suffix.lower().lstrip(".")
    base = safe_filename(f"{stem}-{extension}" if extension else stem)
    return f"{base[:120]}-{path_hash}"


def import_ytdlp() -> Any:
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        fail("缺少依赖 yt-dlp。请先运行：python -m pip install yt-dlp")
    return yt_dlp

def local_source_path(source: str) -> Path | None:
    path = Path(source)
    if path.exists() and path.is_file():
        return path
    return None

def extract_info(source: str, cookies_from_browser: str | None) -> dict[str, Any]:
    local_path = local_source_path(source)
    if local_path:
        return {
            "id": safe_filename(local_path.stem),
            "display_id": safe_filename(local_path.stem),
            "title": local_path.stem,
            "uploader": "本地文件",
            "duration": None,
            "subtitles": {},
            "automatic_captions": {},
            "_local_path": str(local_path),
        }
    yt_dlp = import_ytdlp()
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(source, download=False)

def download_audio(source: str, out_dir: Path, cookies_from_browser: str | None) -> Path:
    local_path = local_source_path(source)
    if local_path:
        return local_path
    yt_dlp = import_ytdlp()
    template = str(out_dir / "audio.%(ext)s")
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "quiet": False,
        "noplaylist": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
    }
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([source])
    audio = out_dir / "audio.mp3"
    if not audio.exists():
        matches = list(out_dir.glob("audio.*"))
        if not matches:
            fail("音频下载失败，未找到 audio.*。")
        return matches[0]
    return audio
