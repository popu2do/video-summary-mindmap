---
name: video-summary-mindmap
description: Prepare transcript support material for Bilibili, YouTube, local video/audio, PDF, and OOXML Word inputs, then publish the single final summary.md and optional mindmap.mmd only after a successful --llm-refine run. Use when asked to analyze videos, documents, lectures, tutorials, interviews, or create mind-map outputs from source content.
---

# Video Summary Mindmap

## Canonical command

Use the repository's single canonical CLI entry point with `--llm-refine` when
the user needs a final delivery:

```powershell
python "src/video_summary_cli.py" "VIDEO_URL" --llm-refine

python "src/video_summary_cli.py" "D:/Videos/course.mp4" --llm-refine
```

It accepts a Bilibili or YouTube URL, a local audio/video path, or a local text-layer PDF/OOXML Word document (`.pdf`, `.doc`, `.docx`). Image-only or scanned PDFs are unsupported and are not OCR'd. The user-facing output under `output/<source-id>/` contains only the final `summary.md` and optional `mindmap.mmd`; keep this per-source layout unchanged. Internal drafts, transcripts, and segmented data stay in the current run's temporary workspace.

### Support-only path (no --llm-refine)

Without `--llm-refine`, the command only prepares support material for manual
review or manual editing. It does not produce a final draft; do not hand off
transcripts, drafts, caches, or archives.

## Delivery decision

1. **Check the CLI exit first.** Only a successful exit is a valid delivery; a
   failure, non-zero exit, or unusable LLM summary is never a final result.
2. **Then open `output/<source-id>/summary.md`.** It is the only required final draft.
3. `mindmap.mmd` is an optional final companion and may be absent when the LLM
   returns no valid Mermaid.
4. Internal drafts, transcripts, transcript segments, downloaded media, and
   `summary_chunks.json` exist only in the current run's temporary workspace; they
   are not output files or cross-run cache.
5. Without `--llm-refine`, no final draft is published; old files and temporary
   data do not count as the current delivery.

Run from the repository root. Keep generated outputs private and do not commit source media, transcripts, cookies, API keys, or output folders.

### Local source-id

Local files use a stable source-id derived from the sanitized filename, extension, and source path; files without an extension omit that segment. The source-id never exposes the raw path. For PDF/DOC/DOCX inputs, user-visible source labels and LLM source fields use only the sanitized filename/title, not the local parent directory or full path. Transcript reuse is temporary run input and does not change the two-file output contract.

## Document shortest path

For a PDF or DOCX, one execution with `--llm-refine` is the shortest final-delivery
path. Do not run a support-only pass first when the goal is the final `summary.md`:

```powershell
python "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --llm-refine
python "src/video_summary_cli.py" "D:/Documents/lecture.docx" --llm-refine
```

A second run is optional only when a caller manually edits or supplies transcript input for
that run. The logical support input may be named `support/transcript.txt`, but it
belongs to the temporary workspace, not `output/<source-id>/`, and is not persisted
as a cross-run cache. `--reuse-transcript` accepts only a local transcript
input explicitly supplied by the user, never historical transcript files from
`output/<source-id>/`; URLs are not accepted as transcript input.

```powershell
python "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --llm-refine
```

### Image-only PDF failure contract

For an image-only or scanned PDF, the exact contract is:

- phase: `PDF/DOCX文本提取`;
- the CLI exits non-zero;
- the message is `PDF 未提取到文本层，图像型 PDF 暂不支持`;
- it does not generate `summary.md` or a final draft;
- it does not fall back to audio download, transcription, or OCR.

## Compatibility

For backward compatibility only, `--reuse-transcript` may accept a
user-provided legacy root-level `transcript.txt` as local input. It never
discovers or reads historical transcript files from `output/<source-id>/`; this
input is not a published output or a cross-run cache.

## Processing rules

1. For PDF and OOXML Word inputs, extract document text directly before any media fallback.
2. Require a PDF text layer; reject image-only or scanned PDFs during document extraction without media fallback.
3. Prefer native subtitles from `yt-dlp` metadata for online videos.
4. If subtitles are unavailable, download audio and transcribe it locally.
5. Use `--cookies-from-browser chrome`, `edge`, or `firefox` when Bilibili or YouTube requires login state.
6. Use `--force-transcribe` only when subtitles are inaccurate or missing important speech.
7. Use `--reuse-transcript` only when the user explicitly supplies a local
   transcript input for the current run's temporary workspace; it never reads
   historical transcript files from `output/` and is not a cross-run cache. A
   legacy root-level `transcript.txt` is accepted only for compatibility. Do not
   combine it with `--force-transcribe`; the CLI rejects that conflict during
   argument validation（二者不能同时使用）。
8. Use `--template refined` for a richer internal draft: abstract, highlights,
   questions, terms, chapter summaries, and mind map. The compact/refined drafts
   summarize the transcript but do not include the complete transcript.
9. Use `--llm-refine` for semantic refinement; apply the Delivery decision above
   to determine whether the result is a final hand-off.
10. Keep every internal file, including optional timed transcript data, in the
    current run's temporary workspace; never publish it under `output/`.

## Quality modes

Choose the built-in local transcription model and language directly:

- Support material only: `--local-whisper-model tiny --template compact` (no final)
- Higher-quality support material: `--local-whisper-model small --language zh --template refined` (no final)
- Course/livestream notes: `--content-type lecture --llm-refine --domain zh-social --language zh`
- Review pass: `--reuse-transcript --llm-refine` after editing transcript input
  in the temporary workspace
- Best quality: produce or edit high-quality transcript input in the temporary
  workspace, then run `--reuse-transcript --llm-refine`

`compact` is the concise deterministic/offline template; `refined` is the richer structured template with chapter and term sections.
The CLI option `--template compact|refined` selects these two output roles.

Local transcription defaults to `--language auto`. Keep `--language zh` for Chinese courses when fixed-language recognition gives better terminology stability.

The built-in `summary_draft.md` is an offline extractive draft in the temporary
workspace, not a final deliverable. Use the Delivery decision above for hand-off rules.

For long lecture transcripts, `--llm-refine` summarizes chronological chunks first and then merges those chunk summaries into the final `summary.md`. Lecture requests are split at 12,000 characters or less to keep provider requests below timeout-prone payload sizes while preserving chronological coverage. `summary_chunks.json` may exist only in the current run's temporary workspace; it is not written to `output/` or any cross-run disk cache and must not be reused across runs.

Use `--domain general` by default for technical videos, business interviews, English media, and mixed-topic content. Use `--domain zh-social` only for Chinese relationship/social-skill courses where the bundled terminology helps correct ASR and extract terms.

Timed outputs are generated from VTT, SRT, common JSON subtitle formats, local ASR segments, or timed transcript lines such as `[00:10] text`. ASS/SSA/XML subtitles currently fall back to plain transcript text without segment timestamps.

## LLM refinement

Set local environment variables before semantic refinement:

```powershell
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-5.4-mini"
```

The CLI auto-loads `.local.env` from the project root (the workspace root for this repository) without overriding existing environment variables.

Run refinement from the canonical entry point. Only a successful command
publishes the final files:

```powershell
python "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --llm-refine
```

After the command exits, apply the Delivery decision above. Support material,
drafts, caches, and archives from an unsuccessful run are never final delivery.

Use `--llm-api responses` for the OpenAI Responses API. Use `--llm-api chat` for OpenAI-compatible services that only support Chat Completions. Override `OPENAI_BASE_URL` for compatible providers.

To reuse Codex's non-secret local configuration, run:

```powershell
python "src/video_summary_cli.py" "D:/Documents/lecture.pdf" --reuse-transcript --template refined --llm-refine --use-codex-config
```

This reads `~/.codex/config.toml` for model, API style, and base URL only. It does not read or copy Codex login credentials. `OPENAI_API_KEY` must still be set in the environment.

## Dependencies

Required:

```powershell
python -m pip install -r requirements.txt
```

Text-layer PDF input requires `pypdf`. Image-only or scanned PDFs without an
extractable text layer are unsupported; the CLI reports a readable
PDF/DOCX extraction-stage error and does not fall back to OCR, Tesseract,
`ocrmypdf`, `pdftoppm`, or an external OCR service. `.doc`/`.docx` support
covers OOXML containers; legacy binary `.doc` files are rejected with an
explicit format error.

Fallback transcription requires `ffmpeg` available on `PATH` for audio extraction. Local transcription uses CPU `faster-whisper`; install it in a compatible Python environment when local audio transcription is needed.

Do not ask users to paste API keys into chat. Read keys only from local environment variables.

## Output guidelines

Generate concise Simplified Chinese summaries by default when the source or user request is Chinese. Preserve source terminology when translation would reduce precision.

Use Mermaid mindmap syntax:

```mermaid
mindmap
  root((Video topic))
    Outline
    Key points
    Terms
```

If extraction fails, report the exact failed phase: metadata, subtitle fetch,
audio download, transcription, document reading, or output generation. For PDF
input that cannot be read, use
`ERROR: 阶段=PDF/DOCX文本提取；PDF 文件损坏或无法读取`; when PDF/DOCX text is
empty or too short, use
`ERROR: 阶段=PDF/DOCX文本提取；文档文本为空或过短`. These document errors must
not be written as transcription failures. The canonical CLI reports operational
failures as `ERROR: 阶段=<phase>；<readable reason>`, returns non-zero, preserves
the original reason, and does not print a full traceback.
