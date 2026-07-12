"""File tagged comics into the library (Mylar-style layout) and poke Komga."""
import json
import logging
import re
import shutil
import threading
from pathlib import Path

import requests

from . import config, identify

log = logging.getLogger("comicsbot.filer")

_komga_library_id: str | None = None
# Serializes destination choice + move: two comics filing concurrently to the
# same name must get "(2)" suffixes, never overwrite each other.
_move_lock = threading.Lock()


def sanitize(name: str) -> str:
    """Match the existing library conventions (Mylar-style): drop colons, no path chars."""
    name = re.sub(r"\s*:\s*", " ", name)
    name = re.sub(r"[\\/]", "-", name)
    name = re.sub(r'[<>"|?*\x00-\x1f]', "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" .")


def _issue_str(number: str) -> str:
    number = (number or "1").strip()
    return re.sub(r"^0+(?=\d)", "", number) or "1"


def file_comic(path: Path, tags: dict) -> Path:
    """Move a tagged cbz into LIBRARY/Publisher/Series (Year)/, write sidecars."""
    issue_id = tags.get("issue_id")
    volume = identify.volume_of_issue(issue_id) if issue_id else None
    vinfo = identify.volume_info(volume["id"]) if volume else {}

    publisher = (vinfo.get("publisher") or {}).get("name") or tags.get("Publisher") or "Unknown"
    series = vinfo.get("name") or tags.get("Series") or path.stem
    start_year = vinfo.get("start_year") or tags.get("Year") or ""
    cover_year = tags.get("Year") or start_year
    issue = _issue_str(tags["Number"]) if tags.get("Number") else ""

    dir_name = f"{sanitize(series)} ({start_year})" if start_year else sanitize(series)
    publisher_dir = config.LIBRARY / sanitize(publisher)
    series_dir = publisher_dir / dir_name
    if not vinfo and not series_dir.exists() and publisher_dir.is_dir():
        # Without a ComicVine volume identity, sibling tomes carry different
        # cover years — reuse an existing folder for the same series name so
        # "Tome 1 (2011)" and "Tome 2 (2013)" land together.
        pattern = re.compile(rf"^{re.escape(sanitize(series))}( \(\d{{4}}\))?$", re.IGNORECASE)
        match = next((d for d in publisher_dir.iterdir()
                      if d.is_dir() and pattern.match(d.name)), None)
        if match:
            series_dir = match

    base = f"{sanitize(series)} {issue}".strip() + (f" ({cover_year})" if cover_year else "")
    with _move_lock:
        series_dir.mkdir(parents=True, exist_ok=True)
        dest = series_dir / f"{base}.cbz"
        n = 1
        while dest.exists():
            n += 1
            dest = series_dir / f"{base} ({n}).cbz"
        shutil.move(str(path), dest)

    if vinfo:
        cvinfo = series_dir / "cvinfo"
        if not cvinfo.exists() and vinfo.get("site_detail_url"):
            cvinfo.write_text(vinfo["site_detail_url"] + "\n")
        series_json = series_dir / "series.json"
        if not series_json.exists():
            desc = re.sub(r"<[^>]+>", "", vinfo.get("description") or "") or None
            series_json.write_text(json.dumps({
                "version": "1.0.2",
                "metadata": {
                    "type": "comicSeries",
                    "publisher": publisher,
                    "imprint": None,
                    "name": vinfo.get("name"),
                    "comicid": vinfo.get("id"),
                    "year": int(start_year) if str(start_year).isdigit() else None,
                    "description_text": desc,
                    "description_formatted": None,
                    "volume": None,
                    "booktype": "Print",
                    "age_rating": None,
                    "collects": None,
                    "comic_image": (vinfo.get("image") or {}).get("super_url"),
                    "total_issues": vinfo.get("count_of_issues"),
                    "publication_run": "",
                    "status": "Unknown",
                },
            }, ensure_ascii=False, indent=4))

    log.info("filed %s", dest)
    return dest


def guess_publisher(text: str) -> str | None:
    """Match the message text against existing publisher folders in the library."""
    if not text or not config.LIBRARY.is_dir():
        return None
    low = text.lower()
    best = None
    for d in config.LIBRARY.iterdir():
        if d.is_dir() and not d.name.startswith(("@", "_", ".")) and d.name.lower() in low:
            if best is None or len(d.name) > len(best):
                best = d.name
    return best


# --------------------------------------------------------------------------- #
# Komga
# --------------------------------------------------------------------------- #
def komga_scan() -> bool:
    global _komga_library_id
    if not (config.KOMGA_URL and config.KOMGA_EMAIL):
        return False
    auth = (config.KOMGA_EMAIL, config.KOMGA_PASSWORD)
    try:
        if not _komga_library_id:
            if config.KOMGA_LIBRARY_ID:
                _komga_library_id = config.KOMGA_LIBRARY_ID
            else:
                r = requests.get(f"{config.KOMGA_URL}/api/v1/libraries", auth=auth, timeout=30)
                r.raise_for_status()
                libs = r.json()
                if not libs:
                    return False
                match = next((l for l in libs if "comic" in (l.get("root") or "").lower()
                              or "comic" in (l.get("name") or "").lower()), libs[0])
                _komga_library_id = str(match["id"])
                log.info("komga library: %s (%s)", match.get("name"), _komga_library_id)
        r = requests.post(
            f"{config.KOMGA_URL}/api/v1/libraries/{_komga_library_id}/scan",
            auth=auth, timeout=30,
        )
        return r.status_code in (200, 202, 204)
    except requests.RequestException as e:
        log.warning("komga scan failed: %s", e)
        return False
