#!/usr/bin/env python3
"""Minimal screen + audio recorder for Linux using ffmpeg.

Records screen (X11 or Wayland), microphone, and speaker output,
mixing both audio streams into a single MP4 file.

Requirements:
    - ffmpeg
    - PulseAudio or PipeWire (with PulseAudio compat)

Usage:
    python record_screen.py [output.mp4]
    Press 'q' then Enter to stop recording.
"""

import subprocess
import sys
import shutil


def _pactl_info() -> dict[str, str]:
    """Parse 'pactl info' into a dict."""
    result = subprocess.run(
        ["pactl", "info"],
        capture_output=True, text=True, check=True,
    )
    info = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()
    return info


def get_default_mic() -> str:
    """Return the PulseAudio default source (microphone) name."""
    return _pactl_info()["Default Source"]


def get_speaker_monitor() -> str:
    """Return the monitor source for the default PulseAudio sink (speaker loopback)."""
    return _pactl_info()["Default Sink"] + ".monitor"


def get_screen_size() -> str:
    """Return the screen resolution as WxH using xdpyinfo."""
    result = subprocess.run(
        ["xdpyinfo"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "dimensions:" in line:
            return line.split()[1].split("+")[0]  # e.g. "1920x1080"
    return "1920x1080"


def is_wayland() -> bool:
    import os
    return "WAYLAND_DISPLAY" in os.environ


def build_command(output_file: str) -> list[str]:
    mic = get_default_mic()
    speaker = get_speaker_monitor()

    print(f"Microphone : {mic}")
    print(f"Speaker mon: {speaker}")

    cmd = ["ffmpeg", "-y"]

    # Video input
    if is_wayland():
        # PipeWire screen capture for Wayland
        cmd += [
            "-f", "pipewire",
            "-framerate", "30",
            "-i", "default",
        ]
    else:
        size = get_screen_size()
        print(f"Screen size: {size}")
        cmd += [
            "-video_size", size,
            "-framerate", "30",
            "-f", "x11grab",
            "-i", ":0.0",
        ]

    # Audio inputs
    cmd += [
        "-f", "pulse", "-i", mic,       # microphone
        "-f", "pulse", "-i", speaker,    # speaker loopback
    ]

    # Mix audio + encode
    cmd += [
        "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        output_file,
    ]

    return cmd


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("Error: ffmpeg not found. Install it with: sudo apt install ffmpeg")
    if not shutil.which("pactl"):
        sys.exit("Error: pactl not found. Install it with: sudo apt install pulseaudio-utils")

    output_file = sys.argv[1] if len(sys.argv) > 1 else "recording.mp4"

    cmd = build_command(output_file)
    print(f"\nStarting recording → {output_file}")
    print("Press 'q' then Enter to stop.\n")

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    try:
        while True:
            user_input = input()
            if user_input.strip().lower() == "q":
                proc.communicate(b"q")
                break
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()

    print(f"\nSaved to {output_file}")


if __name__ == "__main__":
    main()