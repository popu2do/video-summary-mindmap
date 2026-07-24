# Video Summary Mindmap

Generate source transcripts, one final Markdown summary, and an optional Mermaid
mind map from Bilibili or YouTube URLs, local audio/video files, PDFs, and OOXML
Word documents.

The workflow first prepares transcript support material. Use the `Delivery decision`
section below to decide whether a run produced a hand-off artifact.

> Scope: summaries are based on subtitles, audio transcription, or extracted
> document text. Only PDFs with an extractable text layer are supported; image-only
> PDFs are rejected with a readable non-zero error. The tool does not perform
> screenshot analysis or visual scene understanding.

## Features

- Extract subtitles with `yt-dlp` when platform captions are available.
- Transcribe local audio with `faster-whisper` when subtitles are missing or
  explicitly ignored.
- Read local audio and local video files, text-layer PDFs, and OOXML Word documents
  (`.doc`/`.docx`) into the same transcript and final-delivery workflow.
- Prepare transcript support material and internal drafts for inspection and reruns.
- Use `--llm-refine` when a final delivery is required.
- Reuse existing transcripts for fast iteration with `--reuse-transcript`.
- Preserve timestamped transcript segments for chaptering and long-video
  chunking.
- Support local transcription languages with `--language auto|zh|en|ja`
  (`auto` by default).
- Support domain-specific terminology with `--domain general|zh-social`.
- Load local configuration from `.local.env` without committing secrets.

## Repository Layout

```text
.
├── src/
│   ├── video_summary_cli.py # canonical CLI entry point
│   └── video_summary/       # source handling, transcription, summaries, outputs, and LLM refinement
├── .agents/skill/video-summary-mindmap/
│   ├── references/          # prompts and domain terminology
│   ├── agents/              # skill agent metadata
│   └── SKILL.md             # Codex skill instructions
├── tests/                   # repository-level regression tests
├── .env.example
├── requirements.txt
└── README.md
```

The `src/video_summary/` package keeps the implementation modules separated by
responsibility: CLI argument handling, source and document loading, subtitles and
transcription, transcript summarization, artifact writing, Mermaid generation,
configuration, and optional LLM refinement.

## Requirements and Access

- Python 3.12 is recommended for `faster-whisper` compatibility.
- PDF input requires `pypdf` and must contain an extractable text layer.
  Image-only or scanned PDFs are not supported. `.doc` files must be OOXML
  containers (some Word exports use the `.doc` suffix for this format).
- FFmpeg must be installed and available on `PATH` when audio download or
  transcription is needed.
- Network access is required for online videos, first-time local transcription
  model downloads, and optional LLM refinement.

Install Python dependencies:

```powershell
python -m venv .venv
& ".venv/Scripts/python.exe" -m pip install -r requirements.txt
```

Install FFmpeg separately if it is not already available:

```powershell
ffmpeg -version
```

The command above should print version information. If it is not found, install
FFmpeg with your system package manager and reopen the terminal.

Additional setup is scenario-specific:

- `faster-whisper` downloads model files on first use. If Hugging Face access is
  slow or blocked in your environment, pre-download the model, configure the
  relevant cache, or use an environment that can reach the model host.
- Bilibili, YouTube, and other video platforms may block anonymous downloads,
  require login, rate-limit requests, or be unavailable from some networks.
  Restricted videos may require an installed browser profile and
  `--cookies-from-browser edge|chrome|firefox`.
- Final delivery requires a reachable OpenAI-compatible API endpoint, matching
  `OPENAI_API_KIND`, and a valid API key.

## Configuration

Copy the example environment file:

```powershell
Copy-Item ".env.example" ".local.env"
```

`.local.env` is ignored by Git and is loaded automatically from the current
working directory.

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-mini
OPENAI_API_KIND=chat
```

For OpenAI-compatible providers, set:

- `OPENAI_API_KEY`: provider API key.
- `OPENAI_BASE_URL`: compatible API base URL.
- `OPENAI_MODEL`: refinement model.
- `OPENAI_API_KIND`: `responses` or `chat`. The CLI default is `responses`;
  many OpenAI-compatible providers only support `chat`.

Optional local transcription settings:

- `LOCAL_WHISPER_MODEL`: local `faster-whisper` model; default is `tiny`.
- `TRANSCRIBE_LANGUAGE`: `auto`, `zh`, `en`, or `ja`; invalid values fall back
  to `auto`.

## Quick Start

Prepare transcript/support material only (no final deliverable):

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL"
```

Prepare higher-quality transcript/support material only:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --local-whisper-model small --template refined
```

Generate the final delivery with an OpenAI-compatible LLM:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --llm-refine
```

Generate final Chinese course or livestream notes:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Videos/course.mp4" --content-type lecture --domain zh-social --language zh --llm-refine
```

Prepare a local PDF or OOXML Word transcript, then generate its final delivery:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf"
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --llm-refine
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.docx"
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.docx" --reuse-transcript --llm-refine
```

Image-only or scanned PDFs without an extractable text layer are not
supported. The CLI exits non-zero during `PDF/DOCX文本提取` with a readable
message and does not fall back to audio download or local transcription.

After editing `support/transcript.txt`, reuse it for a final rerun:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --llm-refine
```

Document inputs use the same `output/<source-id>/` layout as video inputs. The
extracted text is written to `support/transcript.txt`, which is support material
for review and later reruns, never the final summary. `--reuse-transcript` only
supports local files, not URLs, and requires an existing `support/transcript.txt`
or legacy root-level `transcript.txt`; if both locations are missing, the command
fails before reading or processing the source.

Use browser cookies when the platform requires login:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --cookies-from-browser edge --llm-refine
```

## Recommended Workflow

1. Run once without `--llm-refine` to prepare `support/transcript.txt` and internal
   support material.
2. Inspect and optionally edit `output/<source-id>/support/transcript.txt`.
3. Rerun with the same local source and `--reuse-transcript --llm-refine`.
4. Apply the delivery decision below: first verify a successful CLI exit, then open
   `output/<source-id>/summary.md`.

For Chinese course content, `--language zh` can be more stable than automatic
detection. For mixed-language, English, or Japanese videos, keep the default
`--language auto`.

Template distinction: `compact` is the concise deterministic/offline draft with
core points, an outline, key terms, and a mind map; `refined` is the richer
structured deterministic template with abstract, highlights, questions, term
explanations, chapter summaries, and a mind map. Neither draft contains the
complete transcript. `--template refined` does not call an LLM; add
`--llm-refine` separately for semantic polishing.

## Outputs

By default, outputs are written to:

```text
output/<source-id>/
```

`<source-id>` identifies the source. Use `--out-root` to choose a different
relative or absolute output root while preserving the same `<source-id>/` layout.
Treat this directory as private data: it can contain transcripts and internal
processing artifacts, so do not point it at a public, shared, or synchronized
folder and do not commit it.

### Delivery decision

1. **先看 CLI 是否成功退出。** 只有成功退出才算本次交付有效；失败、非零退出，
   或 LLM 没有返回可用摘要时，都不能把残留文件当最终稿。
2. **再打开 `output/<source-id>/summary.md`。** 它是唯一必需的最终稿。
3. `mindmap.mmd` 仅是可选最终伴随物；LLM 没有返回有效 Mermaid 时可以不存在。
4. `support/transcript.txt` 仅为依据/支持材料，不是最终稿。
5. `_internal/`（包括 `_internal/previous_final/`）是草稿、缓存和历史内部状态，
   不交付给用户。
6. 没有 `--llm-refine` 时不产生最终稿；即使目录里有旧文件或草稿，也不能视为本次交付。

### Source ID rules

`<source-id>` 的规则按来源类型区分：

- 在线来源继续使用平台返回的 `id`/`display_id`（例如 `BV1xxxx`），不改变在线来源的复用方式。
- 本地文件使用基于安全化文件名、扩展名和来源路径的稳定 source-id，
  只用于隔离同名文件，不把原始路径写入输出目录名。无扩展名文件省略扩展名段。
  对 PDF/DOC/DOCX 等文档，用户可见的来源标签和发送给 LLM 的来源字段只使用
  脱敏后的文件名/标题，不展示本地父目录或完整路径。
- 因此，两个不同目录中的 `same-name.docx` 会得到不同的 source-id；
  不同扩展名也继续保持隔离。使用 `--reuse-transcript` 时，应继续使用同一
  本地路径和同一 `--out-root`，这样才能定位到原来的
  `support/transcript.txt`（或兼容读取旧根层 `transcript.txt`）。

## CLI Options

Frequently used options:

```text
--out-root PATH                Write to PATH/<source-id>/; keep it private.
--force-transcribe             Ignore subtitles and transcribe audio; cannot combine with --reuse-transcript.
--reuse-transcript             Rebuild from existing support/transcript.txt (or legacy root transcript.txt); fail if both are missing; cannot combine with --force-transcribe.
--local-whisper-model small    Choose faster-whisper model size.
--language auto|zh|en|ja       Choose or auto-detect transcription language.
--template compact|refined     Choose the internal draft template.
--content-type auto|video|lecture
--domain general|zh-social
--llm-refine                   Publish summary.md and optional mindmap.mmd after success.
--llm-api responses|chat
--use-codex-config             Reuse non-secret Codex model/base URL settings.
```

`--force-transcribe` 与 `--reuse-transcript` 不能同时使用；同时传入会在参数校验阶段被拒绝。运行失败时返回非零码，并使用简洁格式 `ERROR: 阶段=<phase>；<readable reason>`，不打印完整 traceback。

Run the canonical CLI with `--help` for the full argument list:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" --help
```


## Testing

The root command below is the repository-level regression suite:

```powershell
python -m unittest discover -s "tests" -v
```

The root facade regression test can also be run directly:

```powershell
python -m unittest "tests/test_video_summary.py"
```

Compile-check the canonical CLI and tests:

```powershell
python -m py_compile "src/video_summary_cli.py" "tests/test_video_summary.py"
```

## Privacy and Safety

Do not commit:

- `.local.env`
- API keys or GitHub tokens
- cookies
- downloaded media
- private transcripts
- generated output folders
- Codex auth files

Large media files, generated outputs, virtual environments, and local private
notes should stay outside version control.

## Limitations

- This is not a multimodal video-understanding tool. It does not inspect video
  frames, perform OCR on image-only PDFs, analyze screenshots, or infer
  chart/scene meaning.
- Local transcription quality depends on audio quality, speaker clarity,
  language choice, and the selected Whisper model.
- Delivery boundaries are defined in the `Delivery decision` section above; drafts,
  support material, and internal state are never substitutes for the final `summary.md`.
- Long-video LLM refinement can still fail if the provider rejects requests or
  credentials are misconfigured, though transient `429` and `5xx` failures are
  retried. After failure, do not deliver the transcript, drafts, caches, or archive.

## Prior Art and References

This project was informed by public video summarization and transcription
projects, especially:

- [BibiGPT](https://github.com/JimmyLv/BibiGPT-v1): AI audio/video summarization
  for Bilibili, YouTube, local media, podcasts, lectures, and related learning
  content.
- [youtube-transcriber](https://github.com/lifesized/youtube-transcriber):
  local-first YouTube and podcast transcription workflow.
- [AI-Video-Transcriber](https://github.com/wendy7756/AI-Video-Transcriber):
  multi-platform video and podcast transcription and summarization tool.

These projects helped shape the workflow design, subtitle/transcription
handling, prompt structure, and output contract.

## License

No license file is currently included.
