from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any

PREFERRED_LANGS = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en")
TEXT_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".json", ".txt", ".xml"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx"}
DEFAULT_LLM_MODEL = "gpt-5.4-mini"
DEFAULT_TRANSCRIBE_LANGUAGE = "auto"
SUPPORTED_LANGUAGES = ("auto", "zh", "en", "ja")
SUPPORTED_DOMAINS = ("general", "zh-social")
ANALYSIS_BASIS = "subtitle_or_audio_or_document_text"
ANALYSIS_SCOPE_NOTE = "当前总结仅基于字幕、音频转写或文档文本，不包含截图或画面理解。"
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_DELAYS = (2, 4)
STOP_WORDS = {
    "对不对", "对吧", "知道吧", "是不是", "就是", "这个", "那个", "要吧", "要不",
    "明白吗", "可以", "然后", "包括", "什么", "因为", "所以", "如果", "或者",
    "但是", "你们", "我们", "他们", "女生", "男生", "一个", "这种", "很多",
    "时候", "的人", "样的", "是你", "么样", "自己", "的时", "的话",
}
ACTIVE_DOMAIN_TERMS: list[str] = []
ACTIVE_DOMAIN_REPLACEMENTS: dict[str, str] = {}
REFERENCES_DIR = Path(__file__).resolve().parent / "references"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
LOCAL_ENV_FILENAME = ".local.env"
_LOADED_ENV_KEYS: set[str] = set()


def default_output_root() -> Path:
    """Return the canonical output root independent of the caller's cwd."""
    return PROJECT_ROOT / "output"


def _local_env_candidates(explicit_path: str | Path | None) -> list[Path]:
    if explicit_path is not None:
        path = Path(explicit_path).expanduser()
        return [path if path.is_absolute() else Path.cwd() / path]
    # Default discovery is anchored to the source tree rather than the caller's
    # cwd, so the same command selects the same configuration from any directory.
    return [
        PROJECT_ROOT / LOCAL_ENV_FILENAME,
        WORKSPACE_ROOT / LOCAL_ENV_FILENAME,
    ]


def _clear_loaded_env() -> None:
    for key in _LOADED_ENV_KEYS:
        os.environ.pop(key, None)
    _LOADED_ENV_KEYS.clear()


def _read_local_env(env_path: Path, *, explicit: bool) -> list[str]:
    try:
        return env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as error:
        scope = "显式" if explicit else "默认"
        fail(f"无法读取{scope} env 文件：{env_path}")
        raise AssertionError("fail() must raise") from error


def _apply_local_env(lines: list[str]) -> None:
    loaded_keys: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded_keys.add(key)
    _LOADED_ENV_KEYS.update(loaded_keys)


def load_local_env(explicit_path: str | Path | None = None) -> Path | None:
    """Load a stable default env or an explicitly requested env file.

    Default discovery is derived from the repository location and never uses the
    caller's cwd. Explicit paths remain relative to cwd for CLI compatibility, but
    missing or unreadable files are reported as business errors. Values loaded by a
    previous call are removed before the next call so repeated in-process CLI runs
    cannot inherit stale values from an older env file.
    """
    _clear_loaded_env()
    explicit = explicit_path is not None
    candidates = _local_env_candidates(explicit_path)
    seen: set[Path] = set()
    for candidate in candidates:
        env_path = candidate.resolve(strict=False)
        if env_path in seen:
            continue
        seen.add(env_path)
        if not env_path.is_file():
            if explicit:
                fail(f"显式 env 文件不存在：{env_path}")
            continue
        _apply_local_env(_read_local_env(env_path, explicit=explicit))
        return env_path
    return None

def default_transcribe_language() -> str:
    value = os.environ.get("TRANSCRIBE_LANGUAGE", DEFAULT_TRANSCRIBE_LANGUAGE)
    return value if value in SUPPORTED_LANGUAGES else DEFAULT_TRANSCRIBE_LANGUAGE

def load_domain_config(domain: str) -> None:
    ACTIVE_DOMAIN_TERMS.clear()
    ACTIVE_DOMAIN_REPLACEMENTS.clear()

    config_path = REFERENCES_DIR / "domain_terms.json"
    if not config_path.exists():
        return
    data = json.loads(config_path.read_text(encoding="utf-8"))
    config = data.get(domain) if isinstance(data, dict) else None
    if not isinstance(config, dict):
        fail(f"未知领域配置：{domain}")
    known_terms = config.get("known_terms") or []
    replacements = config.get("replacements") or {}
    terms = [str(item) for item in known_terms if str(item).strip()]
    normalized_replacements = {str(key): str(value) for key, value in replacements.items()}
    ACTIVE_DOMAIN_TERMS.extend(terms)
    ACTIVE_DOMAIN_REPLACEMENTS.update(normalized_replacements)


class UserFacingError(Exception):
    """An expected application failure that the canonical CLI formats."""

    def __init__(self, message: str, code: int = 1) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def fail(message: str, code: int = 1) -> None:
    raise UserFacingError(message, code)

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
