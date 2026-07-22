# Video Summary Mindmap

Generate transcripts, structured Markdown notes, and Mermaid mind maps from
Bilibili or YouTube URLs, local audio and local video files, PDFs, and OOXML Word documents.

The workflow is subtitle-first and transcription-backed: it tries to reuse
available subtitles, falls back to local audio transcription when needed, and
can optionally call an OpenAI-compatible LLM to produce polished course notes or
video summaries.

> Scope: summaries are based only on subtitles or audio transcription. The tool
> does not perform OCR, screenshot analysis, or visual scene understanding.

## Features

- Extract subtitles with `yt-dlp` when platform captions are available.
- Transcribe local audio with `faster-whisper` when subtitles are missing or
  explicitly ignored.
- Read local audio and local video files, PDFs, and OOXML Word documents (`.doc`/`.docx`)
  directly into the same transcript, summary, and mind-map workflow.
- Generate deterministic offline outputs: `summary.md`, `mindmap.mmd`, and
  transcript artifacts.
- Optionally generate LLM-polished outputs: `summary_refined.md` and
  `mindmap_refined.mmd`.
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
- PDF input requires the `pypdf` dependency. `.doc` files must be OOXML
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
- LLM-polished output requires a reachable OpenAI-compatible API endpoint,
  matching `OPENAI_API_KIND`, and a valid API key.

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

Fast local draft:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "https://www.bilibili.com/video/BVxxxx/" --local-whisper-model tiny --template compact
```

Better local transcription quality:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "https://www.bilibili.com/video/BVxxxx/" --local-whisper-model small --template refined
```

Generate polished output with an OpenAI-compatible LLM after a prior run has
created `output/<source-id>/transcript.txt`:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "https://www.bilibili.com/video/BVxxxx/" --template refined --llm-refine
# Later rerun, only when output/<source-id>/transcript.txt already exists:
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "https://www.bilibili.com/video/BVxxxx/" --reuse-transcript --template refined --llm-refine
```

Generate Chinese course or livestream notes:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Videos/course.mp4" --template refined --content-type lecture --domain zh-social --language zh --llm-refine
```

Process a local PDF or OOXML Word document:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --template refined --content-type lecture --language zh
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.doc" --template refined --content-type lecture --language zh
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Documents/lecture.docx" --template refined --content-type lecture --language zh
```

Document inputs use the same `output/<source-id>/` layout as video inputs.
The accepted local document formats are PDF and OOXML Word; a legacy binary `.doc`
file is rejected even though the `.doc` suffix is accepted for OOXML containers.
The extracted text is written to `transcript.txt`, so `--reuse-transcript` can
be used for later summary or LLM-refinement reruns without reading the document
again.

Analyze a local media file:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "D:/Videos/example.mp4" --local-whisper-model small --language auto --template refined
```

Use browser cookies when the platform requires login:

```powershell
& ".venv/Scripts/python.exe" "src/video_summary_cli.py" "VIDEO_URL" --cookies-from-browser edge --template refined
```

## Recommended Workflow

1. Run once with subtitle extraction or local transcription.
2. Inspect and optionally edit `output/<source-id>/transcript.txt`.
3. Rerun with `--reuse-transcript` only after that file already exists; the source
   must still resolve to the same `<source-id>` and `--out-root` must be the same.
   If `transcript.txt` is missing, the current CLI emits a warning and falls back
   to ordinary source processing; this documents the current behavior and does not
   change the source code.
4. Add `--llm-refine` when you need the polished delivery files.

For Chinese course content, `--language zh` can be more stable than automatic
detection. For mixed-language, English, or Japanese videos, keep the default
`--language auto`.

Template distinction: `compact` is the concise deterministic/offline draft with
core points, an outline, key terms, and a mind map; `refined` is the richer
structured deterministic template with abstract, highlights, questions, term
explanations, chapter summaries, mind map, and transcript. `--template refined`
does not call an LLM; add `--llm-refine` separately for semantic polishing.

## Outputs

By default, outputs are written to:

```text
output/<source-id>/
```

`<source-id>` identifies the source, and the directory keeps the output files
flat under that root. Use `--out-root` to choose a different relative or absolute output root while
preserving the same `<source-id>/` layout. This directory receives transcripts,
metadata, and sometimes downloaded audio, so treat it as private data: do not point
it at a public, shared, or synchronized folder, and do not commit a custom root
unless it is explicitly protected by your ignore rules.

Generated for each successful run:

```text
metadata.json
transcript.txt
summary.md
mindmap.mmd
```

### Output role contract

The output directory remains flat under `output/<source-id>/`. The following
contract is the single source of truth for file roles:

- **核心交付 (core delivery)**: `transcript.txt`, `summary.md`, `mindmap.mmd`,
  and `metadata.json`. These are the primary handoff files.
- **可选派生 (optional derived)**: `transcript_segments.json`,
  `transcript_timed.txt`, `summary_refined.md`, and `mindmap_refined.mmd`.
  Timestamped files are generated only when timestamped segments are available;
  refined files require `--llm-refine`.
- **中间缓存 (intermediate cache)**: `summary_chunks.json`, `audio.mp3`, and
  `transcription.json`. `summary_chunks.json` supports resumable long-lecture
  refinement, `audio.mp3` is downloaded only for online transcription, and
  `transcription.json` only stores transcription metadata; it is an intermediate
  artifact, not a core delivery file.

`transcription.json` does not automatically include timestamped `segments`.
Timestamped segments are written to `transcript_segments.json` and
`transcript_timed.txt`.

When `--reuse-transcript` reads an edited `transcript.txt`, the CLI records its
SHA-256 in `metadata.json`. If the hash differs or is unavailable, it removes
`transcript_segments.json`, `transcript_timed.txt`, `summary_chunks.json`, and
`transcription.json`, then rebuilds applicable derived data from the current
transcript. It also
removes stale `summary_refined.md` and `mindmap_refined.mmd`; reruns without
`--llm-refine` do not recreate those polished files. A matching hash preserves
existing timestamped transcript reuse behavior.

### Source ID rules

`<source-id>` 的规则按来源类型区分：

- 在线来源继续使用平台返回的 `id`/`display_id`（例如 `BV1xxxx`），不改变在线来源的复用方式。
- 本地文件使用 `<安全化文件名>-<扩展名>-<短哈希>`，例如
  `lecture-mp4-1a2b3c4d`。短哈希取规范化绝对路径的 SHA-256 前 8 位，
  只用于隔离同名文件，不把原始路径写入输出目录名。无扩展名文件省略扩展名段。
- 因此，两个不同目录中的 `same-name.docx` 会得到不同的 source-id；
  不同扩展名也继续保持隔离。使用 `--reuse-transcript` 时，应继续使用同一
  本地路径和同一 `--out-root`，这样才能定位到原来的 `transcript.txt`。

Output roles:

- `transcript.txt`: normalized transcript used by summaries.
- `transcript_segments.json`: timestamped transcript segments when available.
- `transcript_timed.txt`: readable timestamped transcript.
- `summary.md`: deterministic offline extractive draft.
- `mindmap.mmd`: deterministic Mermaid mind map.
- `summary_refined.md`: optional LLM-polished delivery file.
- `mindmap_refined.mmd`: Mermaid extracted from the polished summary.
- `summary_chunks.json`: resumable intermediate chunk summaries for long
  lecture refinement. Lecture requests are split into chunks of at most 12,000
  characters before the final merge to avoid provider request timeouts.
- `audio.mp3`: downloaded audio for online media transcription; local media is
  read directly and is not copied to `audio.mp3`.
- `metadata.json`: source metadata, analysis scope, and transcript content hash.
- `transcription.json`: transcription metadata/intermediate artifact; it is not a
  core delivery file and may be absent or present depending on the processing path.

## CLI Options

Frequently used options:

```text
--out-root PATH                Write to PATH/<source-id>/; keep it private.
--force-transcribe             Ignore subtitles and transcribe audio; cannot combine with --reuse-transcript.
--reuse-transcript             Rebuild from an existing output transcript.txt; not a first run; cannot combine with --force-transcribe.
--local-whisper-model small    Choose faster-whisper model size.
--language auto|zh|en|ja       Choose or auto-detect transcription language.
--template compact|refined     Choose the concise compact or richer refined template.
--content-type auto|video|lecture
--domain general|zh-social
--llm-refine                   Generate semantic polished outputs.
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

- This is not a multimodal video-understanding tool. It does not inspect frames,
  OCR on-screen text, or infer information from visuals.
- Local transcription quality depends on audio quality, speaker clarity,
  language choice, and the selected Whisper model.
- `summary.md` is deterministic and cheap, but it is not a substitute for
  human review or LLM polishing.
- Long-video LLM refinement can still fail if the provider rejects requests or
  credentials are misconfigured, though transient `429` and `5xx` failures are
  retried.

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
