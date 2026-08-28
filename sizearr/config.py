"""Runtime configuration. Everything the app reads from the environment lives
here so there is one place to look."""
import logging
import os

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Every scan step goes to stdout so `docker logs -f sizearr` (or the console
# when run directly) tells you exactly what is happening. LOG_LEVEL=DEBUG also
# logs a line per title with its measured size.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("sizearr")


def env_flag(name, default="true"):
    """Read a boolean-ish env var. Anything but 0/false/no/off counts as true."""
    return os.environ.get(name, default).strip().lower() not in (
        "0", "false", "no", "off",
    )


# Baked in at image build time from the release tag (see Dockerfile /
# .github/workflows/release.yml). "dev" when run from a plain checkout.
VERSION = os.environ.get("SIZEARR_VERSION", "dev")

PORT = int(os.environ.get("PORT", "5432"))

# Root media directories to scan. Each top-level folder inside these is one
# "title" (a movie folder, or a TV show folder). Point these wherever your
# library lives, or mount a single media root and set them to the subfolders
# inside it.
MEDIA_ROOTS = {
    "movies": os.environ.get("MOVIES_PATH", "/media/movies"),
    "tv": os.environ.get("TV_PATH", "/media/tv"),
}

# How often the background rescan runs, in seconds.
REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "3600"))

# A show with more files than this only lists its largest MAX_CHILDREN in the
# per-episode breakdown (the folder total still counts every file).
MAX_CHILDREN = 1000

# Whether the delete button / POST /api/delete are active. Set
# ENABLE_DELETE=false to make the app strictly read-only.
ENABLE_DELETE = env_flag("ENABLE_DELETE")

# ffprobe (part of ffmpeg) reads the true resolution / codecs / duration of a
# file for the detail popup when it is available. It is only ever run on a
# single file you click, never during the bulk scan.
ENABLE_FFPROBE = env_flag("ENABLE_FFPROBE")
FFPROBE_BIN = os.environ.get("FFPROBE", "ffprobe")
