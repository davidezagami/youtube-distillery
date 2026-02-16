# YouTube Channel Transcription & Analysis Pipeline

Fetch, transcribe, summarize, and curate videos from YouTube channels. YouTube captions preferred, AssemblyAI as fallback. Summaries are generated with Claude, then iteratively analyzed and pruned to remove off-topic content.

## Setup

Requires Python 3.10+. A conda environment file is included:

```bash
conda env create -f environment.yml   # creates the 'transcriber' env with all deps
conda activate transcriber
```

Or set up manually:

```bash
conda create -n transcriber python=3.11
conda activate transcriber
pip install -r requirements.txt
```

FFmpeg is also required (for audio download/conversion):

```bash
sudo apt install ffmpeg           # Debian/Ubuntu
brew install ffmpeg               # macOS
```

## Quick start

```bash
# 1. Fetch video list from a channel (after a date) — output goes to output/<channel>/
python channeltool.py fetch https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output

# 2. Transcribe all pending videos (YouTube captions only — no API keys needed)
python channeltool.py transcribe -o ./output/SomeChannel

# 3. Or do both in one step
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output

# 4. Summarize all transcripts (pass the channel-specific directory)
python summarize.py output/SomeChannel/ --prompt-file summary_prompt.txt

# 5. Analyze summaries for outliers, then prune them (repeatable loop)
python analyze.py output/SomeChannel/ --prompt-file find_outliers.txt
python prune.py output/SomeChannel/
# Re-run analyze + prune until no outliers remain — each cycle auto-detects the latest summaries_vN.md
```

## Commands

### `fetch`

Scans a YouTube channel's videos tab, filters by date and duration (≥120s, excludes Shorts), and writes `index.json`.

```
python channeltool.py fetch <channel_url> --after YYYY-MM-DD -o ./output
# Creates output/<channel>/index.json
```

### `transcribe`

Transcribes all `pending` videos in `index.json`. Tries YouTube captions first; falls back to AssemblyAI + Claude if API keys are provided. Takes the channel-specific directory (e.g. `output/SomeChannel`).

```
python channeltool.py transcribe -o ./output/SomeChannel [--enhance] [--no-timestamps] [--lang LANG] [--assemblyai-key KEY] [--anthropic-key KEY]
```

- `--enhance` — run YouTube captions through Claude for readability cleanup (off by default)
- `--no-timestamps` — strip timestamps for clean text output (useful for LLM ingestion)
- `--lang LANG` — caption language code (default: `en`)
- API keys can also be set via `ASSEMBLYAI_API_KEY` and `ANTHROPIC_API_KEY` env vars

### `run`

Fetch + transcribe in one step. Accepts all options from both commands.

```
python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output [--enhance] [--no-timestamps] [--lang LANG]
# Creates output/<channel>/ with index.json + transcripts/
```

## Proxy support

YouTube may block transcript requests from cloud provider IPs (or after heavy use). You can route requests through [Webshare](https://www.webshare.io/) rotating residential proxies:

```bash
# Via CLI flags
python channeltool.py transcribe -o ./output --webshare-user USER --webshare-pass PASS

# Via environment variables
export WEBSHARE_PROXY_USER=USER
export WEBSHARE_PROXY_PASS=PASS
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output
```

The standalone script also supports the same flags:

```bash
python yttranscribe.py VIDEO_URL --webshare-user USER --webshare-pass PASS
```

When no proxy credentials are provided, requests go direct (unchanged behaviour).

## Summarize

Generate a Claude-powered summary for each transcribed video, appended to a single markdown file.

```
python summarize.py <dir>/ [--prompt-file summary_prompt.txt] [-o summaries.md] [--concurrency 10]
```

- `--prompt-file` — custom summarization prompt (defaults to a built-in "key points + bullet points" prompt)
- `--concurrency` — max parallel API calls (default: 5)
- Resumable: already-summarized video IDs are detected and skipped on re-run

## Analyze

Run a chunked analysis over summaries using a prompt file. Summaries are split into batches, each sent to Claude, and responses are concatenated.

```
python analyze.py <dir>/ --prompt-file <prompt.txt> [--batch-size 20] [-o analysis.md] [--concurrency 5]
```

- `--titles-only` — send only video titles (not full summaries) in a single API call; useful for lightweight discovery tasks

Included prompt files:

| File | Purpose |
|------|---------|
| `find_outliers.txt` | Identify off-topic / promotional / non-teaching videos |
| `discover_categories.txt` | Discover natural themes from video titles (used with `--titles-only`) |
| `categorize_template.txt` | Template for categorization with `{categories}` placeholder |

Auto-detects the latest `summaries_vN.md` in the directory (falls back to `summaries.md`). Output defaults to `<dir>/analysis.md` (always overwritten).

## Prune

Remove outlier videos identified by `analyze.py` from the summaries file.

```
python prune.py <dir>/ [--analysis analysis.md] [--overwrite] [-o output.md]
```

- By default reads `<dir>/analysis.md` and the latest `summaries_vN.md`
- Writes a new versioned file: `summaries_v2.md`, `summaries_v3.md`, etc.
- `--overwrite` — replace the source file in place instead of versioning
- `-o` — explicit output path

## Categorize + Split

Full pipeline after summarization: prune outliers, then discover and assign categories.

```bash
# 1. Find outliers (off-topic, vlogs, promos)
python analyze.py <dir>/ --prompt-file find_outliers.txt --batch-size 20

# 2. Prune them from summaries (creates summaries_v2.md, v3, etc.)
python prune.py <dir>/
# Repeat steps 1-2 until no outliers remain

# 3. Discover categories from titles only (lightweight, single API call)
python analyze.py <dir>/ --prompt-file discover_categories.txt --titles-only

# 4. Build the categorization prompt with discovered categories
python build_prompt.py <dir>/analysis.md

# 5. Categorize videos using full summaries (batched)
python analyze.py <dir>/ --prompt-file categorize_run.txt --batch-size 20

# 6. Split into per-category files
python split.py <dir>/
```

Edit the number in `discover_categories.txt` ("Identify 5 natural themes...") to control granularity. `build_prompt.py` injects the discovered categories into `categorize_template.txt` and writes `categorize_run.txt`.

- Reads `analysis.md` for category assignments (matched by URL)
- Writes one markdown file per category into `<dir>/categories/` (e.g. `interview_prep.md`, `resume_and_applications.md`)
- Sections with no matching URL go to `uncategorized.md`
- `--analysis` — custom analysis file path
- `-o` — custom output directory (default: `<dir>/categories/`)

### Iterative analyze → prune loop

```bash
python analyze.py output/SomeChannel/ --prompt-file find_outliers.txt   # reads summaries.md → writes analysis.md
python prune.py output/SomeChannel/                                      # reads analysis.md + summaries.md → writes summaries_v2.md
python analyze.py output/SomeChannel/ --prompt-file find_outliers.txt   # reads summaries_v2.md → overwrites analysis.md
python prune.py output/SomeChannel/                                      # reads analysis.md + summaries_v2.md → writes summaries_v3.md
# repeat until "No outlier URLs found"
```

## Output structure

`fetch` and `run` automatically organize output by channel name:

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
    categories/                         # per-category split files (from split.py)
      interview_prep.md
      resume_and_applications.md
      ...
  AnotherChannel/                       # another channel's data
    ...
```

Re-running transcription/summarization skips already-completed items (resumable).

## Standalone scripts

| Script | Purpose |
|--------|---------|
| `getaudio.py` | Download audio from a single YouTube video |
| `yttranscribe.py` | Download YouTube captions for a single video (supports `--chat` for interactive Q&A via OpenAI) |
| `transcribe.py` | Transcribe audio with AssemblyAI + enhance with Claude |
| `recorder.py` | Screen + audio recorder for Linux using ffmpeg (unrelated utility) |
