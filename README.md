# YouTube Channel Transcription & Analysis Pipeline

Fetch, transcribe, summarize, and curate videos from YouTube channels. YouTube captions preferred, AssemblyAI as fallback. Summaries are generated with Claude, then iteratively analyzed and pruned to remove off-topic content. Multiple channels can be merged into a unified taxonomy and consolidated into deduplicated reference documents.

## Setup

Requires Python 3.10+ and FFmpeg.

```bash
# Option A: conda environment file (includes all deps)
conda env create -f environment.yml
conda activate transcriber

# Option B: manual setup
conda create -n transcriber python=3.11
conda activate transcriber
pip install -r requirements.txt
```

Install FFmpeg:

```bash
sudo apt install ffmpeg           # Debian/Ubuntu
brew install ffmpeg               # macOS
```

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (for summarize/analyze/consolidate) | Claude API access |
| `ASSEMBLYAI_API_KEY` | Only if YouTube captions unavailable | AssemblyAI transcription fallback |
| `ANTHROPIC_MODEL` | No | Override default model (default: `claude-sonnet-4-5-20250929`) |
| `WEBSHARE_PROXY_USER` | No | Webshare rotating proxy username |
| `WEBSHARE_PROXY_PASS` | No | Webshare rotating proxy password |

All API keys can also be passed as CLI flags (`--anthropic-key`, `--assemblyai-key`, etc.).

## Quick start

```bash
# 1. Fetch + transcribe a channel's videos since a date
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output

# 2. Summarize all transcripts
python summarize.py output/SomeChannel/ --prompt-file summary_prompt.txt

# 3. Iteratively prune outliers
python analyze.py output/SomeChannel/ --prompt-file find_outliers.txt
python prune.py output/SomeChannel/
# Repeat until "No outlier URLs found"

# 4. Discover categories, build prompt, categorize, and split
python analyze.py output/SomeChannel/ --prompt-file discover_categories.txt --titles-only
python build_prompt.py output/SomeChannel/analysis.md
python analyze.py output/SomeChannel/ --prompt-file categorize_run.txt --batch-size 20
python split.py output/SomeChannel/
```

### Multi-channel workflow

After processing multiple channels individually:

```bash
# 5. Merge per-channel categories into a unified taxonomy
python merge.py output/

# 6. Consolidate (deduplicate) across creators
python consolidate.py output/_merged/ -o output/_consolidated/
```

## Commands

### channeltool.py

Three subcommands for fetching and transcribing:

#### `fetch`

Scans a YouTube channel's videos tab, filters by date and duration (>=120s, excludes Shorts), and writes `index.json`.

```
python channeltool.py fetch <channel_url> --after YYYY-MM-DD -o ./output
```

#### `transcribe`

Transcribes all `pending` videos in `index.json`. Tries YouTube captions first; falls back to AssemblyAI + Claude if API keys are provided.

```
python channeltool.py transcribe -o ./output/SomeChannel [--enhance] [--include-timestamps] [--lang LANG]
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--enhance` | off | Run YouTube captions through Claude for readability cleanup |
| `--include-timestamps` | off | Include timestamps in transcript output |
| `--lang LANG` | `en` | Caption language code |
| `--webshare-user` / `--webshare-pass` | env vars | Proxy credentials (see [Proxy support](#proxy-support)) |

#### `run`

Fetch + transcribe in one step. Accepts all options from both commands.

```
python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output [--enhance] [--include-timestamps]
```

### summarize.py

Generate a Claude-powered summary for each transcribed video, appended to a single markdown file.

```
python summarize.py <dir>/ [--prompt-file summary_prompt.txt] [-o summaries.md] [--concurrency 5] [--limit N]
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--prompt-file` | built-in prompt | Custom summarization prompt |
| `--concurrency` | 5 | Max parallel API calls |
| `--limit` | unlimited | Max videos to summarize in this run |

Resumable: already-summarized video IDs are detected and skipped on re-run.

### analyze.py

Run a chunked analysis over summaries using a prompt file. Summaries are split into batches, each sent to Claude, and responses are concatenated.

```
python analyze.py <dir>/ --prompt-file <prompt.txt> [--batch-size 20] [-o analysis.md] [--concurrency 5]
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--prompt-file` | (required) | Analysis prompt file |
| `--batch-size` | 20 | Max summaries per API request |
| `--concurrency` | 5 | Max parallel API calls |
| `--titles-only` | off | Send only video titles in a single call (for lightweight tasks) |

Auto-detects the latest `summaries_vN.md` in the directory (falls back to `summaries.md`). Output defaults to `<dir>/analysis.md` (always overwritten).

### prune.py

Remove outlier videos identified by `analyze.py` from the summaries file.

```
python prune.py <dir>/ [--analysis analysis.md] [--overwrite] [-o output.md]
```

- By default reads `<dir>/analysis.md` and the latest `summaries_vN.md`
- Writes a new versioned file: `summaries_v2.md`, `summaries_v3.md`, etc.
- `--overwrite` — replace the source file in place instead of versioning

### split.py

Split categorized summaries into per-category markdown files.

```
python split.py <dir>/ [--analysis analysis.md] [-o <dir>/categories/]
```

- Reads `analysis.md` for category assignments (matched by URL)
- Writes one file per category into `<dir>/categories/`
- Unmatched sections go to `uncategorized.md`

### build_prompt.py

Inject discovered categories into the categorization template.

```
python build_prompt.py <dir>/analysis.md [--template categorize_template.txt] [-o categorize_run.txt]
```

Reads categories from `analysis.md` (output of `discover_categories.txt` run), substitutes the `{categories}` placeholder in the template, and writes the ready-to-use prompt file.

### merge.py

Merge per-channel category files into a unified cross-channel taxonomy.

```
python merge.py output/ [-o output/_merged] [--min-categories 5] [--max-categories 10]
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--taxonomy-file` | — | Reuse existing taxonomy JSON instead of calling the LLM |
| `--min-categories` | 5 | Minimum unified categories |
| `--max-categories` | 10 | Maximum unified categories |
| `--dry-run` | off | Show prompt and taxonomy without writing files |

- Reads `output/<channel>/categories/*.md` across all channels
- LLM proposes a unified taxonomy and maps each channel's categories to it
- Saves `taxonomy.json` for reproducibility
- Adding a new channel: run its pipeline independently, then re-run `merge.py`

### consolidate.py

Deduplicate content across merged category files. Many videos from different creators cover the same advice — consolidation removes redundancy while preserving unique insights.

```
python consolidate.py <file_or_dir> [-o output/_consolidated/] [--chunk-tokens 20000]
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--chunk-tokens` | 20000 | Tokens per chunk for large files |
| `--skip-existing` | off | Skip already-consolidated files on re-run |
| `--dry-run` | off | Show chunking plan without API calls |

- Small categories (under ~30k tokens): single-pass consolidation
- Large categories: chunked consolidation + final merge pass
- Output includes a stats header (original vs consolidated token count)

## Prompt files

Analysis behavior is controlled by `.txt` prompt files passed to `analyze.py` via `--prompt-file`, and to `summarize.py`:

| File | Used with | Purpose |
|------|-----------|---------|
| `summary_prompt.txt` | `summarize.py` | Per-video summarization instructions |
| `find_outliers.txt` | `analyze.py` | Identify off-topic / promotional / non-teaching videos |
| `discover_categories.txt` | `analyze.py --titles-only` | Discover natural themes from video titles |
| `categorize_template.txt` | `build_prompt.py` | Template with `{categories}` placeholder for categorization |
| `categorize_run.txt` | `analyze.py` | Generated by `build_prompt.py` — ready-to-use categorization prompt |

Edit the number in `discover_categories.txt` ("Identify 5 natural themes...") to control category granularity.

## Proxy support

YouTube may block transcript requests from cloud provider IPs (or after heavy use). Route requests through [Webshare](https://www.webshare.io/) rotating residential proxies:

```bash
# Via CLI flags
python channeltool.py transcribe -o ./output/SomeChannel --webshare-user USER --webshare-pass PASS

# Via environment variables
export WEBSHARE_PROXY_USER=USER
export WEBSHARE_PROXY_PASS=PASS
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output
```

The standalone `yttranscribe.py` also supports the same flags. When no credentials are provided, requests go direct.

## Output structure

```
output/
  SomeChannel/                          # auto-created from @SomeChannel URL
    index.json                          # manifest with video metadata + channel info
    transcripts/
      2025-01-15_<video-id>.md          # markdown with YAML frontmatter
      2025-01-20_<video-id>.md
    summaries.md                        # initial summaries (all videos)
    summaries_v2.md                     # after first prune pass
    summaries_v3.md                     # after second prune pass, etc.
    analysis.md                         # latest analysis output (always overwritten)
    categories/                         # per-category split files
      interview_prep.md
      resume_and_applications.md
  AnotherChannel/
    ...
  _merged/                              # cross-channel unified categories
    taxonomy.json                       # mapping from per-channel → unified names
    interview_preparation_and_techniques.md
    salary_negotiation_and_compensation.md
  _consolidated/                        # deduplicated reference docs
    interview_preparation_and_techniques.md
    salary_negotiation_and_compensation.md
```

All scripts are resumable — re-running transcription, summarization, or consolidation skips already-completed items.

## Standalone scripts

| Script | Purpose |
|--------|---------|
| `getaudio.py` | Download audio from a single YouTube video (`input.mp3`) |
| `yttranscribe.py` | Download YouTube captions for a single video (supports `--chat` for interactive Q&A) |
| `transcribe.py` | Transcribe an audio file with AssemblyAI + enhance with Claude |
| `recorder.py` | Screen + audio recorder for Linux using ffmpeg (unrelated utility) |
