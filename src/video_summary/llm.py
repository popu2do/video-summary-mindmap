from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .artifacts import (
    load_existing_chunk_summaries,
    read_segments_file,
    write_chunk_summaries,
)
from .config import (
    ANALYSIS_SCOPE_NOTE,
    LLM_MAX_ATTEMPTS,
    LLM_RETRY_DELAYS,
    REFERENCES_DIR,
    fail,
)
from .mermaid import extract_mermaid
from .outputs import format_duration
from .summarization import split_sentences
from .subtitles import format_timestamp

def should_chunk_lecture(transcript: str, max_chars: int) -> bool:
    """Keep lecture requests below the provider timeout-prone payload size."""
    return len(transcript) > min(max_chars, 12000)

def split_transcript_for_llm(out_dir: Path, transcript: str, chunk_chars: int) -> list[dict[str, Any]]:
    segments = read_segments_file(out_dir)
    if segments:
        return split_segments_for_llm(segments, chunk_chars)
    return split_plain_transcript_for_llm(transcript, chunk_chars)

def split_segments_for_llm(segments: list[dict[str, Any]], chunk_chars: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_len = 0
    current_start: Any = None
    current_end: Any = None
    for segment in segments:
        line = f"[{format_timestamp(segment.get('start'))}] {segment.get('text', '')}"
        if current_lines and current_len + len(line) > chunk_chars:
            chunks.append({"start": current_start, "end": current_end, "text": "\n".join(current_lines)})
            current_lines = []
            current_len = 0
            current_start = None
        if current_start is None:
            current_start = segment.get("start")
        current_end = segment.get("end", segment.get("start"))
        current_lines.append(line)
        current_len += len(line) + 1
    if current_lines:
        chunks.append({"start": current_start, "end": current_end, "text": "\n".join(current_lines)})
    return chunks

def split_plain_transcript_for_llm(transcript: str, chunk_chars: int) -> list[dict[str, Any]]:
    units = split_sentences(transcript) or [transcript]
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        if current and current_len + len(unit) > chunk_chars:
            chunks.append({"start": None, "end": None, "text": "\n".join(current)})
            current = []
            current_len = 0
        current.append(unit)
        current_len += len(unit) + 1
    if current:
        chunks.append({"start": None, "end": None, "text": "\n".join(current)})
    return chunks

def build_lecture_chunk_prompt(
    title: str,
    source: str,
    author: str,
    duration: str,
    subtitle_lang: str | None,
    chunk_index: int,
    chunk_count: int,
    chunk: dict[str, Any],
) -> str:
    return f"""You are summarizing one chronological chunk of a long Chinese lecture.

Return concise Markdown only. Preserve timestamps when present. Capture:
- main claims
- concepts and definitions
- examples or cases
- action steps
- open questions or caveats

Video metadata:
- title: {title}
- url: {source}
- author: {author}
- duration: {duration}
- transcript source: {subtitle_lang or 'local transcription'}
- analysis basis: subtitle/audio transcript only; no OCR, screenshots, or visual scene understanding
- chunk: {chunk_index}/{chunk_count}
- chunk time: {format_timestamp(chunk.get('start'))} - {format_timestamp(chunk.get('end'))}

Chunk transcript:
{chunk.get('text', '')}
"""

def build_llm_prompt(
    title: str,
    source: str,
    author: str,
    duration: str,
    transcript: str,
    subtitle_lang: str | None,
    draft_summary: str,
    content_type: str,
) -> str:
    prompt_file = "lecture_prompt.md" if content_type == "lecture" else "refined_prompt.md"
    prompt_path = REFERENCES_DIR / prompt_file
    instructions = prompt_path.read_text(encoding="utf-8", errors="ignore") if prompt_path.exists() else ""
    return f"""{instructions}

Now produce the final Markdown directly. Do not wrap the whole answer in a code block.

Video metadata:
- title: {title}
- url: {source}
- author: {author}
- duration: {duration}
- transcript source: {subtitle_lang or 'local transcription'}
- analysis basis: subtitle/audio transcript only; no OCR, screenshots, or visual scene understanding
- content type: {content_type}

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
    last_error = ""
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
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
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {error.code} {detail[:500]}"
            if not is_retryable_http_status(error.code) or attempt >= LLM_MAX_ATTEMPTS:
                fail(f"LLM 精校请求失败：{last_error}")
        except urllib.error.URLError as error:
            last_error = str(error)
            if attempt >= LLM_MAX_ATTEMPTS:
                fail(f"LLM 精校请求失败：{last_error}")
        time.sleep(LLM_RETRY_DELAYS[attempt - 1])
    return parse_llm_text(data, api_kind)

def is_retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599

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

def refine_long_lecture_with_llm(
    title: str,
    source: str,
    author: str,
    duration: str,
    out_dir: Path,
    transcript: str,
    subtitle_lang: str | None,
    draft_summary: str,
    model: str,
    api_kind: str,
    chunk_chars: int,
) -> str:
    chunks = split_transcript_for_llm(out_dir, transcript, chunk_chars)
    chunk_summaries = load_existing_chunk_summaries(out_dir)
    completed_indexes = {int(item["index"]) for item in chunk_summaries if isinstance(item.get("index"), int)}
    for index, chunk in enumerate(chunks, 1):
        if index in completed_indexes:
            continue
        chunk_prompt = build_lecture_chunk_prompt(
            title=title,
            source=source,
            author=author,
            duration=duration,
            subtitle_lang=subtitle_lang,
            chunk_index=index,
            chunk_count=len(chunks),
            chunk=chunk,
        )
        chunk_summaries.append({
            "index": index,
            "start": chunk.get("start"),
            "end": chunk.get("end"),
            "summary": call_llm(chunk_prompt, model=model, api_kind=api_kind).strip(),
        })
        write_chunk_summaries(out_dir, chunk_summaries)
    chunk_summaries = sorted(chunk_summaries, key=lambda item: int(item.get("index", 0)))
    write_chunk_summaries(out_dir, chunk_summaries)
    merged_transcript = "\n\n".join(
        f"## 分段 {item['index']} [{format_timestamp(item.get('start'))} - {format_timestamp(item.get('end'))}]\n{item['summary']}"
        for item in chunk_summaries
    )
    prompt = build_llm_prompt(
        title=title,
        source=source,
        author=author,
        duration=duration,
        transcript=merged_transcript,
        subtitle_lang=subtitle_lang,
        draft_summary=draft_summary,
        content_type="lecture",
    )
    return call_llm(prompt, model=model, api_kind=api_kind)

def refine_with_llm(
    info: dict[str, Any],
    source: str,
    out_dir: Path,
    transcript: str,
    subtitle_lang: str | None,
    model: str,
    api_kind: str,
    max_chars: int,
    content_type: str,
) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("启用 --llm-refine 需要设置 OPENAI_API_KEY。--use-codex-config 只读取模型和 base URL，不读取 Codex 登录凭据。")

    title = str(info.get("title") or "未命名视频")
    author = str(info.get("uploader") or info.get("channel") or "未知")
    duration = format_duration(info.get("duration"))
    draft_summary = (out_dir / "summary.md").read_text(encoding="utf-8", errors="ignore") if (out_dir / "summary.md").exists() else ""
    if content_type == "lecture" and should_chunk_lecture(transcript, max_chars):
        refined = refine_long_lecture_with_llm(
            title=title,
            source=source,
            author=author,
            duration=duration,
            out_dir=out_dir,
            transcript=transcript,
            subtitle_lang=subtitle_lang,
            draft_summary=draft_summary,
            model=model,
            api_kind=api_kind,
            chunk_chars=min(max_chars, 12000),
        )
    else:
        prompt = build_llm_prompt(
            title=title,
            source=source,
            author=author,
            duration=duration,
            transcript=transcript[:max_chars],
            subtitle_lang=subtitle_lang,
            draft_summary=draft_summary,
            content_type=content_type,
        )
        refined = call_llm(prompt, model=model, api_kind=api_kind)
    refined_path = out_dir / "summary_refined.md"
    refined_path.write_text(refined.strip() + "\n", encoding="utf-8")
    mermaid = extract_mermaid(refined)
    if mermaid:
        (out_dir / "mindmap_refined.mmd").write_text(mermaid.strip() + "\n", encoding="utf-8")
