"""Turning the media folders into the flat list of titles the table shows."""
import os

from .config import MAX_CHILDREN, MEDIA_ROOTS, log
from .fsutil import get_dir_size, iter_files


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


def scan_media(progress=None):
    """Walk every media root and return the list of title dicts. `progress` is
    called with a one-line status string as each root starts (optional)."""
    def _report(message):
        if progress:
            progress(message)

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
        _report("Scanning %s (%s): %d entries" % (category, root, len(visible)))

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
