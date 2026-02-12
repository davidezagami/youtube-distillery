#!/usr/bin/env python3
"""Download a YouTube video transcript and save it to a file."""

import sys
import re
import argparse
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from a YouTube URL or return as-is if already an ID."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format."""
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def download_transcript(video_id: str, lang: str = "en") -> list:
    """Fetch transcript, preferring manual captions over auto-generated."""
    ytt_api = YouTubeTranscriptApi()

    transcript_list = ytt_api.list(video_id)

    try:
        transcript = transcript_list.find_transcript([lang])
    except Exception:
        transcript = transcript_list.find_generated_transcript([lang])

    return transcript.fetch()


def clean_text(text: str) -> str:
    """Clean extraneous characters from transcript text."""
    text = text.replace("\xa0", " ")
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def deduplicate(entries) -> list:
    """Remove consecutive duplicate lines, keeping the earliest timestamp."""
    seen_text = None
    deduped = []
    for entry in entries:
        text = clean_text(entry.text.replace("\n", " "))
        if text != seen_text:
            deduped.append(entry)
            seen_text = text
    return deduped


def entries_to_plain_text(entries) -> str:
    """Convert transcript entries to plain text without timestamps."""
    lines = []
    for entry in entries:
        text = clean_text(entry.text.replace("\n", " "))
        if text:
            lines.append(text)
    return "\n".join(lines)


def save_transcript(entries, output_path: str, video_id: str, timestamps: bool = True) -> None:
    """Write transcript to a markdown file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Transcript\n\n")
        f.write(f"**Source:** https://www.youtube.com/watch?v={video_id}\n\n---\n\n")

        for entry in entries:
            text = clean_text(entry.text.replace("\n", " "))
            if timestamps:
                ts = format_timestamp(entry.start)
                f.write(f"**[{ts}]** {text}\n\n")
            else:
                f.write(f"{text}\n\n")


def interactive_chat(entries, video_id: str) -> None:
    """Start an interactive chat session about the transcript using OpenAI ChatGPT 5.2."""
    from openai import OpenAI

    client = OpenAI()
    transcript_text = entries_to_plain_text(entries)

    # ChatGPT-aligned model alias
    model = "gpt-5.2-chat-latest"  # :contentReference[oaicite:2]{index=2}

    # thinking=auto: we do NOT set reasoning.effort unless you change this.
    # If you want to force "thinking", set to one of: none, low, medium, high, xhigh :contentReference[oaicite:3]{index=3}
    thinking = "auto"  # "auto" = let the model default decide

    system_prompt = (
        "You are a helpful assistant. The user has provided a transcript from a YouTube video. "
        "Answer their questions about it. Be concise and helpful."
    )

    previous_response_id = None

    print("\n" + "=" * 60)
    print("  AI Chat (powered by OpenAI ChatGPT 5.2)")
    print("=" * 60)
    print(f"  Video: https://www.youtube.com/watch?v={video_id}")
    print(f"  Transcript loaded ({len(transcript_text):,} chars)")
    print()
    print("  The transcript will be included with your first message.")
    print("  Try: \"Summarize this video\" or \"What are the key points?\"")
    print("  Type 'quit' or 'exit' to end the session.")
    print("=" * 60 + "\n")

    first_turn = True

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            break

        # Prepend the transcript to the first user message only
        if first_turn:
            content = (
                f"Here is the transcript of a YouTube video:\n\n"
                f"<transcript>\n{transcript_text}\n</transcript>\n\n"
                f"{user_input}"
            )
            first_turn = False
        else:
            content = user_input

        try:
            # Stream the response (semantic streaming events). :contentReference[oaicite:4]{index=4}
            print("\nChatGPT: ", end="", flush=True)

            req = dict(
                model=model,
                instructions=system_prompt,
                input=[{"role": "user", "content": content}],
                stream=True,
            )

            if previous_response_id is not None:
                req["previous_response_id"] = previous_response_id

            if thinking != "auto":
                req["reasoning"] = {"effort": thinking}
                # (Optional) If you ever want a visible summary of reasoning, you can add:
                # req["reasoning"]["summary"] = "auto"  # :contentReference[oaicite:5]{index=5}

            stream = client.responses.create(**req)

            full_response = ""
            for event in stream:
                etype = getattr(event, "type", None)

                if etype == "response.output_text.delta":
                    delta = event.delta
                    print(delta, end="", flush=True)
                    full_response += delta

                elif etype == "response.refusal.delta":
                    # If the model refuses, stream the refusal text.
                    delta = event.delta
                    print(delta, end="", flush=True)
                    full_response += delta

                elif etype == "response.completed":
                    # Save conversation state for the next turn.
                    previous_response_id = event.response.id

                elif etype == "error":
                    # Some SDKs emit an explicit error event; raise to hit except block.
                    raise RuntimeError(getattr(event, "message", "Unknown streaming error"))

            print("\n")

        except Exception as e:
            print(f"\nError: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Download a YouTube video transcript.")
    parser.add_argument("url", help="YouTube URL or video ID")
    parser.add_argument("output", nargs="?", default="transcript.md", help="Output file (default: transcript.md)")
    parser.add_argument("--no-timestamps", action="store_true", help="Omit timestamps from output")
    parser.add_argument("--chat", action="store_true", help="Start an interactive AI chat about the transcript")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    print(f"Fetching transcript for video: {video_id}")

    entries = download_transcript(video_id)
    entries = deduplicate(entries)
    save_transcript(entries, args.output, video_id, timestamps=not args.no_timestamps)

    print(f"Saved {len(entries)} entries to {args.output}")

    if args.chat:
        interactive_chat(entries, video_id)


if __name__ == "__main__":
    main()
