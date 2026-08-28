"""Turning an API request into a validated absolute path inside a media root.
Every delete and every detail lookup goes through here first."""
import os

from .config import MEDIA_ROOTS


def resolve_media_target(category, name, child):
    """Turn a (category, title, optional file) request into an absolute path
    that is provably inside the configured media root. Raises ValueError for
    anything suspect, FileNotFoundError if the path does not exist."""
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
