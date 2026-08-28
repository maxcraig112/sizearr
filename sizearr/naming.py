"""Best-effort quality/source/codec hints parsed from release-style filenames.
Whatever isn't in the name simply isn't reported.

(The media extension list lives in config.py, driven by YAML.)"""
import os
import re

# Tokens commonly baked into filenames by Radarr / Sonarr / scene groups.
_TOKEN_RES = re.compile(r"(?<![a-z0-9])(2160p|1080p|720p|576p|480p)(?![a-z0-9])", re.I)
_TOKEN_4K = re.compile(r"(?<![a-z0-9])(4k|uhd)(?![a-z0-9])", re.I)
_TOKEN_SOURCE = re.compile(
    r"(?<![a-z0-9])(bluray|blu-ray|bdremux|remux|web-?dl|web-?rip|webhd|hdtv|"
    r"dvdrip|dvd|hdrip|brrip|bdrip|hdcam|cam)(?![a-z0-9])", re.I)
_TOKEN_VCODEC = re.compile(
    r"(?<![a-z0-9])(x265|h\.?265|hevc|x264|h\.?264|avc|av1|xvid|divx|mpeg-?2)(?![a-z0-9])", re.I)
_TOKEN_HDR = re.compile(
    r"(?<![a-z0-9])(dolby[ .]?vision|dovi|hdr10\+|hdr10|hdr|sdr)(?![a-z0-9])", re.I)
_TOKEN_AUDIO = re.compile(
    r"(?<![a-z0-9])(atmos|truehd|dts-?hd(?:[ .]?ma)?|dts-?x|dts|e-?ac-?3|eac3|"
    r"dd\+?p?[ .]?5\.1|ddp|dd5\.1|ac-?3|aac|flac|opus)(?![a-z0-9])", re.I)
_TOKEN_EDITION = re.compile(
    r"(?<![a-z0-9])(extended|director'?s[ .]?cut|uncut|unrated|remastered|imax|"
    r"theatrical|special[ .]?edition|final[ .]?cut)(?![a-z0-9])", re.I)
_TOKEN_EPISODE = re.compile(r"(?<![a-z0-9])s(\d{1,2})[. _]?e(\d{1,3})(?![a-z0-9])", re.I)
_TOKEN_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_TOKEN_GROUP = re.compile(r"-([A-Za-z0-9]{2,})$")
_NOT_A_GROUP = {
    "1080p", "720p", "2160p", "480p", "576p", "x264", "x265", "hevc", "web",
}


def parse_name_tags(filename):
    """Pull quality/source/codec hints out of a release-style filename."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    tags = {}

    m = _TOKEN_RES.search(stem)
    if m:
        tags["resolution"] = m.group(1).lower()
    elif _TOKEN_4K.search(stem):
        tags["resolution"] = "2160p"

    for key, rx in (
        ("source", _TOKEN_SOURCE),
        ("video_codec", _TOKEN_VCODEC),
        ("dynamic_range", _TOKEN_HDR),
        ("audio", _TOKEN_AUDIO),
        ("edition", _TOKEN_EDITION),
    ):
        m = rx.search(stem)
        if m:
            tags[key] = m.group(1)

    m = _TOKEN_EPISODE.search(stem)
    if m:
        tags["episode"] = "S%02dE%02d" % (int(m.group(1)), int(m.group(2)))

    years = _TOKEN_YEAR.findall(stem)
    if years:
        tags["year"] = years[0]

    m = _TOKEN_GROUP.search(stem)
    if m and m.group(1).lower() not in _NOT_A_GROUP:
        tags["release_group"] = m.group(1)

    return tags
