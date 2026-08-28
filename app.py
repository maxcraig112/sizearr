import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import time
import threading
from flask import Flask, jsonify, render_template, request, url_for

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Everything the scanner does is logged to stdout so `docker logs -f
# sizearr` (or the console when run directly) tells you exactly what's
# happening. Set LOG_LEVEL=DEBUG to also see a line per title with its
# measured size.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("sizearr")

# Baked in at image build time from the release tag (see Dockerfile /
# .github/workflows/release.yml). "dev" when run from a plain checkout.
VERSION = os.environ.get("SIZEARR_VERSION", "dev")

app = Flask(__name__)

# Root media directories to scan. Each top-level folder inside these
# is treated as one "title" (a movie folder, or a TV show folder).
#
# The paths are configurable via environment variables so you can point
# the app at wherever your library actually lives (or mount a single
# media root and set these to the subfolders inside it):
#
#   MOVIES_PATH  - default /media/movies
#   TV_PATH      - default /media/tv
MEDIA_ROOTS = {
    "movies": os.environ.get("MOVIES_PATH", "/media/movies"),
    "tv": os.environ.get("TV_PATH", "/media/tv"),
}

def _env_flag(name, default="true"):
    return os.environ.get(name, default).strip().lower() not in (
        "0", "false", "no", "off",
    )


# Whether the delete button / POST /api/delete are active. Set
# ENABLE_DELETE=false to make the app strictly read-only.
ENABLE_DELETE = _env_flag("ENABLE_DELETE")

# ffprobe (part of ffmpeg) is used, when available, to read the true
# resolution / codecs / duration of a file in the detail popup. It is only
# ever run on a single file you click, never during the bulk scan. Falls
# back to what can be parsed from the filename when ffprobe is absent.
FFPROBE_BIN = os.environ.get("FFPROBE", "ffprobe")
_ffprobe_checked = None

# In-memory cache of scan results, refreshed on a timer and on-demand.
_cache_lock = threading.Lock()
_cache = {
    "items": [],
    "last_scan": None,
    "scanning": False,
    "error": None,
    "progress": None,        # human-readable "what is it doing right now"
    "scan_started_at": None,
}

REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "3600"))


def _set_progress(message):
    """Record a one-line status the UI and logs can show while scanning."""
    with _cache_lock:
        _cache["progress"] = message
    log.info(message)


def iter_files(path):
    """Yield (relative_path, size_bytes) for every regular file under path.
    Logs and skips anything it can't read. Relative paths use '/' separators."""

    def _on_error(err):
        log.warning("  cannot read %s: %s", getattr(err, "filename", path), err)

    for dirpath, _dirnames, filenames in os.walk(path, onerror=_on_error):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                if os.path.islink(fp):
                    continue
                size = os.path.getsize(fp)
            except OSError as e:
                log.warning("  skipping %s: %s", fp, e)
                continue
            rel = os.path.relpath(fp, path).replace(os.sep, "/")
            yield rel, size


def get_dir_size(path):
    """Recursively sum file sizes under path. Logs anything it can't read."""
    return sum(size for _, size in iter_files(path))


# A show with more files than this only lists its largest MAX_CHILDREN in the
# per-episode breakdown (the folder total still counts every file).
MAX_CHILDREN = 1000


def tv_show_breakdown(path):
    """Return (total_bytes, children) for a TV show folder, where children is a
    size-descending list of {"name": <relative path>, "size_bytes": int}."""
    files = list(iter_files(path))
    total = sum(size for _, size in files)
    files.sort(key=lambda item: item[1], reverse=True)
    children = [
        {"name": rel, "size_bytes": size}
        for rel, size in files[:MAX_CHILDREN]
    ]
    return total, children


def scan_media():
    items = []
    for category, root in MEDIA_ROOTS.items():
        if not os.path.isdir(root):
            log.warning(
                "%s root %r does not exist or is not a directory - skipping",
                category, root,
            )
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError as e:
            log.error("cannot list %s root %r: %s", category, root, e)
            continue

        visible = [n for n in entries if not n.startswith(".")]
        _set_progress(
            "Scanning %s (%s): %d entries" % (category, root, len(visible))
        )

        for idx, name in enumerate(visible, start=1):
            full_path = os.path.join(root, name)
            children = []
            try:
                if os.path.isdir(full_path):
                    if category == "tv":
                        size, children = tv_show_breakdown(full_path)
                    else:
                        size = get_dir_size(full_path)
                elif os.path.isfile(full_path):
                    size = os.path.getsize(full_path)
                else:
                    log.debug("  %s: not a file or dir, skipping", name)
                    continue
            except OSError as e:
                log.warning("  %s: %s", name, e)
                continue
            log.debug(
                "  [%d/%d] %s = %d bytes (%d files)",
                idx, len(visible), name, size, len(children),
            )
            item = {
                "name": name,
                "category": category,
                "size_bytes": size,
            }
            if children:
                item["children"] = children
            items.append(item)

        log.info("Finished %s: %d titles", category, len(visible))
    return items


def refresh_cache():
    with _cache_lock:
        if _cache["scanning"]:
            log.info("Scan already in progress - ignoring refresh request")
            return
        _cache["scanning"] = True
        _cache["scan_started_at"] = time.time()
        _cache["progress"] = "Starting scan"

    started = time.time()
    log.info("Scan started (roots: %s)", MEDIA_ROOTS)
    try:
        items = scan_media()
        elapsed = time.time() - started
        total_bytes = sum(i["size_bytes"] for i in items)
        with _cache_lock:
            _cache["items"] = items
            _cache["last_scan"] = time.time()
            _cache["error"] = None
            _cache["progress"] = None
        log.info(
            "Scan complete: %d titles, %.1f GiB total, %.1fs",
            len(items), total_bytes / 1024 ** 3, elapsed,
        )
    except Exception as e:
        log.exception("Scan failed")
        with _cache_lock:
            _cache["error"] = "%s: %s" % (type(e).__name__, e)
            _cache["progress"] = None
    finally:
        with _cache_lock:
            _cache["scanning"] = False


def background_refresh_loop():
    while True:
        refresh_cache()
        log.info("Next automatic scan in %d seconds", REFRESH_INTERVAL_SECONDS)
        time.sleep(REFRESH_INTERVAL_SECONDS)


@app.context_processor
def inject_static_url():
    """Provide static_url() to templates: appends the file's mtime as ?v= so
    browsers pick up CSS/JS changes immediately after a deploy instead of
    serving a stale cached copy."""
    def static_url(filename):
        version = 0
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            pass
        return url_for("static", filename=filename, v=version)

    return {"static_url": static_url, "version": VERSION}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/media", methods=["GET"])
def api_media():
    with _cache_lock:
        return jsonify({
            "items": _cache["items"],
            "last_scan": _cache["last_scan"],
            "scanning": _cache["scanning"],
            "error": _cache["error"],
            "progress": _cache["progress"],
            "scan_started_at": _cache["scan_started_at"],
            "can_delete": ENABLE_DELETE,
        })


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    log.info("Manual rescan requested")
    thread = threading.Thread(target=refresh_cache, daemon=True)
    thread.start()
    return jsonify({"started": True})


def resolve_media_target(category, name, child):
    """Turn a (category, title, optional file) request into an absolute,
    validated path that is provably inside the configured media root. Used by
    both the delete and detail endpoints. Raises ValueError for anything
    suspect, FileNotFoundError if the path does not exist."""
    root = MEDIA_ROOTS.get(category)
    if root is None:
        raise ValueError("unknown category")

    if (not isinstance(name, str) or not name or name.startswith(".")
            or "/" in name or "\\" in name or name in (".", "..")):
        raise ValueError("invalid title name")

    root_real = os.path.realpath(root)
    target = os.path.join(root_real, name)

    if child is not None:
        if category != "tv":
            raise ValueError("per-file access is only supported for TV shows")
        if not isinstance(child, str) or not child:
            raise ValueError("invalid file path")
        parts = [p for p in child.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or ".." in parts:
            raise ValueError("invalid file path")
        target = os.path.join(target, *parts)

    target_real = os.path.realpath(target)
    try:
        inside = os.path.commonpath([root_real, target_real]) == root_real
    except ValueError:
        inside = False  # e.g. different drive on Windows
    if not inside or target_real == root_real:
        raise ValueError("path escapes the media root")
    if not os.path.lexists(target_real):
        raise FileNotFoundError(target_real)
    return target_real


def _apply_deletion_to_cache(category, name, child):
    """Reflect a delete in the cached results immediately, so the next
    /api/media call is correct without waiting for the follow-up rescan."""
    with _cache_lock:
        items = _cache["items"]
        if child is None:
            _cache["items"] = [
                it for it in items
                if not (it["category"] == category and it["name"] == name)
            ]
            return
        prefix = child.rstrip("/") + "/"  # so deleting "Season 01" also drops its episodes
        for it in items:
            if it["category"] == category and it["name"] == name:
                kids = it.get("children") or []

                def _hit(rel):
                    return rel == child or rel.startswith(prefix)

                freed = sum(k["size_bytes"] for k in kids if _hit(k["name"]))
                remaining = [k for k in kids if not _hit(k["name"])]
                it["size_bytes"] = max(0, it["size_bytes"] - freed)
                if remaining:
                    it["children"] = remaining
                else:
                    it.pop("children", None)
                break


@app.route("/api/delete", methods=["POST"])
def api_delete():
    if not ENABLE_DELETE:
        return jsonify({"error": "Deletion is disabled on this server"}), 403

    body = request.get_json(silent=True) or {}
    category = body.get("category")
    name = body.get("name")
    child = body.get("child")

    try:
        target = resolve_media_target(category, name, child)
    except FileNotFoundError:
        return jsonify({"error": "Not found - it may already be deleted"}), 404
    except ValueError as e:
        log.warning(
            "Delete rejected (%s): category=%r name=%r child=%r", e, category, name, child
        )
        return jsonify({"error": "Invalid request: %s" % e}), 400

    try:
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except OSError as e:
        log.exception("Delete failed for %s", target)
        return jsonify({"error": str(e)}), 500

    log.info("Deleted %s", target)
    _apply_deletion_to_cache(category, name, child)
    threading.Thread(target=refresh_cache, daemon=True).start()
    return jsonify({"deleted": True})


# ---------------------------------------------------------------------------
# Per-item detail (shown when you click a movie or an episode)
# ---------------------------------------------------------------------------

VIDEO_EXTS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".webm", ".flv", ".divx",
}

# Tokens commonly baked into release filenames by Radarr / Sonarr / scene
# groups. Best-effort: whatever isn't in the name simply isn't reported.
_NAME_TOKEN_RES = re.compile(r"(?<![a-z0-9])(2160p|1080p|720p|576p|480p)(?![a-z0-9])", re.I)
_NAME_TOKEN_4K = re.compile(r"(?<![a-z0-9])(4k|uhd)(?![a-z0-9])", re.I)
_NAME_TOKEN_SOURCE = re.compile(
    r"(?<![a-z0-9])(bluray|blu-ray|bdremux|remux|web-?dl|web-?rip|webhd|hdtv|"
    r"dvdrip|dvd|hdrip|brrip|bdrip|hdcam|cam)(?![a-z0-9])", re.I)
_NAME_TOKEN_VCODEC = re.compile(
    r"(?<![a-z0-9])(x265|h\.?265|hevc|x264|h\.?264|avc|av1|xvid|divx|mpeg-?2)(?![a-z0-9])", re.I)
_NAME_TOKEN_HDR = re.compile(
    r"(?<![a-z0-9])(dolby[ .]?vision|dovi|hdr10\+|hdr10|hdr|sdr)(?![a-z0-9])", re.I)
_NAME_TOKEN_AUDIO = re.compile(
    r"(?<![a-z0-9])(atmos|truehd|dts-?hd(?:[ .]?ma)?|dts-?x|dts|e-?ac-?3|eac3|"
    r"dd\+?p?[ .]?5\.1|ddp|dd5\.1|ac-?3|aac|flac|opus)(?![a-z0-9])", re.I)
_NAME_TOKEN_EDITION = re.compile(
    r"(?<![a-z0-9])(extended|director'?s[ .]?cut|uncut|unrated|remastered|imax|"
    r"theatrical|special[ .]?edition|final[ .]?cut)(?![a-z0-9])", re.I)
_NAME_TOKEN_EPISODE = re.compile(r"(?<![a-z0-9])s(\d{1,2})[. _]?e(\d{1,3})(?![a-z0-9])", re.I)
_NAME_TOKEN_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_NAME_TOKEN_GROUP = re.compile(r"-([A-Za-z0-9]{2,})$")
_NOT_A_GROUP = {
    "1080p", "720p", "2160p", "480p", "576p", "x264", "x265", "hevc", "web",
}


def parse_name_tags(filename):
    """Pull quality/source/codec hints out of a release-style filename."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    tags = {}

    m = _NAME_TOKEN_RES.search(stem)
    if m:
        tags["resolution"] = m.group(1).lower()
    elif _NAME_TOKEN_4K.search(stem):
        tags["resolution"] = "2160p"

    for key, rx in (
        ("source", _NAME_TOKEN_SOURCE),
        ("video_codec", _NAME_TOKEN_VCODEC),
        ("dynamic_range", _NAME_TOKEN_HDR),
        ("audio", _NAME_TOKEN_AUDIO),
        ("edition", _NAME_TOKEN_EDITION),
    ):
        m = rx.search(stem)
        if m:
            tags[key] = m.group(1)

    m = _NAME_TOKEN_EPISODE.search(stem)
    if m:
        tags["episode"] = "S%02dE%02d" % (int(m.group(1)), int(m.group(2)))

    years = _NAME_TOKEN_YEAR.findall(stem)
    if years:
        tags["year"] = years[0]

    m = _NAME_TOKEN_GROUP.search(stem)
    if m and m.group(1).lower() not in _NOT_A_GROUP:
        tags["release_group"] = m.group(1)

    return tags


def ffprobe_available():
    global _ffprobe_checked
    if _ffprobe_checked is None:
        if not _env_flag("ENABLE_FFPROBE"):
            _ffprobe_checked = False
        else:
            _ffprobe_checked = shutil.which(FFPROBE_BIN) is not None
        log.info("ffprobe %s", "available" if _ffprobe_checked else "not available")
    return _ffprobe_checked


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


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def file_detail(abs_path, display_name):
    st = os.stat(abs_path)
    ext = os.path.splitext(abs_path)[1].lower()
    detail = {
        "kind": "file",
        "name": os.path.basename(display_name),
        "path": abs_path,
        "size_bytes": st.st_size,
        "modified": _iso(st.st_mtime),
        "container": ext.lstrip(".") or None,
        "name_tags": parse_name_tags(abs_path),
    }
    birth = getattr(st, "st_birthtime", None)
    if birth:
        detail["created"] = _iso(birth)
    if ext in VIDEO_EXTS and ffprobe_available():
        media = run_ffprobe(abs_path)
        if media:
            detail["media"] = media
    return detail


def folder_detail(abs_path, display_name):
    entries = list(iter_files(abs_path))
    total = sum(size for _, size in entries)
    exts = {}
    newest = oldest = None
    largest = None
    for rel, size in entries:
        key = os.path.splitext(rel)[1].lower() or "(no extension)"
        exts[key] = exts.get(key, 0) + 1
        try:
            mtime = os.path.getmtime(os.path.join(abs_path, rel))
            newest = mtime if newest is None else max(newest, mtime)
            oldest = mtime if oldest is None else min(oldest, mtime)
        except OSError:
            pass
        if largest is None or size > largest[1]:
            largest = (rel, size)

    detail = {
        "kind": "folder",
        "name": display_name,
        "path": abs_path,
        "size_bytes": total,
        "file_count": len(entries),
        "extensions": [
            {"ext": k, "count": v}
            for k, v in sorted(exts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
    if newest:
        detail["modified"] = _iso(newest)
    if oldest and oldest != newest:
        detail["oldest_file"] = _iso(oldest)
    if largest:
        detail["primary_file"] = largest[0]
        detail["name_tags"] = parse_name_tags(largest[0])
        primary = os.path.join(abs_path, largest[0])
        if os.path.splitext(primary)[1].lower() in VIDEO_EXTS and ffprobe_available():
            media = run_ffprobe(primary)
            if media:
                detail["media"] = media
    return detail


@app.route("/api/detail", methods=["GET"])
def api_detail():
    category = request.args.get("category")
    name = request.args.get("name")
    child = request.args.get("child") or None

    try:
        target = resolve_media_target(category, name, child)
    except FileNotFoundError:
        return jsonify({"error": "Not found"}), 404
    except ValueError as e:
        return jsonify({"error": "Invalid request: %s" % e}), 400

    try:
        if os.path.isdir(target):
            return jsonify(folder_detail(target, name))
        return jsonify(file_detail(target, child or name))
    except OSError as e:
        log.exception("Detail failed for %s", target)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5432"))
    log.info(
        "sizearr %s starting on port %d (log level %s, delete %s)",
        VERSION, port, LOG_LEVEL, "enabled" if ENABLE_DELETE else "disabled",
    )
    for category, root in MEDIA_ROOTS.items():
        exists = os.path.isdir(root)
        log.info("  %-6s -> %s %s", category, root, "" if exists else "(MISSING)")
    ffprobe_available()  # log whether detail popups can read real media metadata
    # Kick off an initial scan in the background so the UI can load
    # immediately and poll until data is ready.
    threading.Thread(target=background_refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=port)
