"""sizearr — see what a movie/TV library is doing to your disk, at a glance.

The app is split into small, single-purpose modules:

    config    environment / logging setup, all in one place
    fsutil    walking the media tree
    scanner   turning folders into the flat list of titles
    cache     the in-memory index of the last scan + refresh loop
    paths     validating an API request into a path inside a media root
    naming    quality tags parsed from release-style filenames
    ffprobe   optional real media metadata
    detail    the per-item detail payload
    web       the Flask app and its routes
"""
