#!/usr/bin/env python
"""Generate transcript, Markdown summary, and Mermaid mind map for videos."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PREFERRED_LANGS = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en")
TEXT_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".json", ".txt", ".xml"}
DEFAULT_LLM_MODEL = "gpt-5.4-mini"
STOP_WORDS = {
    "对不对", "对吧", "知道吧", "是不是", "就是", "这个", "那个", "要吧", "要不",
    "明白吗", "可以", "然后", "包括", "什么", "因为", "所以", "如果", "或者",
    "但是", "你们", "我们", "他们", "女生", "男生", "一个", "这种", "很多",
    "时候", "的人", "样的", "是你", "么样", "自己", "的时", "的话",
}
KNOWN_TERMS = [
    "善意假设", "恶意假设", "社交动能", "人设", "展示面", "情绪价值", "社交情商",
    "高框架", "长期关系", "沟通节奏", "实战经验", "自我提升", "约会", "复盘",
    "投其所好", "优质关系", "精神小妹", "职场人设", "学生人设", "销售思维",
]


def load_local_env() -> None:
    env_path = Path.cwd() / ".local.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def slug_from_info(info: dict[str, Any], source: str) -> str:
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


def import_ytdlp() -> Any:
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        fail("缺少依赖 yt-dlp。请先运行：python -m pip install yt-dlp")
    return yt_dlp


def extract_info(source: str, cookies_from_browser: str | None) -> dict[str, Any]:
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
    url = entry.get("url")
    if not url:
        fail("字幕条目没有 URL。")
    ext = f".{entry.get('ext') or 'txt'}".lower()
    if ext not in TEXT_EXTENSIONS:
        ext = ".txt"
    target = out_dir / f"subtitle.{lang}{ext}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target


def subtitle_to_text(path: Path) -> str:
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


def json_subtitle_to_text(raw: str) -> str:
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
    replacements = {
        "人社": "人设",
        "人舍": "人设",
        "展示面": "展示面",
        "溝通": "沟通",
        "沟冲": "沟通",
        "勾踪": "沟通",
        "情参": "情商",
        "善恶假设": "善恶假设",
        "投稀所好": "投其所好",
        "投时": "投其",
        "经常妹": "精神小妹",
        "竞生小妹": "精神小妹",
        "精神的女孩子": "精神小妹",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def download_audio(source: str, out_dir: Path, cookies_from_browser: str | None) -> Path:
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


def transcribe_audio(audio: Path, out_dir: Path, local_model: str, engine: str) -> str:
    if engine == "local" or not os.environ.get("OPENAI_API_KEY"):
        return transcribe_audio_local(audio, out_dir, local_model)
    cli = Path(os.environ.get("TRANSCRIBE_CLI", "transcribe_diarize.py"))
    if not cli.exists():
        fail(f"找不到转写脚本：{cli}")
    transcript = out_dir / "transcript.txt"
    cmd = [sys.executable, str(cli), str(audio), "--response-format", "text", "--out", str(transcript)]
    subprocess.run(cmd, check=True)
    return transcript.read_text(encoding="utf-8", errors="ignore")


def transcribe_audio_local(audio: Path, out_dir: Path, model_name: str) -> str:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        fail("没有字幕，且未设置 OPENAI_API_KEY；本地转写还需要安装 faster-whisper。")

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), language="zh", vad_filter=True)
    lines: list[str] = []
    segment_rows: list[dict[str, Any]] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(text)
            segment_rows.append({"start": segment.start, "end": segment.end, "text": text})
    transcript = normalize_text("\n".join(lines))
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    (out_dir / "transcript_timed.txt").write_text(
        "\n".join(f"[{format_timestamp(row['start'])}] {row['text']}" for row in segment_rows) + "\n",
        encoding="utf-8",
    )
    (out_dir / "transcript_segments.json").write_text(json.dumps(segment_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    local_meta = {
        "engine": "faster-whisper",
        "model": model_name,
        "detected_language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
    }
    (out_dir / "transcription.json").write_text(json.dumps(local_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return transcript


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
    for pattern in KNOWN_TERMS:
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


def load_segments_from_text(text: str) -> list[dict[str, Any]]:
    return []


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


def write_outputs(info: dict[str, Any], source: str, out_dir: Path, transcript: str, subtitle_lang: str | None, template: str) -> None:
    title = str(info.get("title") or "未命名视频")
    author = str(info.get("uploader") or info.get("channel") or "未知")
    duration = info.get("duration")
    key_points = pick_key_sentences(transcript, 10)
    terms = keywords(transcript, 12)
    chapters = chapterize_from_files(out_dir, transcript, 6)
    sections = [chapter["summary"] for chapter in chapters] or chunk_summary(transcript, 6)

    metadata = {
        "source": source,
        "title": title,
        "author": author,
        "duration": duration,
        "subtitle_language": subtitle_lang,
        "word_count": len(transcript),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

    if template == "refined":
        summary_lines = build_refined_summary(title, source, author, duration, subtitle_lang, transcript, key_points, terms, chapters)
    else:
        summary_lines = [
            f"# {title}",
            "",
            "## 元信息",
            f"- 来源：{source}",
            f"- 作者：{author}",
            f"- 时长：{format_duration(duration)}",
            f"- 字幕语言：{subtitle_lang or '无字幕，使用转写'}",
            "",
            "## 核心摘要",
        ]
        summary_lines.extend(f"- {item}" for item in key_points[:5])
        summary_lines.extend(["", "## 分段大纲"])
        summary_lines.extend(f"{index}. {item}" for index, item in enumerate(sections, 1))
        summary_lines.extend(["", "## 关键观点"])
        summary_lines.extend(f"- {item}" for item in key_points[5:] or key_points[:5])
        summary_lines.extend(["", "## 高频术语"])
        summary_lines.append("、".join(terms) if terms else "未识别")
        summary_lines.extend(["", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    (out_dir / "summary.md").write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
    (out_dir / "mindmap.mmd").write_text(build_mermaid(title, sections, key_points, terms) + "\n", encoding="utf-8")


def refine_with_llm(
    info: dict[str, Any],
    source: str,
    out_dir: Path,
    transcript: str,
    subtitle_lang: str | None,
    model: str,
    api_kind: str,
    max_chars: int,
) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("启用 --llm-refine 需要设置 OPENAI_API_KEY。--use-codex-config 只读取模型和 base URL，不读取 Codex 登录凭据。")

    title = str(info.get("title") or "未命名视频")
    author = str(info.get("uploader") or info.get("channel") or "未知")
    duration = format_duration(info.get("duration"))
    prompt = build_llm_prompt(
        title=title,
        source=source,
        author=author,
        duration=duration,
        transcript=transcript[:max_chars],
        subtitle_lang=subtitle_lang,
        draft_summary=(out_dir / "summary.md").read_text(encoding="utf-8", errors="ignore") if (out_dir / "summary.md").exists() else "",
    )
    refined = call_llm(prompt, model=model, api_kind=api_kind)
    refined_path = out_dir / "summary_refined.md"
    refined_path.write_text(refined.strip() + "\n", encoding="utf-8")
    mermaid = extract_mermaid(refined)
    if mermaid:
        (out_dir / "mindmap_refined.mmd").write_text(mermaid.strip() + "\n", encoding="utf-8")


def build_llm_prompt(
    title: str,
    source: str,
    author: str,
    duration: str,
    transcript: str,
    subtitle_lang: str | None,
    draft_summary: str,
) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "references" / "refined_prompt.md"
    instructions = prompt_path.read_text(encoding="utf-8", errors="ignore") if prompt_path.exists() else ""
    return f"""{instructions}

Now produce the final Markdown directly. Do not wrap the whole answer in a code block.

Video metadata:
- title: {title}
- url: {source}
- author: {author}
- duration: {duration}
- transcript source: {subtitle_lang or 'local transcription'}

Draft summary, if useful:
{draft_summary[:12000]}

Transcript:
{transcript}
"""


def call_llm(prompt: str, model: str, api_kind: str) -> str:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    if api_kind == "chat":
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise Chinese video-summary editor."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    else:
        url = f"{base_url}/responses"
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": "You are a precise Chinese video-summary editor."},
                {"role": "user", "content": prompt},
            ],
        }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        fail(f"LLM 精校请求失败：HTTP {error.code} {detail[:500]}")
    except urllib.error.URLError as error:
        fail(f"LLM 精校请求失败：{error}")
    return parse_llm_text(data, api_kind)


def parse_llm_text(data: dict[str, Any], api_kind: str) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    if api_kind == "chat":
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    output = data.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if isinstance(content, dict):
                    if isinstance(content.get("text"), str):
                        chunks.append(content["text"])
                    elif isinstance(content.get("output_text"), str):
                        chunks.append(content["output_text"])
        if chunks:
            return "\n".join(chunks)
    fail("无法解析 LLM 返回结果。")


def apply_codex_config(args: argparse.Namespace) -> None:
    config_path = Path(os.environ.get("CODEX_CONFIG", Path.home() / ".codex" / "config.toml"))
    if not config_path.exists():
        fail(f"找不到 Codex 配置文件：{config_path}")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    provider_name = config.get("model_provider")
    providers = config.get("model_providers") or {}
    provider = providers.get(provider_name) if provider_name else None
    if not isinstance(provider, dict):
        fail(f"Codex 配置里找不到 model_provider：{provider_name}")

    model = config.get("model")
    wire_api = provider.get("wire_api")
    base_url = provider.get("base_url")
    if isinstance(model, str) and not args.llm_model_explicit:
        args.llm_model = model
    if isinstance(wire_api, str) and not args.llm_api_explicit:
        args.llm_api = "responses" if wire_api == "responses" else "chat"
    if isinstance(base_url, str) and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = base_url


def extract_mermaid(markdown: str) -> str:
    match = re.search(r"```mermaid\s+(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(^mindmap\s+.*)", markdown, flags=re.DOTALL | re.MULTILINE)
    return match.group(1) if match else ""


def chapterize_from_files(out_dir: Path, transcript: str, chapters: int) -> list[dict[str, Any]]:
    segments_path = out_dir / "transcript_segments.json"
    if segments_path.exists():
        try:
            data = json.loads(segments_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return chapterize_segments(data, chapters)
        except json.JSONDecodeError:
            pass
    return chapterize(transcript, chapters)


def build_refined_summary(
    title: str,
    source: str,
    author: str,
    duration: Any,
    subtitle_lang: str | None,
    transcript: str,
    key_points: list[str],
    terms: list[str],
    chapters: list[dict[str, Any]],
) -> list[str]:
    abstract = build_abstract(key_points, chapters)
    lines = [
        f"# 视频精校总结：{title}",
        "",
        "## 元信息",
        f"- 来源：{source}",
        f"- 作者：{author}",
        f"- 时长：{format_duration(duration)}",
        f"- 文稿来源：{subtitle_lang or '无字幕，本地转写'}",
        "",
        "## 摘要",
        abstract,
        "",
        "### 亮点",
    ]
    lines.extend(f"- {trim_sentence(point, 92)}{format_time_suffix(chapters, index)}" for index, point in enumerate(key_points[:5]))
    lines.extend(["", "### 思考"])
    for index, question in enumerate(build_questions(terms, key_points), 1):
        lines.append(f"{index}. **{question}**")
        answer = key_points[index - 1] if index - 1 < len(key_points) else abstract
        lines.append(f"   - {trim_sentence(answer, 120)}")
    lines.extend(["", "### 术语解释"])
    for term in terms[:6]:
        lines.append(f"- **{term}**：{explain_term(term, key_points, chapters)}")
    lines.extend(["", "---", "", f"## 视频章节总结 ｜ {title}", "", abstract])
    for index, chapter in enumerate(chapters, 1):
        time_label = format_timestamp(chapter.get("time")) if chapter.get("time") is not None else f"章节 {index}"
        lines.extend(["", f"### [{time_label}] - {chapter['title']}", "", chapter["summary"]])
    sections = [chapter["summary"] for chapter in chapters]
    lines.extend(["", "---", "", "## 思维导图", "", "```mermaid", build_mermaid(title, sections, key_points, terms), "```"])
    lines.extend(["", "---", "", "## 口播逐字稿", "", transcript])
    return lines


def build_abstract(key_points: list[str], chapters: list[dict[str, Any]]) -> str:
    seeds = key_points[:3] or [chapter["summary"] for chapter in chapters[:3]]
    text = "；".join(trim_sentence(seed, 80) for seed in seeds if seed)
    return text + "。" if text else "本视频围绕核心主题展开，建议结合逐字稿进一步精校。"


def build_questions(terms: list[str], key_points: list[str]) -> list[str]:
    first = terms[0] if terms else "核心概念"
    second = terms[1] if len(terms) > 1 else "实践方法"
    third = terms[2] if len(terms) > 2 else "认知误区"
    return [
        f"{first}真正解决的是什么问题？",
        f"{second}在实际场景中应该如何判断和使用？",
        f"哪些{third}会导致行动偏差？",
    ][: max(2, min(3, len(key_points) or 2))]


def explain_term(term: str, key_points: list[str], chapters: list[dict[str, Any]]) -> str:
    corpus = key_points + [chapter["summary"] for chapter in chapters]
    for item in corpus:
        if term in item:
            return trim_sentence(item, 110)
    return "文稿中的高频概念，建议结合上下文进一步人工精校。"


def format_time_suffix(chapters: list[dict[str, Any]], index: int) -> str:
    if not chapters:
        return ""
    chapter = chapters[min(index, len(chapters) - 1)]
    value = chapter.get("time")
    return f" [{format_timestamp(value)}]" if value is not None else ""


def format_duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "未知"
    seconds = int(value)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def format_timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "00:00"
    seconds = int(value)
    if seconds >= 3600:
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def mindmap_text(value: str, limit: int = 36) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = re.sub(r"[(){}\[\]\"`]", "", value)
    return value[:limit] or "未命名"


def build_mermaid(title: str, sections: list[str], key_points: list[str], terms: list[str]) -> str:
    lines = ["mindmap", f"  root(({mindmap_text(title, 28)}))", "    分段大纲"]
    lines.extend(f"      {mindmap_text(item)}" for item in sections[:6])
    lines.append("    关键观点")
    lines.extend(f"      {mindmap_text(item)}" for item in key_points[:6])
    lines.append("    高频术语")
    lines.extend(f"      {mindmap_text(item, 18)}" for item in terms[:8])
    return "\n".join(lines)


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser(description="Summarize Bilibili/YouTube videos into Markdown and Mermaid mind maps.")
    parser.add_argument("source", help="视频 URL 或本地媒体路径")
    parser.add_argument("--out-root", default="workflow/output", help="输出根目录")
    parser.add_argument("--cookies-from-browser", help="需要登录态时读取浏览器 Cookie，例如 chrome、edge、firefox")
    parser.add_argument("--force-transcribe", action="store_true", help="忽略字幕，强制下载音频并转写")
    parser.add_argument("--transcribe-engine", choices=("local", "openai"), default=os.environ.get("TRANSCRIBE_ENGINE", "local"), help="转写引擎：local 使用 faster-whisper，openai 使用 Codex transcribe skill")
    parser.add_argument("--local-whisper-model", default=os.environ.get("LOCAL_WHISPER_MODEL", "tiny"), help="无 OPENAI_API_KEY 时使用的 faster-whisper 模型")
    parser.add_argument("--reuse-transcript", action="store_true", help="如果输出目录已有 transcript.txt，则只重新生成摘要和脑图")
    parser.add_argument("--template", choices=("compact", "refined"), default="refined", help="摘要模板：compact 简版，refined 精校版")
    parser.add_argument("--llm-refine", action="store_true", help="调用 OpenAI-compatible LLM 生成语义精校版 summary_refined.md")
    parser.add_argument("--llm-model", default=os.environ.get("OPENAI_MODEL", DEFAULT_LLM_MODEL), help="LLM 精校模型")
    parser.add_argument("--llm-api", choices=("responses", "chat"), default=os.environ.get("OPENAI_API_KIND", "responses"), help="LLM API 类型：responses 或 chat")
    parser.add_argument("--llm-max-chars", type=int, default=60000, help="发送给 LLM 的逐字稿最大字符数")
    parser.add_argument("--use-codex-config", action="store_true", help="读取 ~/.codex/config.toml 的模型、wire_api 和 base_url 作为 LLM 精校配置")
    args = parser.parse_args()
    args.llm_model_explicit = "--llm-model" in sys.argv
    args.llm_api_explicit = "--llm-api" in sys.argv
    if args.use_codex_config:
        apply_codex_config(args)

    source = args.source
    info = extract_info(source, args.cookies_from_browser)
    video_id = slug_from_info(info, source)
    out_dir = Path(args.out_root) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    subtitle_lang: str | None = None
    transcript = ""
    existing_transcript = out_dir / "transcript.txt"
    if args.reuse_transcript and existing_transcript.exists():
        transcript = existing_transcript.read_text(encoding="utf-8", errors="ignore")
    if not args.force_transcribe:
        subtitle = choose_subtitle(info)
        if subtitle and not transcript:
            subtitle_lang, entry = subtitle
            subtitle_path = fetch_subtitle(entry, out_dir, safe_filename(subtitle_lang))
            transcript = subtitle_to_text(subtitle_path)

    if not transcript:
        audio = download_audio(source, out_dir, args.cookies_from_browser)
        transcript = transcribe_audio(audio, out_dir, args.local_whisper_model, args.transcribe_engine)

    if len(transcript.strip()) < 20:
        fail("转写文本过短，无法生成摘要。")

    transcript = normalize_asr_text(transcript)
    write_outputs(info, source, out_dir, transcript, subtitle_lang, args.template)
    if args.llm_refine:
        refine_with_llm(info, source, out_dir, transcript, subtitle_lang, args.llm_model, args.llm_api, args.llm_max_chars)
    print(f"输出目录：{out_dir}")
    print(f"- transcript.txt")
    print(f"- summary.md")
    print(f"- mindmap.mmd")
    if args.llm_refine:
        print(f"- summary_refined.md")
        if (out_dir / "mindmap_refined.mmd").exists():
            print(f"- mindmap_refined.mmd")
    print(f"- metadata.json")


if __name__ == "__main__":
    main()
