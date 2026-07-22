from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from .artifacts import *
from .config import *
from .documents import *
from .llm import *
from .mermaid import *
from .outputs import *
from .sources import *
from .subtitles import *
from .summarization import *
from .transcription import *
from .transcript import *


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"ERROR: 阶段=参数校验；{message}\n")


class StageFailure(Exception):
    def __init__(self, stage: str, reason: str, code: int = 1) -> None:
        self.stage = stage
        self.reason = reason
        self.code = code
        super().__init__(reason)


def _exception_reason(error: BaseException) -> str:
    detail = str(error).strip()
    return detail or type(error).__name__


def _run_stage(stage: str, operation: Any) -> Any:
    try:
        return operation()
    except UserFacingError as error:
        raise StageFailure(stage, error.message, error.code) from error
    except Exception as error:
        raise StageFailure(stage, _exception_reason(error)) from error


def _report_failure(stage: str, reason: str, code: int = 1) -> None:
    print(f"ERROR: 阶段={stage}；{reason}", file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    load_local_env()
    parser = CliArgumentParser(
        description="支持 Bilibili/YouTube URL、本地音频/视频、PDF 和 OOXML Word 文档；输出 Markdown 和 Mermaid 脑图。"
    )
    parser.add_argument(
        "source",
        help="输入来源：Bilibili/YouTube URL，或本地音频/视频、PDF、OOXML Word 文档路径",
    )
    parser.add_argument(
        "--out-root",
        default="output",
        help="输出根目录；实际写入 PATH/<source-id>/",
    )
    parser.add_argument("--cookies-from-browser", help="需要登录态时读取浏览器 Cookie，例如 chrome、edge、firefox")
    parser.add_argument("--force-transcribe", action="store_true", help="忽略字幕，强制下载音频并转写")
    parser.add_argument(
        "--local-whisper-model",
        default=os.environ.get("LOCAL_WHISPER_MODEL", "tiny"),
        help="本地 faster-whisper 使用的模型",
    )
    parser.add_argument("--language", choices=SUPPORTED_LANGUAGES, default=default_transcribe_language(), help="转写语言：auto 自动检测，zh/en/ja 固定语言")
    parser.add_argument("--domain", choices=SUPPORTED_DOMAINS, default=os.environ.get("SUMMARY_DOMAIN", "general"), help="领域词表：general 通用，zh-social 中文情感/社交课程")
    parser.add_argument(
        "--reuse-transcript",
        action="store_true",
        help="优先复用已有 transcript.txt 重新生成摘要和脑图；缺失时警告并回退普通处理；不能与 --force-transcribe 同时使用",
    )
    parser.add_argument(
        "--template",
        choices=("compact", "refined"),
        default="refined",
        help="离线摘要模板：compact 紧凑版，refined 精校版；两者都不调用 LLM",
    )
    parser.add_argument("--content-type", choices=("auto", "video", "lecture"), default=os.environ.get("CONTENT_TYPE", "auto"), help="内容类型：lecture 适合课程/直播长口播")
    parser.add_argument(
        "--llm-refine",
        action="store_true",
        help="调用 LLM 对离线摘要做语义精校，额外生成 summary_refined.md",
    )
    parser.add_argument("--llm-model", default=os.environ.get("OPENAI_MODEL", DEFAULT_LLM_MODEL), help="LLM 精校模型")
    parser.add_argument("--llm-api", choices=("responses", "chat"), default=os.environ.get("OPENAI_API_KIND", "responses"), help="LLM API 类型：responses 或 chat")
    parser.add_argument("--llm-max-chars", type=int, default=60000, help="发送给 LLM 的逐字稿最大字符数")
    parser.add_argument("--use-codex-config", action="store_true", help="读取 ~/.codex/config.toml 的模型、wire_api 和 base_url 作为 LLM 精校配置")
    args = parser.parse_args()
    if args.force_transcribe and args.reuse_transcript:
        parser.error("--force-transcribe 与 --reuse-transcript 不能同时使用")

    try:
        args.llm_model_explicit = "--llm-model" in sys.argv
        args.llm_api_explicit = "--llm-api" in sys.argv
        if args.use_codex_config:
            _run_stage("配置", lambda: apply_codex_config(args))
        _run_stage("配置", lambda: load_domain_config(args.domain))

        source = args.source
        info = _run_stage("元数据", lambda: extract_info(source, args.cookies_from_browser))
        video_id = _run_stage("元数据", lambda: slug_from_info(info, source))
        out_dir = Path(args.out_root) / video_id
        _run_stage("输出生成", lambda: out_dir.mkdir(parents=True, exist_ok=True))

        subtitle_lang: str | None = None
        subtitle_segments: list[dict[str, Any]] = []
        transcript = ""
        existing_transcript = out_dir / "transcript.txt"
        if args.reuse_transcript:
            if existing_transcript.exists():
                transcript = _run_stage(
                    "输出生成",
                    lambda: existing_transcript.read_text(encoding="utf-8", errors="ignore"),
                )
            else:
                print(
                    "WARNING: --reuse-transcript 未找到已有 transcript.txt，将继续处理源文件。",
                    file=sys.stderr,
                )
        local_path = _run_stage("元数据", lambda: local_source_path(source))
        if not transcript and local_path and local_path.suffix.lower() in DOCUMENT_EXTENSIONS:
            transcript = _run_stage("PDF/DOCX文本提取", lambda: extract_document_text(local_path))
            _run_stage(
                "输出生成",
                lambda: write_transcript_artifacts(
                    out_dir,
                    transcript,
                    None,
                    {"engine": "document", "requested_language": args.language, "domain": args.domain},
                ),
            )
        if not args.force_transcribe:
            subtitle = _run_stage("元数据", lambda: choose_subtitle(info))
            if subtitle and not transcript:
                subtitle_lang, entry = subtitle
                subtitle_path = _run_stage(
                    "在线字幕与音频获取",
                    lambda: fetch_subtitle(entry, out_dir, safe_filename(subtitle_lang)),
                )
                subtitle_segments = _run_stage(
                    "在线字幕与音频获取",
                    lambda: parse_subtitle_segments(subtitle_path),
                )
                transcript = _run_stage(
                    "在线字幕与音频获取",
                    lambda: subtitle_to_text(subtitle_path),
                )

        if not transcript:
            audio = _run_stage(
                "在线字幕与音频获取",
                lambda: download_audio(source, out_dir, args.cookies_from_browser),
            )
            transcript = _run_stage(
                "本地转写",
                lambda: transcribe_audio(audio, out_dir, args.local_whisper_model, args.language),
            )

        if len(transcript.strip()) < 20:
            stage = "PDF/DOCX文本提取" if local_path and local_path.suffix.lower() in DOCUMENT_EXTENSIONS else "本地转写"
            raise StageFailure(stage, "转写文本过短，无法生成摘要。")

        transcript = normalize_asr_text(transcript)
        if subtitle_segments:
            subtitle_segments = apply_domain_replacements_to_segments(subtitle_segments)
            _run_stage(
                "输出生成",
                lambda: write_transcript_artifacts(
                    out_dir,
                    transcript,
                    subtitle_segments,
                    {
                        "engine": "subtitle",
                        "subtitle_language": subtitle_lang,
                        "requested_language": args.language,
                        "domain": args.domain,
                    },
                ),
            )
        else:
            _run_stage("输出生成", lambda: refresh_existing_segment_artifacts(out_dir, transcript))
        content_type = _run_stage("输出生成", lambda: resolve_content_type(args.content_type, info, source))
        _run_stage(
            "输出生成",
            lambda: write_outputs(info, source, out_dir, transcript, subtitle_lang, args.template),
        )
        if args.llm_refine:
            _run_stage(
                "LLM精校",
                lambda: refine_with_llm(
                    info,
                    source,
                    out_dir,
                    transcript,
                    subtitle_lang,
                    args.llm_model,
                    args.llm_api,
                    args.llm_max_chars,
                    content_type,
                ),
            )
        print(f"输出目录：{out_dir}")
        for line in output_contract_lines(out_dir):
            print(line)
    except StageFailure as error:
        _report_failure(error.stage, error.reason, error.code)
    except UserFacingError as error:
        _report_failure("未处理", error.message, error.code)
    except Exception as error:
        _report_failure("未处理", _exception_reason(error))
