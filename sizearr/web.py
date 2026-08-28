"""The Flask app: routes, template wiring, and the startup sequence."""
import os
import shutil
import threading

from flask import Flask, jsonify, render_template, request, url_for

from .cache import cache
from .config import ENABLE_DELETE, LOG_LEVEL, MEDIA_ROOTS, PORT, VERSION, log
from .detail import file_detail, folder_detail
from .ffprobe import ffprobe_available
from .paths import resolve_media_target

# templates/ and static/ live at the repo root, next to this package.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

app = Flask(
    "sizearr",
    template_folder=os.path.join(_ROOT, "templates"),
    static_folder=os.path.join(_ROOT, "static"),
)


@app.context_processor
def inject_globals():
    """static_url() appends the file's mtime as ?v= so browsers pick up CSS/JS
    changes right after a deploy instead of serving a stale copy. `version` is
    the release tag shown in the header."""
    def static_url(filename):
        stamp = 0
        try:
            stamp = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            pass
        return url_for("static", filename=filename, v=stamp)

    return {"static_url": static_url, "version": VERSION}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/media", methods=["GET"])
def api_media():
    state = cache.snapshot()
    return jsonify({
        "items": state["items"],
        "last_scan": state["last_scan"],
        "scanning": state["scanning"],
        "error": state["error"],
        "progress": state["progress"],
        "scan_started_at": state["scan_started_at"],
        "can_delete": ENABLE_DELETE,
    })


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    log.info("Manual rescan requested")
    threading.Thread(target=cache.refresh, daemon=True).start()
    return jsonify({"started": True})


def _delete_and_rescan(target):
    """Do the (possibly slow) filesystem delete off the request thread. A
    failure is logged and undone by the follow-up rescan, which re-adds the
    title the optimistic cache update removed."""
    try:
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        log.info("Deleted %s", target)
    except OSError:
        log.exception("Delete failed for %s", target)
    cache.refresh()


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

    # Update the cache now so the UI reacts immediately, then delete on disk in
    # the background - a big folder can take a while and the client shouldn't
    # wait on it.
    cache.apply_deletion(category, name, child)
    threading.Thread(target=_delete_and_rescan, args=(target,), daemon=True).start()
    return jsonify({"accepted": True}), 202


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


def run():
    """Log the startup banner, kick off the background scanner, then serve."""
    log.info(
        "sizearr %s starting on port %d (log level %s, delete %s)",
        VERSION, PORT, LOG_LEVEL, "enabled" if ENABLE_DELETE else "disabled",
    )
    for category, root in MEDIA_ROOTS.items():
        exists = os.path.isdir(root)
        log.info("  %-6s -> %s %s", category, root, "" if exists else "(MISSING)")
    ffprobe_available()  # log whether detail popups can read real media metadata
    # Kick off an initial scan in the background so the UI can load immediately
    # and poll until data is ready.
    threading.Thread(target=cache.run_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
