# Video Summary Mindmap

Generate transcripts, structured Markdown notes, and Mermaid mind maps from
Bilibili videos, YouTube videos, and local media files.

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
- Read local PDF and OOXML Word documents (`.doc`/`.docx`) directly into the
  same transcript, summary, and mind-map workflow.
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
├── .agents/skill/video-summary-mindmap/
│   ├── references/          # prompts and domain terminology
│   ├── scripts/             # deterministic workflow implementation
│   ├── tests/               # skill-level regression tests
│   └── SKILL.md             # Codex skill instructions
├── tests/                   # repository-level regression tests
├── workflow/video_summary.py # thin wrapper around the skill script
├── .env.example
├── requirements.txt
└── README.md
```

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

Optional transcription defaults:

- `TRANSCRIBE_ENGINE`: `local` by default.
- `LOCAL_WHISPER_MODEL`: default is `tiny`.
- `TRANSCRIBE_LANGUAGE`: `auto`, `zh`, `en`, or `ja`; invalid values fall back
  to `auto`.

## Quick Start

Fast local draft:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --transcribe-engine local --local-whisper-model tiny --template compact
```

Better local transcription quality:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --transcribe-engine local --local-whisper-model small --template refined
```

Generate polished output with an OpenAI-compatible LLM:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --reuse-transcript --template refined --llm-refine
```

Generate Chinese course or livestream notes:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "D:/Videos/course.mp4" --reuse-transcript --template refined --content-type lecture --domain zh-social --language zh --llm-refine
```

Process a local PDF or OOXML Word document:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "D:/Documents/lecture.pdf" --template refined --content-type lecture --language zh
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "D:/Documents/lecture.doc" --template refined --content-type lecture --language zh
```

Document inputs use the same `workflow/output/<video-id>/` layout as video inputs.
The extracted text is written to `transcript.txt`, so `--reuse-transcript` can
be used for later summary or LLM-refinement reruns without reading the document
again.

Analyze a local media file:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "D:/Videos/example.mp4" --transcribe-engine local --local-whisper-model small --language auto --template refined
```

Use browser cookies when the platform requires login:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "VIDEO_URL" --cookies-from-browser edge --template refined
```

## Recommended Workflow

1. Run once with subtitle extraction or local transcription.
2. Inspect and optionally edit `transcript.txt`.
3. Rerun with `--reuse-transcript`.
4. Add `--llm-refine` when you need the polished delivery files.

For Chinese course content, `--language zh` can be more stable than automatic
detection. For mixed-language, English, or Japanese videos, keep the default
`--language auto`.

## Outputs

Outputs are written to:

```text
workflow/output/<video-id>/
```

Generated for each successful run:

```text
metadata.json
transcript.txt
summary.md
mindmap.mmd
```

Generated when timestamped subtitles or ASR segments are available:

```text
transcript_segments.json
transcript_timed.txt
transcription.json
```

Generated when applicable:

```text
audio.mp3              # downloaded only when online media must be transcribed
summary_refined.md     # with --llm-refine
mindmap_refined.mmd    # when refined output includes Mermaid
summary_chunks.json    # long lecture refinement
```

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
- `metadata.json`: source metadata and analysis scope.

## CLI Options

Frequently used options:

```text
--force-transcribe             Ignore subtitles and transcribe audio.
--reuse-transcript             Rebuild outputs from an existing transcript.txt.
--transcribe-engine local      Use local faster-whisper transcription.
--local-whisper-model small    Choose faster-whisper model size.
--language auto|zh|en|ja       Choose or auto-detect transcription language.
--template compact|refined     Choose deterministic summary template.
--content-type auto|video|lecture
--domain general|zh-social
--llm-refine                   Generate semantic polished outputs.
--llm-api responses|chat
--use-codex-config             Reuse non-secret Codex model/base URL settings.
```

Run the script with `--help` for the full argument list.

## Testing

Run repository tests:

```powershell
python -m unittest "tests/test_video_summary.py"
```

Run skill tests directly:

```powershell
python ".agents/skill/video-summary-mindmap/tests/test_video_summary.py"
```

Compile-check the workflow script and tests:

```powershell
python -m py_compile ".agents/skill/video-summary-mindmap/scripts/video_summary.py" "tests/test_video_summary.py"
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
