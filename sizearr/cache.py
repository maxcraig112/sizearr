"""The in-memory index of the most recent scan, and the refresh machinery."""
import threading
import time

from .config import MEDIA_ROOTS, REFRESH_INTERVAL_SECONDS, log
from .scanner import scan_media


class MediaCache:
    """Holds the most recent scan result. Thread-safe; one instance per app."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "items": [],
            "last_scan": None,
            "scanning": False,
            "error": None,
            "progress": None,        # human-readable "what is it doing right now"
            "scan_started_at": None,
        }

    def snapshot(self):
        """A copy of the current state, for the /api/media response."""
        with self._lock:
            return dict(self._state)

    def set_progress(self, message):
        """Record a one-line status the UI and logs show while scanning."""
        with self._lock:
            self._state["progress"] = message
        log.info(message)

    def refresh(self):
        """Run one scan and store the result. No-op if a scan is already going."""
        with self._lock:
            if self._state["scanning"]:
                log.info("Scan already in progress - ignoring refresh request")
                return
            self._state["scanning"] = True
            self._state["scan_started_at"] = time.time()
            self._state["progress"] = "Starting scan"

        started = time.time()
        log.info("Scan started (roots: %s)", MEDIA_ROOTS)
        try:
            items = scan_media(progress=self.set_progress)
            elapsed = time.time() - started
            total_bytes = sum(i["size_bytes"] for i in items)
            with self._lock:
                self._state["items"] = items
                self._state["last_scan"] = time.time()
                self._state["error"] = None
                self._state["progress"] = None
            log.info(
                "Scan complete: %d titles, %.1f GiB total, %.1fs",
                len(items), total_bytes / 1024 ** 3, elapsed,
            )
        except Exception as e:
            log.exception("Scan failed")
            with self._lock:
                self._state["error"] = "%s: %s" % (type(e).__name__, e)
                self._state["progress"] = None
        finally:
            with self._lock:
                self._state["scanning"] = False

    def run_forever(self):
        """Background loop: refresh, wait REFRESH_INTERVAL_SECONDS, repeat."""
        while True:
            self.refresh()
            log.info("Next automatic scan in %d seconds", REFRESH_INTERVAL_SECONDS)
            time.sleep(REFRESH_INTERVAL_SECONDS)

    def apply_deletion(self, category, name, child):
        """Reflect a delete in the cache immediately, so the next snapshot is
        right without waiting for the follow-up rescan."""
        with self._lock:
            items = self._state["items"]
            if child is None:
                self._state["items"] = [
                    it for it in items
                    if not (it["category"] == category and it["name"] == name)
                ]
                return
            prefix = child.rstrip("/") + "/"  # deleting "Season 01" also drops its episodes
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


# The single instance the whole app shares.
cache = MediaCache()
