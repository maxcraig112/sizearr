import os
import time
import threading
from flask import Flask, jsonify, render_template

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
}

REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "3600"))


def get_dir_size(path):
    """Recursively sum file sizes under path. Skips files/dirs it can't read."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                continue
    return total


def scan_media():
    items = []
    for category, root in MEDIA_ROOTS.items():
        if not os.path.isdir(root):
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for name in entries:
            full_path = os.path.join(root, name)
            if name.startswith('.'):
                continue
            try:
                if os.path.isdir(full_path):
                    size = get_dir_size(full_path)
                elif os.path.isfile(full_path):
                    size = os.path.getsize(full_path)
                else:
                    continue
            except OSError:
                continue
            items.append({
                "name": name,
                "category": category,
                "size_bytes": size,
            })
    return items


def refresh_cache():
    with _cache_lock:
        if _cache["scanning"]:
            return
        _cache["scanning"] = True
    try:
        items = scan_media()
        with _cache_lock:
            _cache["items"] = items
            _cache["last_scan"] = time.time()
            _cache["error"] = None
    except Exception as e:
        with _cache_lock:
            _cache["error"] = str(e)
    finally:
        with _cache_lock:
            _cache["scanning"] = False


def background_refresh_loop():
    while True:
        refresh_cache()
        time.sleep(REFRESH_INTERVAL_SECONDS)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/media")
def api_media():
    with _cache_lock:
        return jsonify({
            "items": _cache["items"],
            "last_scan": _cache["last_scan"],
            "scanning": _cache["scanning"],
            "error": _cache["error"],
        })


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    thread = threading.Thread(target=refresh_cache, daemon=True)
    thread.start()
    return jsonify({"started": True})


if __name__ == "__main__":
    # Kick off an initial scan in the background so the UI can load
    # immediately and poll until data is ready.
    threading.Thread(target=background_refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5432")))
