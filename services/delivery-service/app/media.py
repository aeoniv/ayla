"""Small media helpers for the authoring flow."""
from __future__ import annotations

import subprocess


def video_duration_seconds(local_path: str) -> float:
    """Return a video's duration in seconds using ffprobe.

    Raises ValueError if the duration can't be determined (e.g. not a video).
    """
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                local_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"ffprobe failed: {e}")
    raw = out.stdout.strip()
    if not raw:
        raise ValueError(f"could not read video duration: {out.stderr.strip()}")
    return float(raw)
