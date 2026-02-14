# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A pipeline for scraping YouTube channels, transcribing videos, summarizing transcripts with Claude, and iteratively pruning outliers. All scripts are standalone Python CLIs with no shared framework — they communicate via files on disk.

## Setup

```bash
conda activate <env>        # Python 3.10+
pip install -r requirements.txt
# Also needs: ffmpeg (apt/brew install ffmpeg)
```

API keys via env vars: `ANTHROPIC_API_KEY`, `ASSEMBLYAI_API_KEY`. Optional proxy: `WEBSHARE_PROXY_USER` / `WEBSHARE_PROXY_PASS`.

## Pipeline

The typical workflow processes one channel directory (e.g. `output/andylacivita/`):

1. **Fetch + Transcribe** — `python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output` → creates `output/<channel>/`
2. **Summarize** — `python summarize.py output/<channel>/ --prompt-file summary_prompt.txt` → writes `summaries.md`
3. **Analyze** — `python analyze.py output/<channel>/ --prompt-file find_outliers.txt` → writes `analysis.md`
4. **Prune** — `python prune.py output/<channel>/` → reads `analysis.md`, writes `summaries_v2.md`
5. Repeat steps 3–4: analyze picks up latest `summaries_vN.md` automatically, prune writes `summaries_v(N+1).md`
6. **Categorize + Split** — `python analyze.py output/<channel>/ --prompt-file categorize.txt` → `analysis.md`, then `python split.py output/<channel>/` → `categories/*.md`

## Key Architecture Details

**Versioned summaries loop:** `analyze.py` and `prune.py` both have `find_latest_summaries()` which scans for the highest `summaries_vN.md`, falling back to `summaries.md`. `analysis.md` is always overwritten (unversioned). `prune.py`'s `next_version_path()` generates the next available `summaries_vN.md`.

**Transcription fallback chain:** `channeltool.py` tries YouTube captions first (`yttranscribe.py`), then AssemblyAI + Claude enhancement (`transcribe.py`). Each video's status is tracked in `index.json` and runs are resumable.

**Prompt files:** Analysis behavior is controlled by `.txt` prompt files passed via `--prompt-file`:
- `find_outliers.txt` — identifies off-topic videos (used with `analyze.py` → `prune.py`)
- `categorize.txt` — categorizes videos by theme
- `summary_prompt.txt` — per-video summarization prompt (used with `summarize.py`)

**Concurrency:** `summarize.py`, `analyze.py`, and `transcribe.py` use `asyncio` + `anthropic.AsyncAnthropic` with semaphore-based concurrency control.

## File Roles

| Script | Input | Output |
|---|---|---|
| `channeltool.py` | YouTube channel URL | `<output>/<channel>/index.json` + `transcripts/*.md` |
| `summarize.py` | `index.json` + transcripts | `summaries.md` |
| `analyze.py` | `summaries[_vN].md` + prompt file | `analysis.md` |
| `prune.py` | `summaries[_vN].md` + `analysis.md` | `summaries_v(N+1).md` |
| `split.py` | `summaries[_vN].md` + `analysis.md` | `categories/*.md` |
| `yttranscribe.py` | single video URL | transcript file (standalone) |
| `transcribe.py` | audio file | enhanced transcript (standalone) |
| `getaudio.py` | YouTube URL | `input.mp3` (standalone) |
| `recorder.py` | — | screen recording (unrelated utility) |
