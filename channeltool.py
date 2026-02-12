#!/usr/bin/env python3
"""Unified YouTube channel transcription CLI.

Fetches all non-Shorts videos from a YouTube channel (after a given date),
transcribes each (YouTube captions preferred, AssemblyAI as fallback),
and stores structured results for later LLM-based summarization.

Usage:
    python channeltool.py fetch <channel_url> --after YYYY-MM-DD -o ./output
    python channeltool.py transcribe -o ./output [--enhance] [--no-timestamps] [--lang LANG]
    python channeltool.py run <channel_url> --after YYYY-MM-DD -o ./output [--enhance] [--no-timestamps] [--lang LANG]
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
import yt_dlp

from yttranscribe import (
    download_transcript,
    deduplicate,
    clean_text,
    entries_to_plain_text,
    format_timestamp,
)
from transcribe import Transcriber, Enhancer, prepare_text_chunks


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------

def load_index(output_dir: Path) -> dict:
    """Load index.json from the output directory, or return an empty index."""
    index_path = output_dir / "index.json"
    if index_path.exists():
        return json.loads(index_path.read_text(encoding="utf-8"))
    return {"videos": []}


def save_index(output_dir: Path, index: dict) -> None:
    """Write index.json to the output directory."""
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


# ---------------------------------------------------------------------------
# Fetching channel videos
# ---------------------------------------------------------------------------

def fetch_channel_videos(channel_url: str, after_date: str) -> list[dict]:
    """Fetch non-Shorts videos from a YouTube channel uploaded after *after_date*.

    Returns a list of dicts with keys: id, title, url, upload_date, duration.
    """
    # Normalise to the /videos tab so yt-dlp lists uploads (excludes Shorts)
    if not channel_url.rstrip("/").endswith("/videos"):
        channel_url = channel_url.rstrip("/") + "/videos"

    print(f"Scanning channel: {channel_url}")
    print(f"Looking for videos after {after_date}")

    flat_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info or "entries" not in info:
        print("No videos found on this channel.")
        return []

    entries = list(info["entries"])
    print(f"Found {len(entries)} video entries, fetching metadata...")

    after_dt = datetime.strptime(after_date, "%Y-%m-%d")
    stale_streak = 0
    videos = []

    meta_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    for i, entry in enumerate(entries):
        video_id = entry.get("id") or entry.get("url")
        if not video_id:
            continue

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            with yt_dlp.YoutubeDL(meta_opts) as ydl:
                meta = ydl.extract_info(video_url, download=False)
        except Exception as exc:
            print(f"  [{i+1}/{len(entries)}] Could not fetch metadata for {video_id}: {exc}")
            time.sleep(1)
            continue

        upload_date_str = meta.get("upload_date", "")  # YYYYMMDD
        duration = meta.get("duration") or 0
        title = meta.get("title", "")

        # Parse upload date
        try:
            upload_dt = datetime.strptime(upload_date_str, "%Y%m%d")
        except (ValueError, TypeError):
            time.sleep(0.5)
            continue

        # Filter: too old → increment stale streak
        if upload_dt < after_dt:
            stale_streak += 1
            print(f"  [{i+1}/{len(entries)}] Skipping (before cutoff): {title} ({upload_date_str})")
            if stale_streak >= 3:
                print("  Early termination: 3 consecutive videos older than cutoff.")
                break
            time.sleep(0.5)
            continue

        stale_streak = 0

        # Filter: too short → likely a Short that slipped through
        if duration < 120:
            print(f"  [{i+1}/{len(entries)}] Skipping (< 120s): {title}")
            time.sleep(0.5)
            continue

        iso_date = upload_dt.strftime("%Y-%m-%d")
        print(f"  [{i+1}/{len(entries)}] {iso_date} | {title} ({duration}s)")

        videos.append({
            "id": video_id,
            "title": title,
            "url": video_url,
            "upload_date": iso_date,
            "duration": duration,
            "status": "pending",
        })

        time.sleep(0.5)

    print(f"\nCollected {len(videos)} videos after {after_date}.")
    return videos


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------

def transcribe_video_yt(video_id: str, lang: str = "en", timestamps: bool = True, proxy_config=None) -> str | None:
    """Try to get a YouTube caption transcript. Returns markdown text or None."""
    try:
        entries = download_transcript(video_id, lang=lang, proxy_config=proxy_config)
        entries = deduplicate(entries)
    except Exception as exc:
        print(f"    Caption fetch error: {exc}")
        return None

    if timestamps:
        lines = []
        for entry in entries:
            text = clean_text(entry.text.replace("\n", " "))
            if text:
                ts = format_timestamp(entry.start)
                lines.append(f"**[{ts}]** {text}")
        return "\n\n".join(lines) if lines else None
    else:
        return entries_to_plain_text(entries) or None


def download_audio_to(url: str, output_path: Path) -> Path:
    """Download audio from a YouTube URL to *output_path* (mp3)."""
    stem = str(output_path.with_suffix(""))  # yt-dlp adds extension after conversion
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": stem,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return Path(stem + ".mp3")


def transcribe_video_assemblyai(
    url: str,
    assemblyai_key: str,
    anthropic_key: str,
    model: str,
) -> str | None:
    """Download audio, transcribe with AssemblyAI, enhance with Claude.

    Returns enhanced markdown text or None on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = download_audio_to(url, Path(tmpdir) / "audio")
        if not audio_path.exists():
            return None

        transcriber = Transcriber(assemblyai_key)
        utterances = transcriber.transcribe(audio_path)
        if not utterances:
            return None

        enhancer = Enhancer(anthropic_key, model)
        chunks = prepare_text_chunks(utterances)
        enhanced = asyncio.run(enhancer.enhance_chunks(chunks))
        return "\n\n".join(chunk.strip() for chunk in enhanced)


def enhance_text(text: str, anthropic_key: str, model: str) -> str:
    """Run existing text through Claude's Enhancer for readability cleanup."""
    enhancer = Enhancer(anthropic_key, model)
    # Split into manageable chunks (~8000 chars each)
    max_chunk = 8000
    chunks = []
    while text:
        chunks.append(text[:max_chunk])
        text = text[max_chunk:]
    enhanced = asyncio.run(enhancer.enhance_chunks(chunks))
    return "\n\n".join(chunk.strip() for chunk in enhanced)


# ---------------------------------------------------------------------------
# Transcript file I/O
# ---------------------------------------------------------------------------

def save_transcript_file(
    output_dir: Path,
    video: dict,
    body: str,
    method: str,
) -> Path:
    """Save a transcript as a markdown file with YAML frontmatter."""
    transcripts_dir = output_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{video['upload_date']}_{video['id']}.md"
    path = transcripts_dir / filename

    frontmatter = (
        f"---\n"
        f"title: \"{video['title']}\"\n"
        f"url: {video['url']}\n"
        f"date: {video['upload_date']}\n"
        f"duration: {video['duration']}\n"
        f"method: {method}\n"
        f"---\n\n"
    )
    path.write_text(frontmatter + body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def process_videos(
    output_dir: Path,
    enhance: bool = False,
    assemblyai_key: str | None = None,
    anthropic_key: str | None = None,
    anthropic_model: str = "claude-sonnet-4-5-20250929",
    lang: str = "en",
    timestamps: bool = True,
    proxy_config=None,
) -> None:
    """Transcribe all pending videos in the index."""
    index = load_index(output_dir)
    videos = index.get("videos", [])

    pending = [v for v in videos if v.get("status") == "pending"]
    if not pending:
        print("No pending videos to transcribe.")
        return

    print(f"\n{len(pending)} pending video(s) to transcribe.\n")

    for i, video in enumerate(pending):
        print(f"[{i+1}/{len(pending)}] {video['title']}")

        body = None
        method = None

        # 1. Try YouTube captions
        print("  Trying YouTube captions...")
        body = transcribe_video_yt(video["id"], lang=lang, timestamps=timestamps, proxy_config=proxy_config)
        if body:
            method = "youtube-captions"
            if enhance and anthropic_key:
                print("  Enhancing with Claude...")
                body = enhance_text(body, anthropic_key, anthropic_model)
                method = "youtube-captions+enhanced"
            print("  Success (YouTube captions).")

        # 2. Fallback to AssemblyAI
        if body is None and assemblyai_key and anthropic_key:
            print("  YouTube captions unavailable, trying AssemblyAI...")
            try:
                body = transcribe_video_assemblyai(
                    video["url"], assemblyai_key, anthropic_key, anthropic_model,
                )
                if body:
                    method = "assemblyai+enhanced"
                    print("  Success (AssemblyAI).")
            except Exception as exc:
                print(f"  AssemblyAI failed: {exc}")

        # 3. Update status
        if body:
            path = save_transcript_file(output_dir, video, body, method)
            video["status"] = "transcribed"
            video["method"] = method
            video["transcript_file"] = str(path.relative_to(output_dir))
            print(f"  Saved to {path}")
        else:
            video["status"] = "failed"
            print("  FAILED — no transcript could be obtained.")

        # Save index after each video for resumability
        save_index(output_dir, index)

    done = sum(1 for v in videos if v["status"] == "transcribed")
    failed = sum(1 for v in videos if v["status"] == "failed")
    print(f"\nDone. {done} transcribed, {failed} failed, {len(videos)} total.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    videos = fetch_channel_videos(args.channel_url, args.after)
    if not videos:
        print("No new videos found.")
        return 0

    # Merge into existing index (avoid duplicates)
    index = load_index(output_dir)
    existing_ids = {v["id"] for v in index["videos"]}
    new_count = 0
    for v in videos:
        if v["id"] not in existing_ids:
            index["videos"].append(v)
            existing_ids.add(v["id"])
            new_count += 1

    save_index(output_dir, index)
    print(f"Index updated: {new_count} new video(s) added, {len(index['videos'])} total.")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    if not (output_dir / "index.json").exists():
        print(f"Error: no index.json found in {output_dir}. Run 'fetch' first.")
        return 1

    assemblyai_key = args.assemblyai_key or os.getenv("ASSEMBLYAI_API_KEY")
    anthropic_key = args.anthropic_key or os.getenv("ANTHROPIC_API_KEY")
    anthropic_model = args.model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    ws_user = args.webshare_user or os.getenv("WEBSHARE_PROXY_USER")
    ws_pass = args.webshare_pass or os.getenv("WEBSHARE_PROXY_PASS")
    if ws_user and ws_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        proxy_config = WebshareProxyConfig(proxy_username=ws_user, proxy_password=ws_pass)
    else:
        proxy_config = None

    process_videos(
        output_dir,
        enhance=args.enhance,
        assemblyai_key=assemblyai_key,
        anthropic_key=anthropic_key,
        anthropic_model=anthropic_model,
        lang=args.lang,
        timestamps=not args.no_timestamps,
        proxy_config=proxy_config,
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_fetch(args)
    if rc != 0:
        return rc
    return cmd_transcribe(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channeltool",
        description="Fetch and transcribe all videos from a YouTube channel.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- fetch --
    p_fetch = sub.add_parser("fetch", help="List channel videos and write/update index.json")
    p_fetch.add_argument("channel_url", help="YouTube channel URL")
    p_fetch.add_argument("--after", required=True,
                         help="Only include videos uploaded on or after this date (YYYY-MM-DD)")
    p_fetch.add_argument("-o", "--output", default="./output",
                         help="Output directory (default: ./output)")
    p_fetch.set_defaults(func=cmd_fetch)

    # -- transcribe --
    p_trans = sub.add_parser("transcribe", help="Transcribe all pending videos in the index")
    p_trans.add_argument("-o", "--output", default="./output",
                         help="Output directory (default: ./output)")
    p_trans.add_argument("--enhance", action="store_true",
                         help="Enhance YouTube captions with Claude for readability")
    p_trans.add_argument("--no-timestamps", action="store_true",
                         help="Strip timestamps for clean text output")
    p_trans.add_argument("--lang", default="en",
                         help="Caption language code (default: en)")
    p_trans.add_argument("--assemblyai-key", help="AssemblyAI API key (or ASSEMBLYAI_API_KEY env)")
    p_trans.add_argument("--anthropic-key", help="Anthropic API key (or ANTHROPIC_API_KEY env)")
    p_trans.add_argument("--model", help="Anthropic model (or ANTHROPIC_MODEL env)")
    p_trans.add_argument("--webshare-user", help="Webshare proxy username (or WEBSHARE_PROXY_USER env)")
    p_trans.add_argument("--webshare-pass", help="Webshare proxy password (or WEBSHARE_PROXY_PASS env)")
    p_trans.set_defaults(func=cmd_transcribe)

    # -- run --
    p_run = sub.add_parser("run", help="Fetch + transcribe in one step")
    p_run.add_argument("channel_url", help="YouTube channel URL")
    p_run.add_argument("--after", required=True,
                       help="Only include videos uploaded on or after this date (YYYY-MM-DD)")
    p_run.add_argument("-o", "--output", default="./output",
                       help="Output directory (default: ./output)")
    p_run.add_argument("--enhance", action="store_true",
                       help="Enhance YouTube captions with Claude for readability")
    p_run.add_argument("--no-timestamps", action="store_true",
                       help="Strip timestamps for clean text output")
    p_run.add_argument("--lang", default="en",
                       help="Caption language code (default: en)")
    p_run.add_argument("--assemblyai-key", help="AssemblyAI API key (or ASSEMBLYAI_API_KEY env)")
    p_run.add_argument("--anthropic-key", help="Anthropic API key (or ANTHROPIC_API_KEY env)")
    p_run.add_argument("--model", help="Anthropic model (or ANTHROPIC_MODEL env)")
    p_run.add_argument("--webshare-user", help="Webshare proxy username (or WEBSHARE_PROXY_USER env)")
    p_run.add_argument("--webshare-pass", help="Webshare proxy password (or WEBSHARE_PROXY_PASS env)")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
