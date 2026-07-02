"""Small media helpers for the authoring flow."""
from __future__ import annotations

import os
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


def faststart_inplace(local_path: str) -> None:
    """Move the MP4 moov atom to the front so browsers can start playback
    before the whole file downloads (progressive streaming). Stream-copies —
    no re-encode. Best-effort: on any failure the original file is kept as-is.
    """
    tmp = local_path + ".fs.mp4"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", local_path,
             "-c", "copy", "-movflags", "+faststart", tmp],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, local_path)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
