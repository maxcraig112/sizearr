# Test data

Fake library used to run the app locally without pointing it at a real NAS.

Every `.mkv` / `.srt` here is an **empty placeholder** (all-zero bytes) with a
deliberately chosen size, so the scanner has something to measure and the
table has rows to sort and filter. Nothing here is real media.

```
make run-local        # scans testdata/movies and testdata/tv, serves on :5432
# equivalent to:
MOVIES_PATH=testdata/movies TV_PATH=testdata/tv make run
```

Add or resize files freely; `make run-local` (or the "Rescan now" button)
picks up changes.

Because these files have no real content, the detail popup's `ffprobe`
section stays empty for them — drop a real video in to see it populated.
