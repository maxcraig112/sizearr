"""Optional real-media metadata via `ffprobe`, run lazily on one file at a time."""
import json
import shutil
import subprocess

from .config import ENABLE_FFPROBE, FFPROBE_BIN, log

_available = None  # cached result of the PATH check


def ffprobe_available():
    """True if ffprobe is enabled and on PATH. Checked once, then cached."""
    global _available
    if _available is None:
        _available = ENABLE_FFPROBE and shutil.which(FFPROBE_BIN) is not None
        log.info("ffprobe %s", "available" if _available else "not available")
    return _available


def run_ffprobe(path):
    """Return a trimmed dict of real media properties, or None on any failure."""
    try:
        proc = subprocess.run(
            [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        log.warning("ffprobe failed for %s", path, exc_info=True)
        return None

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    out = {}
    try:
        if fmt.get("duration"):
            out["duration_seconds"] = int(float(fmt["duration"]))
    except ValueError:
        pass
    try:
        if fmt.get("bit_rate"):
            out["bitrate"] = int(fmt["bit_rate"])
    except ValueError:
        pass

    if video:
        if video.get("width") and video.get("height"):
            out["resolution"] = "%sx%s" % (video["width"], video["height"])
        out["video_codec"] = video.get("codec_name")
        if video.get("color_transfer") in ("smpte2084", "arib-std-b67"):
            out["hdr"] = video["color_transfer"]

    out["audio"] = [
        {
            "codec": a.get("codec_name"),
            "channels": a.get("channels"),
            "language": (a.get("tags") or {}).get("language"),
            "title": (a.get("tags") or {}).get("title"),
        }
        for a in audios
    ]
    out["subtitles"] = [
        (s.get("tags") or {}).get("language") or s.get("codec_name")
        for s in subs
    ]
    return out
