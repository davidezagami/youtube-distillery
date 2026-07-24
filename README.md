# YouTube Channel Transcription & Analysis Pipeline

Fetch, transcribe, summarize, and curate videos from YouTube channels. YouTube captions preferred, AssemblyAI as fallback. Summaries and downstream LLM stages use Claude by default, with optional local non-interactive `codex exec` support. Multiple channels can be merged into a unified taxonomy and consolidated into deduplicated reference documents.

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
| `ANTHROPIC_API_KEY` | Yes for Anthropic-backed summarize/analyze/merge/consolidate | Claude API access |
| `ASSEMBLYAI_API_KEY` | Only if YouTube captions unavailable | AssemblyAI transcription fallback |
| `ANTHROPIC_MODEL` | No | Override default model (default: `claude-opus-4-6`) |
| `CODEX_MODEL` | No | Override Codex model for `codex-exec` stages (default: `gpt-5.3-codex`) |
| `CODEX_COMMAND` | No | Override Codex executable path/name (default: `codex`) |
| `CODEX_REASONING_EFFORT` | No | Override Codex reasoning effort (default: `low`) |
| `CODEX_VERBOSITY` | No | Override Codex response verbosity (default: `low`) |
| `CODEX_TIMEOUT` | No | Seconds to wait for each Codex call (default: `900`) |
| `WEBSHARE_PROXY_USER` | No | Webshare rotating proxy username |
| `WEBSHARE_PROXY_PASS` | No | Webshare rotating proxy password |

All API keys can also be passed as CLI flags (`--anthropic-key`, `--assemblyai-key`, etc.).

## Quick start

```bash
# 1. Standard path: fetch + transcribe a channel's videos since a date
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output

# Optional broad-channel path: fetch, triage titles, then transcribe kept videos
python channeltool.py fetch https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output
python index_triage.py discover output/SomeChannel/
python index_triage.py categorize output/SomeChannel/
python index_triage.py apply output/SomeChannel/ --keep-category "Sales, Closing, and Persuasion"
# Re-run the apply command with --apply after reviewing the dry-run counts, then:
python channeltool.py transcribe -o output/SomeChannel/

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
# 5. Optional: build one shared taxonomy across a selected group of channels
python group_categorize.py run output/ \
  --group-name sales \
  --channel SomeChannel \
  --channel AnotherChannel \
  --provider codex-exec

# 6. Merge per-channel categories into a unified taxonomy
python merge.py output/

# 7. Consolidate (deduplicate) across creators
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

### index_triage.py

Metadata-only triage before transcription. This is useful for broad channels where many videos should not be transcribed or summarized.

#### `discover`

Discover categories from `index.json` metadata only. Defaults to pending videos and writes `<dir>/index_categories.md`.

```
python index_triage.py discover <dir>/ --provider codex-exec
```

#### `categorize`

Categorize each indexed video into the discovered categories. Defaults to pending videos and writes `<dir>/index_categorizations.md`.

```
python index_triage.py categorize <dir>/ --provider codex-exec --batch-size 60
```

#### `apply`

Dry-run a category filter, then mark excluded videos with `excluded_pretranscription` when `--apply` is passed. `channeltool.py transcribe` only processes `pending` videos, so excluded videos are skipped while remaining in `index.json` for audit.

```
# Dry run
python index_triage.py apply <dir>/ --keep-category "Sales, Closing, and Persuasion"

# Apply after reviewing counts
python index_triage.py apply <dir>/ --keep-category "Sales, Closing, and Persuasion" --apply
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--provider` | `codex-exec` | Model provider for `discover` and `categorize`: `anthropic` or local non-interactive `codex-exec` |
| `--model` | provider env/default | Model override (`ANTHROPIC_MODEL` for Anthropic, `CODEX_MODEL` for `codex-exec`) |
| `--status` | `pending` | Video status included by `discover`/`categorize`; repeat or use `all` |
| `--batch-size` | 60 | Max videos per categorization call |
| `--keep-category` | required for apply unless dropping | Keep only selected categories; repeat for multiple categories |
| `--drop-category` | required for apply unless keeping | Exclude selected categories; repeat for multiple categories |
| `--input-status` | `pending` | Statuses eligible for update during `apply`; repeat for multiple statuses |
| `--uncategorized` | `keep` | Keep or exclude videos missing from the categorization file |
| `--excluded-status` | `excluded_pretranscription` | Status assigned to filtered-out videos |
| `--apply` | off | Actually update `index.json`; otherwise print a dry-run report |

`apply --apply` writes a timestamped `index.before_index_triage_*.json` backup before changing statuses.

### summarize.py

Generate a summary for each transcribed video, appended to a single markdown file.

```
python summarize.py <dir>/ [--prompt-file summary_prompt.txt] [-o summaries.md] [--concurrency 5] [--limit N]
python summarize.py <dir>/ --provider codex-exec --prompt-file summary_prompt.txt
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--prompt-file` | built-in prompt | Custom summarization prompt |
| `--provider` | `anthropic` | Model provider: `anthropic` or local non-interactive `codex-exec` |
| `--model` | provider env/default | Model override (`ANTHROPIC_MODEL` for Anthropic, `CODEX_MODEL` for `codex-exec`) |
| `--codex-command` | `codex` | Codex executable path/name for `codex-exec` |
| `--codex-reasoning-effort` | `low` | Codex reasoning effort for `codex-exec` |
| `--codex-verbosity` | `low` | Codex response verbosity for `codex-exec` |
| `--codex-timeout` | `900` | Seconds to wait for each Codex call |
| `--concurrency` | provider-specific | Max parallel model calls (default: 5 for Anthropic, 1 for `codex-exec`) |
| `--limit` | unlimited | Max videos to summarize in this run |
| `--video-id` | all transcribed videos | Limit a run to one specific YouTube video ID; repeat for multiple IDs |

Resumable: already-summarized video IDs are detected and skipped on re-run.

### extract_sales_quotes.py

Extract reusable sales-talk quotes from the manifest-defined sales corpus by
running one local non-interactive `codex exec` call per transcript.

```
python extract_sales_quotes.py
python extract_sales_quotes.py -o output/_sales_group/sales_talk_quotes.md
python extract_sales_quotes.py --video-id A_881tlXXa0 --limit 1
```

Defaults:

- Reads `output/_sales_group/manifest.json`
- Appends to `output/_sales_group/sales_talk_quotes.md`
- Uses `sales_quote_prompt.txt`
- Uses `gpt-5.5` unless `--model`, `CODEX_QUOTE_MODEL`, or `CODEX_MODEL` overrides it
- Uses `--codex-reasoning-effort none`

| Flag | Default | Purpose |
|------|---------|---------|
| `--manifest` | `output/_sales_group/manifest.json` | Manifest that defines the exact sales corpus video set |
| `--output` | `<manifest_dir>/sales_talk_quotes.md` | Output markdown file; re-runs resume by URL and append only new sections |
| `--prompt-file` | `sales_quote_prompt.txt` | Prompt template for quote selection |
| `--model` | `CODEX_QUOTE_MODEL`/`CODEX_MODEL`/`gpt-5.5` | Codex model override |
| `--codex-command` | `codex` | Codex executable path/name |
| `--codex-reasoning-effort` | `none` | Codex reasoning effort for quote extraction |
| `--codex-verbosity` | `low` | Codex response verbosity |
| `--codex-timeout` | `900` | Seconds to wait for each Codex call |
| `--concurrency` | `1` | Max parallel Codex calls |
| `--max-quotes` | `5` | Max quotes to keep per transcript |
| `--channel` | all manifest channels | Limit a run to one channel; repeat for multiple channels |
| `--video-id` | all manifest videos | Limit a run to one specific YouTube video ID; repeat for multiple IDs |
| `--limit` | unlimited | Max videos to process in this run |

The script records transcripts with no qualifying quotes as well, so interrupted
runs can resume cleanly from the same output file. Each kept quote includes the
specific sales situation where the phrasing should be used.

### analyze.py

Run a chunked analysis over summaries using a prompt file. Summaries are split into batches, each sent to the selected provider, and responses are concatenated.

```
python analyze.py <dir>/ --prompt-file <prompt.txt> [--batch-size 20] [-o analysis.md] [--concurrency 5]
python analyze.py <dir>/ --provider codex-exec --prompt-file <prompt.txt>
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--prompt-file` | (required) | Analysis prompt file |
| `--provider` | `anthropic` | Model provider: `anthropic` or local non-interactive `codex-exec` |
| `--model` | provider env/default | Model override (`ANTHROPIC_MODEL` for Anthropic, `CODEX_MODEL` for `codex-exec`) |
| `--codex-command` | `codex` | Codex executable path/name for `codex-exec` |
| `--codex-reasoning-effort` | `low` | Codex reasoning effort for `codex-exec` |
| `--codex-verbosity` | `low` | Codex response verbosity for `codex-exec` |
| `--codex-timeout` | `900` | Seconds to wait for each Codex call |
| `--batch-size` | 20 | Max summaries per API request |
| `--concurrency` | provider-specific | Max parallel model calls (default: 5 for Anthropic, 1 for `codex-exec`) |
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

### group_categorize.py

Discover and apply one shared taxonomy across selected channels. This is useful when per-channel category discovery would create duplicated or weaker category names.

```
python group_categorize.py inspect output/ --group-name sales --channel ChannelA --channel ChannelB
python group_categorize.py discover output/ --group-name sales --channel ChannelA --channel ChannelB --provider codex-exec
python group_categorize.py categorize output/ --group-name sales --channel ChannelA --channel ChannelB --provider codex-exec
python group_categorize.py split output/ --group-name sales --channel ChannelA --channel ChannelB
python group_categorize.py run output/ --group-name sales --channel ChannelA --channel ChannelB --provider codex-exec
```

Outputs default to `<output_dir>/_<group-name>_group/`:

| File | Purpose |
|------|---------|
| `categories.md` | Shared category list discovered from all selected titles |
| `categorizations.md` | URL-keyed categorization output for all selected videos |
| `analysis/<channel>.md` | Per-channel categorization audit in `split.py`-compatible format |
| `taxonomy.json` | Identity taxonomy for `merge.py --taxonomy-file` |
| `manifest.json` | Inputs, counts, and generated artifact paths |

`split` writes normal `<channel>/categories/*.md` files for only the selected channels. Use `--overwrite-categories` when replacing existing category files.

### merge.py

Merge per-channel category files into a unified cross-channel taxonomy.

```
python merge.py output/ [-o output/_merged] [--min-categories 5] [--max-categories 10]
python merge.py output/ --provider codex-exec
python merge.py output/ --include-channel SomeChannel --include-channel AnotherChannel -o output/_merged_subset
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--provider` | `anthropic` | Model provider for taxonomy generation |
| `--model` | provider env/default | Model override (`ANTHROPIC_MODEL` or `CODEX_MODEL`) |
| `--codex-command` | `codex` | Codex executable path/name for `codex-exec` |
| `--codex-reasoning-effort` | `low` | Codex reasoning effort for `codex-exec` |
| `--codex-verbosity` | `low` | Codex response verbosity for `codex-exec` |
| `--codex-timeout` | `900` | Seconds to wait for each Codex call |
| `--taxonomy-file` | — | Reuse existing taxonomy JSON instead of calling the LLM |
| `--min-categories` | 5 | Minimum unified categories |
| `--max-categories` | 10 | Maximum unified categories |
| `--include-channel` | — | Only include this channel folder; repeat for multiple channels |
| `--exclude-channel` | — | Exclude this channel folder; repeat for multiple channels |
| `--dry-run` | off | Show prompt and taxonomy without writing files |

- Reads `output/<channel>/categories/*.md` across all channels
- LLM proposes a unified taxonomy and maps each channel's categories to it
- Saves `taxonomy.json` for reproducibility
- Adding a new channel: run its pipeline independently, then re-run `merge.py`

### consolidate.py

Deduplicate content across merged category files. Many videos from different creators cover the same advice — consolidation removes redundancy while preserving unique insights.

```
python consolidate.py <file_or_dir> [-o output/_consolidated/] [--chunk-tokens 20000]
python consolidate.py <file_or_dir> --provider codex-exec [-o output/_consolidated/]
python consolidate.py <file_or_dir> --final-merge concat --save-intermediates
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--provider` | `anthropic` | Model provider: `anthropic` or local non-interactive `codex-exec` |
| `--model` | provider env/default | Model override (`ANTHROPIC_MODEL` or `CODEX_MODEL`) |
| `--codex-command` | `codex` | Codex executable path/name for `codex-exec` |
| `--codex-reasoning-effort` | `low` | Codex reasoning effort for `codex-exec` |
| `--codex-verbosity` | `low` | Codex response verbosity for `codex-exec` |
| `--codex-timeout` | `900` | Seconds to wait for each Codex call |
| `--chunk-tokens` | 20000 | Tokens per chunk for large files |
| `--final-merge` | `model` | Use `model` for an LLM final merge, or `concat` for deterministic concatenation of first-pass chunks |
| `--save-intermediates` | off | Save raw chunk inputs, consolidated chunks, and final merge input under `<output>/_chunks/` |
| `--intermediate-dir` | `<output>/_chunks` | Custom directory for `--save-intermediates` artifacts |
| `--skip-existing` | off | Skip already-consolidated files on re-run |
| `--dry-run` | off | Show chunking plan without API calls |

- Small categories (under ~30k tokens): single-pass consolidation
- Large categories: chunked consolidation + final merge pass, unless `--final-merge concat` is used
- Output includes a stats header (original vs consolidated token count)

## Prompt files

Analysis behavior is controlled by `.txt` prompt files passed to `analyze.py` via `--prompt-file`, and to `summarize.py`:

| File | Used with | Purpose |
|------|-----------|---------|
| `summary_prompt.txt` | `summarize.py` | Per-video summarization instructions |
| `discover_index_categories.txt` | `index_triage.py discover` | Discover practical pre-transcription categories from `index.json` metadata |
| `categorize_index_template.txt` | `index_triage.py categorize` | Template with `{categories}` placeholder for index-level categorization |
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
    index_categories.md                 # optional pre-transcription category list
    index_categorizations.md            # optional pre-transcription video categorization
    index.before_index_triage_*.json     # backup before applying pre-transcription exclusions
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
| `index_triage.py` | Discover categories, categorize videos, and filter `index.json` before transcription |
| `group_categorize.py` | Discover one shared taxonomy across selected channels and split them into compatible category files |
| `transcribe.py` | Transcribe an audio file with AssemblyAI + enhance with Claude |
| `recorder.py` | Screen + audio recorder for Linux using ffmpeg (unrelated utility) |
