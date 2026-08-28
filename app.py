import logging
import os
import time
import threading
from flask import Flask, jsonify, render_template, url_for

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Everything the scanner does is logged to stdout so `docker logs -f
# media-size-browser` (or the console when run directly) tells you exactly
# what's happening. Set LOG_LEVEL=DEBUG to also see a line per title with
# its measured size.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("media-size-browser")

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

    return {"static_url": static_url}


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
        })


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    log.info("Manual rescan requested")
    thread = threading.Thread(target=refresh_cache, daemon=True)
    thread.start()
    return jsonify({"started": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5432"))
    log.info("Media Size Browser starting on port %d (log level %s)", port, LOG_LEVEL)
    for category, root in MEDIA_ROOTS.items():
        exists = os.path.isdir(root)
        log.info("  %-6s -> %s %s", category, root, "" if exists else "(MISSING)")
    # Kick off an initial scan in the background so the UI can load
    # immediately and poll until data is ready.
    threading.Thread(target=background_refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=port)
