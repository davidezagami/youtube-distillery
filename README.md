# YouTube Channel Transcription Tools

Fetch and transcribe all videos from a YouTube channel. YouTube captions preferred, AssemblyAI as fallback.

## Setup

Requires Python 3.10+.

```bash
conda activate <your-env>        # or create a new one: conda create -n recorders python=3.11
pip install -r requirements.txt
```

FFmpeg is also required (for audio download/conversion):

```bash
sudo apt install ffmpeg           # Debian/Ubuntu
brew install ffmpeg               # macOS
```

## Quick start

```bash
# 1. Fetch video list from a channel (after a date)
python channeltool.py fetch https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output

# 2. Transcribe all pending videos (YouTube captions only — no API keys needed)
python channeltool.py transcribe -o ./output

# 3. Or do both in one step
python channeltool.py run https://www.youtube.com/@SomeChannel --after 2025-01-01 -o ./output
```

## Commands

### `fetch`

Scans a YouTube channel's videos tab, filters by date and duration (≥120s, excludes Shorts), and writes `index.json`.

```
python channeltool.py fetch <channel_url> --after YYYY-MM-DD -o ./output
```

### `transcribe`

Transcribes all `pending` videos in `index.json`. Tries YouTube captions first; falls back to AssemblyAI + Claude if API keys are provided.

```
python channeltool.py transcribe -o ./output [--enhance] [--no-timestamps] [--lang LANG] [--assemblyai-key KEY] [--anthropic-key KEY]
```

- `--enhance` — run YouTube captions through Claude for readability cleanup (off by default)
- `--no-timestamps` — strip timestamps for clean text output (useful for LLM ingestion)
- `--lang LANG` — caption language code (default: `en`)
- API keys can also be set via `ASSEMBLYAI_API_KEY` and `ANTHROPIC_API_KEY` env vars

### `run`

Fetch + transcribe in one step. Accepts all options from both commands.

```
python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output [--enhance] [--no-timestamps] [--lang LANG]
```

## Output structure

```
output/
  index.json                          # manifest with video metadata + status
  transcripts/
    2025-01-15_<video-id>.md          # markdown with YAML frontmatter
    2025-01-20_<video-id>.md
```

Re-running skips already-transcribed videos (resumable).

## Standalone scripts

| Script | Purpose |
|--------|---------|
| `getaudio.py` | Download audio from a single YouTube video |
| `yttranscribe.py` | Download YouTube captions for a single video |
| `transcribe.py` | Transcribe audio with AssemblyAI + enhance with Claude |
