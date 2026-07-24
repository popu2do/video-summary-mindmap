from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from .artifacts import refresh_existing_segment_artifacts, write_transcript_artifacts
from .config import (
    DEFAULT_LLM_MODEL,
    DOCUMENT_EXTENSIONS,
    SUPPORTED_DOMAINS,
    SUPPORTED_LANGUAGES,
    UserFacingError,
    apply_codex_config,
    default_transcribe_language,
    load_domain_config,
    load_local_env,
)
from .documents import extract_document_text
from .llm import call_llm, refine_with_llm
from .outputs import (
    ARCHIVED_OUTPUTS,
    final_delivery_ready,
    output_contract_lines,
    prepare_output_directory,
    write_outputs,
)
from .storage import (
    MINDMAP_DRAFT_FILENAME,
    MINDMAP_FILENAME,
    SUMMARY_DRAFT_FILENAME,
    SUMMARY_FILENAME,
    TRANSCRIPT_RELATIVE_PATH,
    legacy_transcript_path,
    transcript_path,
)
from .sources import (
    download_audio,
    extract_info,
    info_without_access,
    is_remote_source,
    is_url_source,
    local_source_path,
    source_id_without_access,
    safe_filename,
    slug_from_info,
)
from .subtitles import (
    choose_subtitle,
    fetch_subtitle,
    parse_subtitle_segments,
    subtitle_to_text,
)
from .summarization import resolve_content_type
from .transcription import transcribe_audio
from .transcript import apply_domain_replacements_to_segments, normalize_asr_text


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


def _require_final_delivery(out_dir: Path) -> None:
    if not final_delivery_ready(out_dir):
        raise StageFailure(
            "最终稿发布",
            f"LLM 精校未生成非空 {SUMMARY_FILENAME}。",
        )


def _previous_final_note(out_dir: Path) -> str | None:
    archive_dir = out_dir / "_internal" / "previous_final"
    if any((archive_dir / filename).is_file() for filename in ARCHIVED_OUTPUTS):
        return "旧最终稿已归档至 _internal/previous_final/，不属于本次结果。"
    return None


def _final_failure_reason(out_dir: Path, reason: str) -> str:
    if "最终稿已发布但后续归档清理失败" in reason:
        return reason
    note = _previous_final_note(out_dir)
    suffix = (
        "最终稿：未生成\n"
        f"{TRANSCRIPT_RELATIVE_PATH}：依据材料，不是最终稿\n"
        "_internal/summary_draft.md：内部草稿，不是最终稿\n"
        "_internal/mindmap_draft.mmd：内部草稿，不是最终稿\n"
        "_internal/*：内部状态（草稿/缓存/元数据），全部不是最终稿"
    )
    if note:
        suffix += f"\n{note}"
    return f"{reason}；{suffix}"
def main() -> None:
    load_local_env()
    parser = CliArgumentParser(
        description=(
            "支持 Bilibili/YouTube URL、本地音频/视频、PDF 和 OOXML Word 文档。\n"
            "默认不产生最终稿。\n"
            "只有 --llm-refine 成功后才发布 summary.md。\n"
            "support/transcript.txt 和 _internal/ 不是最终交付。\n"
            "仅支持有文本层的 PDF；图像型 PDF 不支持。\n"
            "refined 是内部草稿模板，不是最终稿。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        help="输入来源：Bilibili/YouTube URL，或本地音频/视频、有文本层的 PDF、OOXML Word 文档路径",
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
        help=f"仅复用已有 {TRANSCRIPT_RELATIVE_PATH}（兼容旧版根层 transcript.txt）重新生成摘要和脑图；两处均缺失时直接失败；不能与 --force-transcribe 同时使用",
    )
    parser.add_argument(
        "--template",
        choices=("compact", "refined"),
        default="refined",
        help="离线摘要模板：compact 紧凑版；refined 内部草稿模板，不是最终稿；两者都不调用 LLM",
    )
    parser.add_argument("--content-type", choices=("auto", "video", "lecture"), default=os.environ.get("CONTENT_TYPE", "auto"), help="内容类型：lecture 适合课程/直播长口播")
    parser.add_argument(
        "--llm-refine",
        action="store_true",
        help=f"成功完成语义精校后发布 {SUMMARY_FILENAME}；可选 Mermaid 脑图 {MINDMAP_FILENAME}",
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
        if args.reuse_transcript and is_url_source(source):
            raise StageFailure("输出准备", "--reuse-transcript 仅支持本地文件。")
        if args.reuse_transcript:
            video_id = _run_stage("输出准备", lambda: source_id_without_access(source))
            out_dir = Path(args.out_root) / video_id
            _run_stage("输出准备", lambda: prepare_output_directory(out_dir, True))
            current_transcript = transcript_path(out_dir)
            legacy_transcript = legacy_transcript_path(out_dir)
            if not current_transcript.is_file() and not legacy_transcript.is_file():
                raise StageFailure(
                    "输出准备",
                    f"--reuse-transcript 缺少 {TRANSCRIPT_RELATIVE_PATH}，且未找到旧版根层 transcript.txt。",
                )
            transcript_path_to_read = current_transcript if current_transcript.is_file() else legacy_transcript
            transcript = _run_stage(
                "输出生成",
                lambda: transcript_path_to_read.read_text(encoding="utf-8", errors="ignore"),
            )
            info = _run_stage("元数据", lambda: info_without_access(source))
            local_path = None if is_remote_source(source) else Path(source)
        else:
            info = _run_stage("元数据", lambda: extract_info(source, args.cookies_from_browser))
            video_id = _run_stage("元数据", lambda: slug_from_info(info, source))
            out_dir = Path(args.out_root) / video_id
            _run_stage("输出准备", lambda: prepare_output_directory(out_dir, False))
            transcript = ""
            local_path = _run_stage("元数据", lambda: local_source_path(source))

        subtitle_lang: str | None = None
        subtitle_segments: list[dict[str, Any]] = []
        transcript_artifacts_written = False
        is_document = bool(local_path and local_path.suffix.lower() in DOCUMENT_EXTENSIONS)
        if not transcript and is_document:
            transcript = _run_stage(
                "PDF/DOCX文本提取",
                lambda: extract_document_text(local_path),
            )
            if len(transcript.strip()) < 20:
                raise StageFailure("PDF/DOCX文本提取", "文档文本为空或过短，无法生成摘要。")
            _run_stage(
                "输出生成",
                lambda: write_transcript_artifacts(
                    out_dir,
                    transcript,
                    None,
                    {"engine": "document", "requested_language": args.language, "domain": args.domain},
                ),
            )
            transcript_artifacts_written = True
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
            transcript_artifacts_written = True

        if len(transcript.strip()) < 20:
            stage = "PDF/DOCX文本提取" if is_document else "本地转写"
            reason = (
                "文档文本为空或过短，无法生成摘要。"
                if is_document
                else "转写文本过短，无法生成摘要。"
            )
            raise StageFailure(stage, reason)

        transcript = normalize_asr_text(transcript)
        if subtitle_segments and not transcript_artifacts_written:
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
            transcript_artifacts_written = True
        elif not transcript_artifacts_written:
            _run_stage("输出生成", lambda: refresh_existing_segment_artifacts(out_dir, transcript))
        content_type = _run_stage("输出生成", lambda: resolve_content_type(args.content_type, info, source))
        _run_stage(
            "输出生成",
            lambda: write_outputs(info, source, out_dir, transcript, subtitle_lang, args.template),
        )
        if not args.llm_refine:
            print(f"输出目录：{out_dir}")
            print("最终稿：未生成")
            print("未生成最终稿：本次运行仅生成草稿。")
            print(f"{TRANSCRIPT_RELATIVE_PATH}：依据材料，不是最终稿")
            print("_internal/summary_draft.md：内部草稿，不是最终稿")
            print("_internal/mindmap_draft.mmd：内部草稿，不是最终稿")
            print("_internal/*：内部状态（草稿/缓存/元数据），全部不是最终稿")
            if note := _previous_final_note(out_dir):
                print(note)
            print("如需发布最终稿，请使用 --llm-refine。")
            for line in output_contract_lines(out_dir):
                print(line)
            return
        cleanup_warning = _run_stage(
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
        _run_stage("最终稿发布", lambda: _require_final_delivery(out_dir))
        print(f"输出目录：{out_dir}")
        print(f"最终稿：{SUMMARY_FILENAME}")
        if (out_dir / MINDMAP_FILENAME).is_file():
            print(f"脑图：{MINDMAP_FILENAME}")
        else:
            print("脑图：未生成（LLM 未返回有效 Mermaid，按需生成）")
        if cleanup_warning:
            print(f"警告：{cleanup_warning}", file=sys.stderr)
        for line in output_contract_lines(out_dir):
            print(line)
    except StageFailure as error:
        reason = error.reason
        if "out_dir" in locals() and error.stage != "输出准备":
            reason = _final_failure_reason(out_dir, reason)
        _report_failure(error.stage, reason, error.code)
    except UserFacingError as error:
        _report_failure("未处理", error.message, error.code)
    except Exception as error:
        _report_failure("未处理", _exception_reason(error))
