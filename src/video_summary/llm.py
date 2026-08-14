from __future__ import annotations

import json
from difflib import SequenceMatcher
import os
import re
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .artifacts import read_segments_file
from .config import (
    ANALYSIS_SCOPE_NOTE,
    LLM_MAX_ATTEMPTS,
    LLM_RETRY_DELAYS,
    REFERENCES_DIR,
    fail,
)
from .mermaid import extract_mermaid, is_valid_mindmap, remove_bare_mindmaps
from .outputs import clear_previous_final_outputs, format_duration
from .storage import (
    MINDMAP_FILENAME,
    SUMMARY_DRAFT_FILENAME,
    SUMMARY_FILENAME,
    internal_path,
)
from .sources import is_document_source, is_remote_source, safe_display_name, source_origin_label
from .summarization import split_sentences
from .subtitles import format_timestamp

TRANSCRIPT_SECTION_TERMS = (
    "\u9010\u5b57\u7a3f",
    "\u9010\u5b57\u8f6c\u5199",
    "\u5b8c\u6574\u8f6c\u5199",
    "\u539f\u59cb\u6587\u7a3f",
    "transcript",
    "transcription",
)


def transcript_source_label(source: str, subtitle_lang: str | None) -> str:
    return source_origin_label(source, subtitle_lang)


def _content_label(source: str) -> str:
    return "文档" if is_document_source(source) else "视频"


def _content_subject(source: str) -> str:
    return "document" if is_document_source(source) else "video"


def _analysis_scope_zh(source: str) -> str:
    if is_document_source(source):
        return "仅基于有文本层的 PDF 或 OOXML 文档文本，不包含音频转写、OCR、截图或画面理解。"
    return "仅基于字幕/音频转写，不包含 OCR、截图或画面理解。"


def _render_prompt_instructions(instructions: str, source: str) -> str:
    replacements = {
        "{content_label}": _content_label(source),
        "{analysis_scope_zh}": _analysis_scope_zh(source),
    }
    for placeholder, value in replacements.items():
        instructions = instructions.replace(placeholder, value)
    return instructions


def _prompt_source_name(source: str) -> str:
    if is_remote_source(source):
        return source
    return safe_display_name(source)


def _remove_transcript_sections(summary: str) -> str:
    lines = summary.splitlines()
    kept: list[str] = []
    skipped_level: int | None = None
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    for line in lines:
        heading = heading_pattern.match(line)
        if skipped_level is not None:
            if heading and len(heading.group(1)) <= skipped_level:
                skipped_level = None
            else:
                continue
        if heading:
            heading_title = heading.group(2).lower()
            if any(term in heading_title for term in TRANSCRIPT_SECTION_TERMS):
                skipped_level = len(heading.group(1))
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def _path_variants(value: str) -> set[str]:
    return {value, value.replace("\\", "/"), value.replace("/", "\\")}


def _remove_local_parent_paths(summary: str, source: str) -> str:
    if is_remote_source(source):
        return summary

    source_path = Path(source)
    display_name = _prompt_source_name(source)
    source_variants = _path_variants(str(source)) | _path_variants(str(source_path))
    parent_variants = _path_variants(str(source_path.parent))

    sanitized = summary
    for value in sorted(source_variants, key=len, reverse=True):
        sanitized = sanitized.replace(value, display_name)
    for value in sorted(parent_variants, key=len, reverse=True):
        sanitized = sanitized.replace(value + "\\", "").replace(value + "/", "").replace(value, "")
    return sanitized


def _strip_outer_code_fence(summary: str) -> str:
    """移除包裹整个 LLM 响应的通用代码围栏（``` 或 ```markdown），保留内部正文。"""
    text = summary.strip()
    if not text.startswith("```"):
        return text
    match = re.match(r"^```[^\r\n]*\r?\n", text)
    if not match:
        return text
    language = match.group(0).strip("` \t\r\n").strip().lower()
    if language.startswith("mermaid"):
        return text
    if not text.rstrip().endswith("```"):
        return text
    return text[match.end():-3].strip()


def _strip_leading_reasoning(summary: str) -> str:
    """丢弃第一个 Markdown 标题之前的思维链文本，避免推理痕迹混入最终稿。"""
    lines = summary.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+\S", line):
            if index > 0 and any(line.strip() for line in lines[:index]):
                return "\n".join(lines[index:]).strip()
            break
    return summary.strip()


def _prepare_final_summary(summary: str, source: str) -> str:
    final_summary = _strip_outer_code_fence(summary)
    final_summary = _strip_leading_reasoning(final_summary)
    final_summary = _remove_local_parent_paths(final_summary, source)
    final_summary = _remove_transcript_sections(final_summary)
    if is_document_source(source):
        final_summary = re.sub(
            r"(?im)^(\s*#{1,6}\s*)视频精校总结(?P<suffix>.*)$",
            r"\g<1>文档精校总结\g<suffix>",
            final_summary,
        )
        final_summary = re.sub(
            r"(?im)^(\s*#{1,6}\s*)视频章节总结(?P<suffix>.*)$",
            r"\g<1>文档章节总结\g<suffix>",
            final_summary,
        )
        final_summary = re.sub(
            r"(?im)^\s*(?:[-*]\s*)?(?:\u6587\u7a3f\u6765\u6e90|transcript\s+source)\s*[:：].*$",
            "- \u6587\u7a3f\u6765\u6e90：\u6587\u6863",
            final_summary,
        )
    elif not is_remote_source(source):
        final_summary = re.sub(
            r"(?im)^\s*(?:[-*]\s*)?(?:\u6587\u7a3f\u6765\u6e90|transcript\s+source)\s*[:：].*$",
            "- \u6587\u7a3f\u6765\u6e90：\u672c\u5730\u8f6c\u5199",
            final_summary,
        )
    return final_summary.strip()


def _without_mermaid(summary: str) -> str:
    without_fenced = re.sub(
        r"```mermaid\b.*?(?:```|\Z)",
        "",
        summary,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Only remove a standalone Mermaid mindmap block. A normal sentence that
    # mentions "mindmap" must not consume the rest of the final summary.
    return re.sub(
        r"(?im)^\s*mindmap\s*$\r?\n(?:[ \t]+.*(?:\r?\n|$))*",
        "",
        without_fenced,
    ).strip()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _summary_without_markdown_headings(summary: str) -> str:
    lines = summary.splitlines()
    body: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*#{1,6}\s+\S", line):
            index += 1
            continue
        if (
            line.strip()
            and index + 1 < len(lines)
            and re.fullmatch(r"\s*(?:=+|-+)\s*", lines[index + 1])
        ):
            index += 2
            continue
        body.append(line)
        index += 1
    return "\n".join(body).strip()


def _normalized_refusal_text(value: str) -> str:
    compact = _summary_without_markdown_headings(value).casefold().replace("’", "'")
    return re.sub(r"[\s，,：:；;。.!！?？\']+", "", compact)


def _has_markdown_title(summary: str) -> bool:
    return bool(re.search(r"(?m)^\s*#{1,6}\s+\S", summary))


def _looks_like_refusal_or_invalid_short_text(summary: str) -> bool:
    compact = _normalized_refusal_text(summary)
    refusal_prefixes = (
        "抱歉我无法",
        "很抱歉我无法",
        "对不起我无法",
        "我无法完成",
        "我不能完成",
        "无法生成总结",
        "无法完成总结",
        "无法提供总结",
        "imsorryicant",
        "imsorryicannot",
        "sorryicant",
        "sorryicannot",
        "icantprovideasummary",
        "icannotprovideasummary",
        "icantsummarize",
        "icannotsummarize",
        "imunabletosummarize",
    )
    if any(compact.startswith(prefix) for prefix in refusal_prefixes):
        return True

    # Reject only obvious acknowledgement tokens, not every short untitled
    # sentence. This keeps concise but meaningful summaries publishable.
    short_token = re.sub(r"[^\w]+", "", compact)
    return short_token in {"好", "好的", "收到", "明白", "谢谢", "ok", "okay", "done", "sure"}


def _summary_body_for_copy(summary: str) -> str:
    lines: list[str] = []
    for line in _summary_without_markdown_headings(summary).splitlines():
        lines.append(re.sub(r"^\s*(?:[-*+]\s+|>\s?|\d+[.)]\s+)", "", line))
    return "\n".join(lines).strip()


def _is_high_copy_without_title(summary: str, transcript: str) -> bool:
    normalized_summary = _normalized_text(_summary_body_for_copy(summary))
    normalized_transcript = _normalized_text(transcript)
    if len(normalized_transcript) < 40 or not normalized_summary:
        return False
    if normalized_transcript in normalized_summary:
        return True

    ratio = SequenceMatcher(None, normalized_summary, normalized_transcript).ratio()
    large_copy = len(normalized_summary) >= max(40, int(len(normalized_transcript) * 0.6))
    return large_copy and ratio >= 0.85


_LOCAL_WINDOWS_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/](?:[^\r\n`<>\"|]*)?|\\\\(?:[^\r\n`<>\"|]*)?)"
)
_LOCAL_UNIX_PATH = re.compile(
    r"(?<![\w:/])/(?:[^/\s`<>\"']+/)*[^/\s`<>\"']*"
)


def _contains_local_absolute_path(summary: str) -> bool:
    return bool(_LOCAL_WINDOWS_PATH.search(summary) or _LOCAL_UNIX_PATH.search(summary))


def _validate_final_summary(summary: str | None, transcript: str) -> None:
    if not isinstance(summary, str) or not summary.strip():
        fail("LLM 返回为空，无法发布最终稿。")

    if _contains_local_absolute_path(summary):
        fail("LLM 返回包含本机绝对路径，无法发布最终稿。")

    meaningful_summary = _without_mermaid(summary)
    if not meaningful_summary:
        fail("LLM 返回仅包含 Mermaid 脑图，无法发布最终稿。")
    if not _summary_without_markdown_headings(meaningful_summary):
        fail("LLM 返回缺少实质摘要正文，无法发布最终稿。")
    if _looks_like_refusal_or_invalid_short_text(meaningful_summary):
        fail("LLM 返回疑似拒答或无效短文本，无法发布最终稿。")
    if _contains_local_absolute_path(meaningful_summary):
        fail("LLM 返回包含本机绝对路径，无法发布最终稿。")
    if _normalized_text(meaningful_summary) == _normalized_text(transcript):
        fail("LLM 返回仅复制逐字稿，无法发布最终稿。")
    if _is_high_copy_without_title(meaningful_summary, transcript):
        fail("LLM 返回高度复制逐字稿，无法发布最终稿。")


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
    display_name = _prompt_source_name(source)
    subject = _content_subject(source)
    return f"""You are summarizing one chronological chunk of a long Chinese {subject}.

Return concise Markdown only. Preserve timestamps when present. Capture:
- main claims
- concepts and definitions
- examples or cases
- action steps
- open questions or caveats

{subject.title()} metadata:
- title: {title}
- url: {display_name}
- author: {author}
- duration: {duration}
- transcript source: {transcript_source_label(source, subtitle_lang)}
- analysis basis: {("document text from a text-layer PDF or OOXML document; no audio transcription, OCR, screenshots, or visual scene understanding" if is_document_source(source) else "subtitle/audio transcript only; no OCR, screenshots, or visual scene understanding")}
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
    display_name = _prompt_source_name(source)
    prompt_file = "lecture_prompt.md" if content_type == "lecture" and not is_document_source(source) else "refined_prompt.md"
    prompt_path = REFERENCES_DIR / prompt_file
    instructions = prompt_path.read_text(encoding="utf-8", errors="ignore") if prompt_path.exists() else ""
    instructions = _render_prompt_instructions(instructions, source)
    subject = _content_subject(source)
    document_instruction = (
        "\u6700\u7ec8\u7a3f\u53ea\u4fdd\u7559\u7cbe\u4fee\u603b\u7ed3\u7ed3\u6784\uff0c\u4e0d\u5f97\u8f93\u51fa\u5b8c\u6574\u9010\u5b57\u7a3f\u3001\u5168\u6587\u8f6c\u5f55\u6216\u7b49\u4ef7 transcript\uff1b\u5b8c\u6574\u4f9d\u636e\u6750\u6599\u53ea\u4fdd\u7559\u5728 support/transcript.txt\u3002"
    )
    analysis_basis = (
        "document text from a text-layer PDF or OOXML document; no audio transcription, OCR, screenshots, or visual scene understanding"
        if is_document_source(source)
        else "subtitle/audio transcript only; no OCR, screenshots, or visual scene understanding"
    )
    return f"""{instructions}

{document_instruction}

Now produce the final Markdown directly. Do not wrap the whole answer in a code block.

{subject.title()} metadata:
- title: {title}
- url: {display_name}
- author: {author}
- duration: {duration}
- transcript source: {transcript_source_label(source, subtitle_lang)}
- analysis basis: {analysis_basis}
- content type: {content_type}

Draft summary, if useful:
{draft_summary[:12000]}

Transcript:
{transcript}
"""

def _write_llm_trace(trace_dir: Path | None, prompt: str, response: str) -> None:
    if trace_dir is None:
        return
    trace_dir.mkdir(parents=True, exist_ok=True)
    sequence = len(list(trace_dir.glob("prompt_*.md"))) + 1
    (trace_dir / f"prompt_{sequence:03d}.md").write_text(prompt, encoding="utf-8")
    (trace_dir / f"response_{sequence:03d}.md").write_text(response, encoding="utf-8")


def call_llm(
    prompt: str,
    model: str,
    api_kind: str,
    trace_dir: Path | None = None,
) -> str:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    api_key = os.environ["OPENAI_API_KEY"]
    if api_kind == "chat":
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise Chinese summary editor."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    else:
        url = f"{base_url}/responses"
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": "You are a precise Chinese summary editor."},
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
                "User-Agent": "video-summary-mindmap/1.0",
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
    result = parse_llm_text(data, api_kind)
    _write_llm_trace(trace_dir, prompt, result)
    return result

def _call_and_trace(
    prompt: str,
    model: str,
    api_kind: str,
    trace_dir: Path | None,
) -> str:
    result = call_llm(prompt, model=model, api_kind=api_kind)
    if isinstance(result, str):
        _write_llm_trace(trace_dir, prompt, result)
    return result


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
                if not isinstance(content, dict):
                    continue
                content_type = str(content.get("type") or "")
                # 推理模型会把思维链放在 reasoning_text 项，正文才是最终交付。
                if content_type == "reasoning_text":
                    continue
                if isinstance(content.get("output_text"), str):
                    chunks.append(content["output_text"])
                elif isinstance(content.get("text"), str):
                    chunks.append(content["text"])
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
    workspace_dir: Path | None = None,
    trace_dir: Path | None = None,
) -> str:
    workspace_dir = workspace_dir or out_dir
    chunks = split_transcript_for_llm(workspace_dir, transcript, chunk_chars)
    # Chunk summaries are only useful to assemble this single request. Keeping
    # them in memory avoids presenting a non-functional cross-run cache.
    chunk_summaries: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, 1):
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
            "summary": _call_and_trace(
                chunk_prompt,
                model=model,
                api_kind=api_kind,
                trace_dir=trace_dir,
            ).strip(),
        })
    chunk_summaries.sort(key=lambda item: int(item.get("index", 0)))
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
    return _call_and_trace(prompt, model=model, api_kind=api_kind, trace_dir=trace_dir)

def _stage_bytes_file(workspace_dir: Path, filename: str, content: bytes) -> Path:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=workspace_dir,
        prefix=f".{filename}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _stage_text_file(workspace_dir: Path, filename: str, content: str) -> Path:
    return _stage_bytes_file(workspace_dir, filename, content.encode("utf-8"))


def _publish_final_outputs(
    out_dir: Path,
    summary: str,
    mindmap: str | None = None,
    workspace_dir: Path | None = None,
) -> None:
    workspace_dir = workspace_dir or out_dir
    summary_path = out_dir / SUMMARY_FILENAME
    mindmap_path = out_dir / MINDMAP_FILENAME
    targets: list[tuple[Path, bytes | None]] = [
        (summary_path, summary.encode("utf-8")),
    ]
    if mindmap is not None:
        targets.append((mindmap_path, mindmap.encode("utf-8")))
    elif mindmap_path.is_file():
        # A summary-only refinement must not leave an older mindmap looking
        # like it belongs to the newly published summary.
        targets.append((mindmap_path, None))
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    moved_backups: list[Path] = []
    published: list[Path] = []
    try:
        for target, content in targets:
            if content is not None:
                staged[target] = _stage_bytes_file(workspace_dir, target.name, content)
        for target, _ in targets:
            if target.is_file():
                backups[target] = _stage_bytes_file(workspace_dir, target.name, target.read_bytes())
        for target, _ in targets:
            backup = backups.get(target)
            if backup is not None:
                os.replace(target, backup)
                moved_backups.append(target)
        for target, _ in targets:
            staged_path = staged.get(target)
            if staged_path is not None:
                os.replace(staged_path, target)
                published.append(target)
    except Exception:
        for target in reversed(published):
            target.unlink(missing_ok=True)
        for target in reversed(moved_backups):
            backup = backups[target]
            if backup.exists():
                os.replace(backup, target)
        raise
    finally:
        for path in (*staged.values(), *backups.values()):
            path.unlink(missing_ok=True)

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
    workspace_dir: Path | None = None,
) -> str | None:
    workspace_dir = workspace_dir or out_dir
    trace_dir = workspace_dir / "llm"
    if (out_dir / SUMMARY_FILENAME).is_file() or (out_dir / MINDMAP_FILENAME).is_file():
        # A failed quality gate must not leave a previous final looking like
        # the result of the current refinement attempt. The old finals are
        # known tool outputs, so removing them is safe and does not touch any
        # other user file.
        (out_dir / SUMMARY_FILENAME).unlink(missing_ok=True)
        (out_dir / MINDMAP_FILENAME).unlink(missing_ok=True)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("启用 --llm-refine 需要设置 OPENAI_API_KEY。--use-codex-config 只读取模型和 base URL，不读取 Codex 登录凭据。")

    title = str(info.get("title") or ("未命名文档" if is_document_source(source) else "未命名视频"))
    author = str(info.get("uploader") or info.get("channel") or "未知")
    duration = format_duration(info.get("duration"))
    draft_summary_path = internal_path(workspace_dir, SUMMARY_DRAFT_FILENAME)
    draft_summary = draft_summary_path.read_text(encoding="utf-8", errors="ignore") if draft_summary_path.exists() else ""
    if content_type == "lecture" and should_chunk_lecture(transcript, max_chars):
        refined = refine_long_lecture_with_llm(
            title=title,
            source=source,
            author=author,
            duration=duration,
            out_dir=workspace_dir,
            transcript=transcript,
            subtitle_lang=subtitle_lang,
            draft_summary=draft_summary,
            model=model,
            api_kind=api_kind,
            chunk_chars=min(max_chars, 12000),
            trace_dir=trace_dir,
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
        refined = _call_and_trace(prompt, model=model, api_kind=api_kind, trace_dir=trace_dir)

    final_summary = _prepare_final_summary(refined, source) if isinstance(refined, str) else refined
    _validate_final_summary(final_summary, transcript)
    candidate_mindmap = extract_mermaid(final_summary).strip()
    final_mindmap = candidate_mindmap if is_valid_mindmap(candidate_mindmap) else ""
    if isinstance(final_summary, str):
        final_summary = remove_bare_mindmaps(final_summary).strip()
    if _contains_local_absolute_path(final_mindmap):
        fail("LLM 返回包含本机绝对路径，无法发布最终稿。")
    _publish_final_outputs(
        out_dir,
        final_summary + "\n",
        final_mindmap + "\n" if final_mindmap else None,
        workspace_dir=workspace_dir,
    )
    try:
        clear_previous_final_outputs(out_dir)
    except Exception as error:
        return f"最终稿已发布但后续归档清理失败：{SUMMARY_FILENAME}；{error}"
    return None
