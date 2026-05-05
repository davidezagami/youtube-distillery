# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## What This Is

A pipeline for scraping YouTube channels, transcribing videos, summarizing transcripts, and iteratively pruning outliers. LLM-backed stages use Claude by default and also support local non-interactive `codex exec`. All scripts are standalone Python CLIs with no shared framework — they communicate via files on disk.

## Setup

```bash
conda activate <env>        # Python 3.10+
pip install -r requirements.txt
# Also needs: ffmpeg (apt/brew install ffmpeg)
```

API keys via env vars: `ANTHROPIC_API_KEY` for Anthropic-backed LLM stages and `ASSEMBLYAI_API_KEY` for transcription fallback. Codex-backed LLM stages use the local `codex` CLI. Optional proxy: `WEBSHARE_PROXY_USER` / `WEBSHARE_PROXY_PASS`.

Useful model env vars:
- `ANTHROPIC_MODEL` — Anthropic model override
- `CODEX_MODEL` — shared Codex model override for `--provider codex-exec`
- `CODEX_REASONING_EFFORT` — Codex reasoning effort override, default `low`
- `CODEX_VERBOSITY` — Codex response verbosity override, default `low`
- `CODEX_TIMEOUT` — per-call Codex timeout in seconds, default `900`

## Pipeline

The typical workflow processes one channel directory (e.g. `output/andylacivita/`):

1. **Fetch + Transcribe** — `python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output` → creates `output/<channel>/`
2. **Summarize** — `python summarize.py output/<channel>/ --prompt-file summary_prompt.txt` → writes `summaries.md`; add `--provider codex-exec` to use local Codex
3. **Analyze** — `python analyze.py output/<channel>/ --prompt-file find_outliers.txt` → writes `analysis.md`; add `--provider codex-exec` to use local Codex
4. **Prune** — `python prune.py output/<channel>/` → reads `analysis.md`, writes `summaries_v2.md`
5. Repeat steps 3–4: analyze picks up latest `summaries_vN.md` automatically, prune writes `summaries_v(N+1).md`
6. **Categorize + Split** — `python analyze.py output/<channel>/ --prompt-file categorize_run.txt --batch-size 20` → `analysis.md`, then `python split.py output/<channel>/` → `categories/*.md`
7. **Merge + Consolidate** — `python merge.py output/` → `output/_merged/`, then `python consolidate.py output/_merged/ -o output/_consolidated/`; both support `--provider codex-exec`

## Key Architecture Details

**Versioned summaries loop:** `analyze.py` and `prune.py` both have `find_latest_summaries()` which scans for the highest `summaries_vN.md`, falling back to `summaries.md`. `analysis.md` is always overwritten (unversioned). `prune.py`'s `next_version_path()` generates the next available `summaries_vN.md`.

**Transcription fallback chain:** `channeltool.py` tries YouTube captions first (`yttranscribe.py`), then AssemblyAI + Claude enhancement (`transcribe.py`). Each video's status is tracked in `index.json` and runs are resumable.

**LLM providers:** `summarize.py`, `analyze.py`, `merge.py`, and `consolidate.py` default to Anthropic. Each accepts `--provider codex-exec` plus shared Codex flags from `llm_providers.py`. `summarize.py` sends one transcript per model call. `analyze.py` keeps the existing batching behavior: `--titles-only` is one call, otherwise `--batch-size` summaries per call. `merge.py` makes one taxonomy call unless `--taxonomy-file` is provided. `consolidate.py` makes one call for small files and chunk-plus-final-merge calls for large files.

**Prompt files:** Analysis behavior is controlled by `.txt` prompt files passed via `--prompt-file`:
- `find_outliers.txt` — identifies off-topic videos (used with `analyze.py` → `prune.py`)
- `discover_categories.txt` — discovers themes from titles
- `categorize_template.txt` — template filled by `build_prompt.py`
- `categorize_run.txt` — categorizes videos by theme after category discovery
- `summary_prompt.txt` — per-video summarization prompt (used with `summarize.py`)

**Concurrency:** `summarize.py`, `analyze.py`, and `transcribe.py` use `asyncio` with semaphore-based concurrency control. Defaults are 5 Anthropic calls and 1 Codex call for `summarize.py` and `analyze.py`.

## File Roles

| Script | Input | Output |
|---|---|---|
| `channeltool.py` | YouTube channel URL | `<output>/<channel>/index.json` + `transcripts/*.md` |
| `summarize.py` | `index.json` + transcripts | `summaries.md` |
| `analyze.py` | `summaries[_vN].md` + prompt file | `analysis.md` |
| `prune.py` | `summaries[_vN].md` + `analysis.md` | `summaries_v(N+1).md` |
| `split.py` | `summaries[_vN].md` + `analysis.md` | `categories/*.md` |
| `merge.py` | `output/<channel>/categories/*.md` | `output/_merged/*.md` + `taxonomy.json` |
| `consolidate.py` | `output/_merged/*.md` | `output/_consolidated/*.md` |
| `yttranscribe.py` | single video URL | transcript file (standalone) |
| `transcribe.py` | audio file | enhanced transcript (standalone) |
| `getaudio.py` | YouTube URL | `input.mp3` (standalone) |
| `recorder.py` | — | screen recording (unrelated utility) |
