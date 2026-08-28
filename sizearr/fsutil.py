"""Walking the media tree. The one place that does bulk filesystem reads."""
import os

from .config import log
from .naming import NON_MEDIA_EXTS


def iter_files(path):
    """Yield (relative_path, size_bytes) for every media file under path.
    Artwork, .nfo and other non-media files are skipped, along with anything
    that can't be read. Relative paths use '/' separators."""

    def _on_error(err):
        log.warning("  cannot read %s: %s", getattr(err, "filename", path), err)

    for dirpath, _dirnames, filenames in os.walk(path, onerror=_on_error):
        for f in filenames:
            if os.path.splitext(f)[1].lower() in NON_MEDIA_EXTS:
                continue
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
    """Recursively sum file sizes under path."""
    return sum(size for _, size in iter_files(path))
