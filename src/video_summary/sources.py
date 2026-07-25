from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from .config import DOCUMENT_EXTENSIONS, fail
from .storage import AUDIO_FILENAME, ensure_internal_dir, internal_path

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

def is_remote_source(source: str) -> bool:
    return urlparse(str(source)).scheme in {"http", "https"}

def is_document_source(source: str) -> bool:
    path_without_query = str(source).split("?", 1)[0]
    return Path(path_without_query).suffix.lower() in DOCUMENT_EXTENSIONS


def source_origin_label(source: str, subtitle_lang: str | None) -> str:
    if is_document_source(source):
        return "文档"
    return subtitle_lang or "本地转写"

def is_url_source(source: str) -> bool:
    """Return whether source uses a URL scheme rather than a local path."""
    value = str(source).strip()
    parsed = urlparse(value)
    if not parsed.scheme:
        return False
    if len(parsed.scheme) == 1 and len(value) > 1 and value[1] == ":":
        return False
    return True


def safe_display_name(source: str, info: dict[str, Any] | None = None) -> str:
    """Return a user-visible source label without exposing local parent paths."""
    if info and info.get("_local_path"):
        return safe_filename(Path(str(info["_local_path"])).name)
    if not is_remote_source(source):
        return safe_filename(Path(str(source)).name)
    if info:
        title = str(info.get("title") or info.get("display_id") or "").strip()
        if title:
            return safe_filename(title)
    return safe_filename(str(source))


def source_id_without_access(source: str) -> str:
    """Resolve the same local/source-id shape without reading source contents."""
    if not is_remote_source(source):
        return local_source_id(Path(source))
    match = re.search(r"(BV[0-9A-Za-z]+)", source)
    if match:
        return match.group(1)
    return "video"


def info_without_access(source: str) -> dict[str, Any]:
    if not is_remote_source(source):
        path = Path(source)
        return {
            "id": safe_filename(path.stem),
            "display_id": safe_filename(path.stem),
            "title": path.stem,
            "uploader": "本地文件",
            "duration": None,
            "subtitles": {},
            "automatic_captions": {},
            "_local_path": str(path),
        }
    return {"title": "未命名视频", "uploader": "未知", "duration": None, "subtitles": {}, "automatic_captions": {}}


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
    ensure_internal_dir(out_dir)
    local_path = local_source_path(source)
    if local_path:
        return local_path
    yt_dlp = import_ytdlp()
    template = str(internal_path(out_dir, "audio.%(ext)s"))
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
    audio = internal_path(out_dir, AUDIO_FILENAME)
    if not audio.exists():
        matches = list((out_dir / "_internal").glob("audio.*"))
        if not matches:
            fail("音频下载失败，未找到 audio.*。")
        return matches[0]
    return audio
