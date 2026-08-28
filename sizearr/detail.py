"""The per-item detail payload shown when you click a movie or an episode."""
import datetime
import os

from .config import VIDEO_EXTS
from .ffprobe import ffprobe_available, run_ffprobe
from .fsutil import iter_files
from .naming import parse_name_tags


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def file_detail(abs_path, display_name):
    """Detail dict for a single file (a movie file, or one episode)."""
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
    """Detail dict for a folder (a movie folder, or a whole TV show)."""
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
