# Video Summary Mindmap

Bilibili/YouTube/local-media workflow for generating:

- `transcript.txt`
- `summary.md`
- `mindmap.mmd`
- optional LLM-polished `summary_refined.md`
- optional LLM-polished `mindmap_refined.mmd`

The bundled Codex skill lives at:

```text
.agents/skill/video-summary-mindmap/
```

## Features

- Subtitle-first extraction through `yt-dlp`
- Local audio transcription fallback with `faster-whisper`
- Compact and refined Markdown summary templates
- Mermaid mind map generation
- Optional OpenAI-compatible LLM semantic refinement
- Optional reuse of an existing `transcript.txt`
- Optional `.local.env` loading from the current working directory

## Install

Use Python 3.12 for best compatibility with `faster-whisper`.

```powershell
python -m venv .venv
& ".venv/Scripts/python.exe" -m pip install -r requirements.txt
```

`ffmpeg` must be available on `PATH` when audio download/transcription is needed.

## Configure

Copy the example env file and fill your local key:

```powershell
Copy-Item ".env.example" ".local.env"
```

`.local.env` is ignored by Git.

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-mini
OPENAI_API_KIND=chat
```

For OpenAI-compatible providers, set `OPENAI_BASE_URL`, `OPENAI_MODEL`, and `OPENAI_API_KIND=chat` as needed.

## Usage

Fast local draft:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --transcribe-engine local --local-whisper-model tiny --template compact
```

Better local output:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --transcribe-engine local --local-whisper-model small --template refined
```

Regenerate summary from an existing transcript:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --reuse-transcript --template refined
```

Generate semantic polished output:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "https://www.bilibili.com/video/BVxxxx/" --reuse-transcript --template refined --llm-refine
```

Use browser cookies when the platform requires login:

```powershell
& ".venv/Scripts/python.exe" "workflow/video_summary.py" "VIDEO_URL" --cookies-from-browser edge --template refined
```

## Output

Outputs are written under:

```text
workflow/output/<video-id>/
```

Common files:

```text
audio.mp3
metadata.json
mindmap.mmd
mindmap_refined.mmd
summary.md
summary_refined.md
transcript.txt
transcription.json
```

Large media and generated outputs are ignored by Git.

## Privacy

Do not commit:

- `.local.env`
- API keys
- cookies
- downloaded media
- private transcripts
- generated output folders
- Codex auth files

This repository intentionally excludes local test outputs, virtual environments, downloaded reference repositories, and user-provided private notes.

## Codex Skill

The skill metadata and workflow instructions are in:

```text
.agents/skill/video-summary-mindmap/SKILL.md
```

The deterministic workflow script is:

```text
.agents/skill/video-summary-mindmap/scripts/video_summary.py
```

The root wrapper is:

```text
workflow/video_summary.py
```
