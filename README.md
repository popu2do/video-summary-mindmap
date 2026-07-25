# Video Summary Mindmap

Generate one final Markdown summary and an optional Mermaid mind map from
Bilibili or YouTube URLs, local audio/video files, PDFs, and OOXML Word documents.

Transcript support material, internal drafts, and segmented data exist only in the
temporary workspace for the current run. They are not user-facing output artifacts.

> Scope: summaries are based on subtitles, audio transcription, or extracted
> document text. Only PDFs with an extractable text layer are supported; image-only
> PDFs are rejected with a readable non-zero error. The tool does not perform OCR,
> screenshot analysis, or visual scene understanding.

## Canonical command

For a user-facing final summary, use the canonical CLI with `--llm-refine` in
this first run. A successful run publishes `output/<source-id>/summary.md`.

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --llm-refine

& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Videos/course.mp4" --llm-refine
```

The same command shape applies to local video/audio, PDF, and DOCX inputs.
Without `--llm-refine`, the command is only a support-material/manual-review
path and does not produce a final draft.

## Features

- Extract subtitles with `yt-dlp` when platform captions are available.
- Transcribe local audio with `faster-whisper` when subtitles are missing or
  explicitly ignored.
- Read local audio and local video files, text-layer PDFs, and OOXML Word documents
  (`.doc`/`.docx`) into the same transcript and final-delivery workflow.
- Prepare transcript support material and internal drafts only in the current run's temporary workspace.
- Use `--llm-refine` when a final delivery is required.
- Reuse a user-supplied local transcript input for fast iteration with `--reuse-transcript`.
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
  Image-only or scanned PDFs are not supported and are not OCR'd. `.doc` files
  must be OOXML containers (some Word exports use the `.doc` suffix for this format).
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

`.local.env` is ignored by Git and is loaded automatically from the project
root (the workspace root for this repository).

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

### Support-only path (no --llm-refine)

Use this only for manual review or manual editing. Support material stays in
the current run's temporary workspace, and this mode does not produce a final draft:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL"
```

A higher-quality support-only pass is also available:

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

### Document shortest path

For a PDF or DOCX, one execution with `--llm-refine` is the shortest final-delivery
path. Do not run a support-only pass first when the goal is the final `summary.md`:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --llm-refine
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.docx" --llm-refine
```

A second run is optional only when a caller manually edits or explicitly supplies a
local transcript input for that run. The logical support input may be named
`support/transcript.txt`, but it belongs to the temporary workspace.
`--reuse-transcript` accepts only that user-provided local input; it never reads
historical transcript files from `output/<source-id>/` or treats output as a
cross-run cache. URLs are not accepted as transcript input.

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --llm-refine
```

### Image-only PDF failure contract

For an image-only or scanned PDF, the exact contract is:

- phase: `PDF/DOCX文本提取`;
- the CLI exits non-zero;
- the message is `PDF 未提取到文本层，图像型 PDF 暂不支持`;
- it does not generate `summary.md` or a final draft;
- it does not fall back to audio download, transcription, or OCR.

### Compatibility

For backward compatibility only, `--reuse-transcript` may accept a
user-provided legacy root-level `transcript.txt` as local input. It never
discovers or reads historical transcript files from `output/<source-id>/`;
this input is not a published output or a cross-run cache.

Use browser cookies when the platform requires login:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --cookies-from-browser edge --llm-refine
```

## Recommended Workflow

1. For a final summary, run the canonical command once with `--llm-refine`.
2. If a review is needed, edit or provide transcript input in the temporary workspace
   for the relevant run; do not expect transcripts or drafts under `output/`.
3. Verify a successful CLI exit, then open `output/<source-id>/summary.md`.

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

By default, the user-facing output contract is:

```text
output/<source-id>/
├── summary.md       # 唯一必需的最终稿
└── mindmap.mmd      # 可选的最终脑图
```

`summary.md` is the only required final deliverable. `mindmap.mmd` is optional
and may be absent when no valid Mermaid is produced. Internal drafts,
transcripts, transcript segments, downloaded media, and `summary_chunks.json`
exist only in the temporary workspace for the current run; they do not belong
under `output/<source-id>/` and are never a cross-run disk cache.

Without `--llm-refine`, no final draft is published. A support-only run, an old
file, a draft, or temporary processing data must not be presented as the current
delivery.

Treat `output/<source-id>/` as private data and do not commit it. The `--out-root`
option may choose a different relative or absolute root, but the same two-file
user-facing contract and `<source-id>/` layout apply.

### Source ID rules

`<source-id>` identifies the source while keeping the user-facing output contract
stable:

- Online sources continue to use the platform-provided `id`/`display_id`.
- Local files use a stable source-id derived from the sanitized filename, extension,
  and source path, without exposing the raw path in the output directory name.
- For PDF/DOC/DOCX inputs, user-visible source labels and LLM source fields use only
  the sanitized filename/title, not the local parent directory or full path.
- Transcript reuse is temporary run input and does not create a persistent output
  file or change the two-file output contract.

## CLI Options

Frequently used options:

```text
--out-root PATH                Write to PATH/<source-id>/; keep it private.
--force-transcribe             Ignore subtitles and transcribe audio; cannot combine with --reuse-transcript.
--reuse-transcript             Rebuild only from a user-supplied local transcript input; never read history from output/; cannot combine with --force-transcribe.
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
  frames, OCR image-only PDFs, analyze screenshots, or infer chart/scene meaning.
  Image-only or scanned PDFs are rejected rather than OCR'd.
- Local transcription quality depends on audio quality, speaker clarity,
  language choice, and the selected Whisper model.
- Delivery boundaries are defined in the `Outputs` section above; drafts, support
  material, and internal state are never substitutes for the final `summary.md`.
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
