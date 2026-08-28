"""Runtime configuration.

Deployment-specific things (paths, port, feature toggles) come from environment
variables. The tunable lists - which file extensions count as media, and the
per-episode cap - come from a YAML file: `config.default.yml` shipped alongside
this module, with your own file layered on top.

Your file is found via `SIZEARR_CONFIG`, or at `/config/config.yml` if that
exists. Values you provide replace the defaults key by key.
"""
import logging
import os

import yaml

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


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
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

# Whether the delete button / POST /api/delete are active. Set
# ENABLE_DELETE=false to make the app strictly read-only.
ENABLE_DELETE = env_flag("ENABLE_DELETE")

# ffprobe (part of ffmpeg) reads the true resolution / codecs / duration of a
# file for the detail popup when it is available. It is only ever run on a
# single file you click, never during the bulk scan.
ENABLE_FFPROBE = env_flag("ENABLE_FFPROBE")
FFPROBE_BIN = os.environ.get("FFPROBE", "ffprobe")

CONFIG_FILE = os.environ.get("SIZEARR_CONFIG")

# ---------------------------------------------------------------------------
# YAML config
# ---------------------------------------------------------------------------
# config.default.yml ships with the package (and in the Docker image) and is
# always the base. Your own file, if you point at one, is layered on top.
_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "config.default.yml")


def _user_config_path():
    if CONFIG_FILE:
        return CONFIG_FILE
    if os.path.isfile("/config/config.yml"):
        return "/config/config.yml"
    return None


def _merge(base, override):
    """One level of dict merge. A value you provide - including a list -
    replaces the default outright."""
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _read_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_config():
    # The default file is part of the install - a missing/broken one is a
    # packaging bug, so fail loudly rather than guessing.
    cfg = _read_yaml(_DEFAULT_CONFIG)

    path = _user_config_path()
    if not path:
        return cfg
    try:
        user = _read_yaml(path)
    except (OSError, yaml.YAMLError) as e:
        log.warning("could not load config %s (%s) - using defaults", path, e)
        return cfg
    if not isinstance(user, dict):
        log.warning("config %s is not a mapping - ignoring it", path)
        return cfg
    log.info("loaded config overrides from %s", path)
    return _merge(cfg, user)


def _ext_set(values):
    """Normalise a list of extensions to a set of lowercase, dot-prefixed strings."""
    out = set()
    for v in values or []:
        v = str(v).strip().lower()
        if v:
            out.add(v if v.startswith(".") else "." + v)
    return out


_CFG = _load_config()
_media = _CFG.get("media_extensions") or {}

# Video-only - used to decide whether it's worth running ffprobe.
VIDEO_EXTS = _ext_set(_media.get("video"))
# Everything the scan counts.
MEDIA_EXTS = VIDEO_EXTS | _ext_set(_media.get("audio")) | _ext_set(_media.get("subtitle"))

# A show with more files than this only lists its largest MAX_CHILDREN in the
# per-episode breakdown (the folder total still counts every file).
try:
    MAX_CHILDREN = int(_CFG.get("max_children") or 1000)
except (TypeError, ValueError):
    log.warning("max_children is not a number - using 1000")
    MAX_CHILDREN = 1000

log.info("counting %d media extensions (%d video)", len(MEDIA_EXTS), len(VIDEO_EXTS))
