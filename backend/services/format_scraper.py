"""
format_scraper.py
-----------------
Fetches the Wikipedia "List of file formats" page and merges any newly
discovered extensions into the local formats.json data file.

Run manually:
    python -m services.format_scraper

Or call `refresh_formats()` programmatically (used by the startup hook in
app.py so the catalogue is kept fresh without manual intervention).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent.parent / "data" / "formats.json"
WIKIPEDIA_API = (
    "https://en.wikipedia.org/w/api.php"
    "?action=parse&page=List_of_file_formats&prop=wikitext&format=json"
)
# Wikipedia section → formats.json category id
_SECTION_MAP: dict[str, str] = {
    "audio": "audio",
    "video": "video",
    "image": "image",
    "raster": "image",
    "vector": "image",
    "animation": "video",
    "document": "document",
    "text": "document",
    "spreadsheet": "document",
    "presentation": "document",
    "database": "data",
    "data": "data",
    "archive": "archive",
    "compressed": "archive",
    "executable": "archive",
    "web": "web",
    "internet": "web",
    "3d": "cad",
    "cad": "cad",
    "font": "font",
    "code": "code",
    "source": "code",
    "script": "code",
    "programming": "code",
}

_EXT_RE = re.compile(r"\{\{ext\|([^}|]+)", re.IGNORECASE)
_HEADING_RE = re.compile(r"==+\s*(.+?)\s*==+")


def _fetch_wikitext() -> str:
    import urllib.request
    with urllib.request.urlopen(WIKIPEDIA_API, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data["parse"]["wikitext"]["*"]


def _parse_extensions(wikitext: str) -> dict[str, set[str]]:
    """
    Walk the wikitext line-by-line, track the current section heading, and
    collect all {{ext|…}} template occurrences into category buckets.
    """
    buckets: dict[str, set[str]] = {cat: set() for cat in set(_SECTION_MAP.values())}
    current_cat = "code"  # default for anything before first heading

    for line in wikitext.splitlines():
        heading_match = _HEADING_RE.search(line)
        if heading_match:
            heading = heading_match.group(1).lower()
            for keyword, cat in _SECTION_MAP.items():
                if keyword in heading:
                    current_cat = cat
                    break

        for ext_match in _EXT_RE.finditer(line):
            raw = ext_match.group(1).strip().lower().lstrip(".")
            # Skip multi-char entries that look like descriptions
            if raw and 1 <= len(raw) <= 10 and " " not in raw:
                buckets[current_cat].add(raw)

    return buckets


def refresh_formats(force: bool = False) -> bool:
    """
    Download the Wikipedia list and merge new extensions into formats.json.
    Returns True if the file was updated, False if nothing changed or the
    download failed.

    The function is intentionally non-destructive: it only *adds* extensions
    it has never seen before; it never removes anything from the existing file.
    """
    # Rate-limit: don't hammer Wikipedia more than once per hour unless forced
    stale_marker = DATA_PATH.with_suffix(".fetch_ts")
    if not force and stale_marker.exists():
        last = float(stale_marker.read_text().strip() or "0")
        if time.time() - last < 3600:
            logger.debug("formats.json is fresh, skipping Wikipedia fetch")
            return False

    try:
        logger.info("Fetching Wikipedia 'List of file formats'…")
        wikitext = _fetch_wikitext()
        wiki_buckets = _parse_extensions(wikitext)
    except Exception as exc:
        logger.warning("Wikipedia fetch failed (%s) — using cached formats.json", exc)
        return False

    with open(DATA_PATH, encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    changed = False
    for cat_id, new_exts in wiki_buckets.items():
        if cat_id not in data["categories"]:
            continue
        existing: list[str] = data["categories"][cat_id]["extensions"]
        existing_set = set(existing)
        additions = sorted(e for e in new_exts if e not in existing_set)
        if additions:
            data["categories"][cat_id]["extensions"] = sorted(existing_set | set(additions))
            logger.info("  [%s] +%d extensions: %s", cat_id, len(additions), additions[:8])
            changed = True

    if changed:
        with open(DATA_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        logger.info("formats.json updated from Wikipedia.")

    stale_marker.write_text(str(time.time()))
    return changed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    updated = refresh_formats(force=True)
    print("Updated:" if updated else "No changes.")
