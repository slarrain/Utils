"""Identification: convert to CBZ, tag with ComicTagger (ComicVine), CV API helpers."""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

from . import config

log = logging.getLogger("comicsbot.identify")

CV_BASE = "https://comicvine.gamespot.com/api"
CV_HEADERS = {"User-Agent": "comics-bot/1.0 (santiago; personal NAS pipeline)"}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# --------------------------------------------------------------------------- #
# Archive normalization
# --------------------------------------------------------------------------- #
def _unique(p: Path) -> Path:
    n, d = 1, p
    while d.exists():
        n += 1
        d = p.with_stem(f"{p.stem} ({n})")
    return d


def explode_container(path: Path) -> list[Path] | None:
    """Channels often ship zips/rars that CONTAIN comic archives (one or many
    tomes) instead of pages. Extract the inner archives next to the container
    and return them; None means `path` is a normal comic (or not a container).

    The archive format is sniffed from the CONTENT, not the extension: release
    groups routinely ship a zip named .cbr (and vice versa). Dispatching on the
    extension sent such a zip to the UnRAR engine, which crashed with
    "OpenResult is 13" — that is how "Las guerras silenciosas ... CRG.cbr"
    (a zip) died before it could even be identified."""
    inner_exts = config.ARCHIVE_EXTS
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if any(Path(n).suffix.lower() in IMAGE_EXTS for n in names):
                return None
            inner = [n for n in names if Path(n).suffix.lower() in inner_exts]
            if not inner:
                return None
            out = []
            for n in inner:
                dest = _unique(path.parent / Path(n).name)
                with zf.open(n) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                out.append(dest)
        path.unlink()
        return out
    with open(path, "rb") as fh:
        magic = fh.read(8)
    if magic.startswith(b"Rar!"):
        from unrar.cffi import rarfile as unrarfile

        rf = unrarfile.RarFile(str(path))
        infos = [i for i in rf.infolist() if not i.is_dir()]
        if any(Path(i.filename).suffix.lower() in IMAGE_EXTS for i in infos):
            return None
        inner = [i for i in infos if Path(i.filename).suffix.lower() in inner_exts]
        if not inner:
            return None
        out = []
        for i in inner:
            dest = _unique(path.parent / Path(i.filename).name)
            dest.write_bytes(rf.read(i))
            out.append(dest)
        path.unlink()
        return out
    return None


def ensure_cbz(path: Path) -> Path:
    """Return a .cbz for `path`, converting RAR/7z archives if needed.

    The archive format is detected from the CONTENT, not the extension —
    release groups routinely ship zips named .cbr (and vice versa), and
    dispatching on the extension made those fail as "unreadable"."""
    ext = path.suffix.lower()
    if zipfile.is_zipfile(path):
        if ext == ".cbz":
            return path
        target = path.with_suffix(".cbz")
        path.rename(target)
        return target
    with open(path, "rb") as fh:
        magic = fh.read(8)
    if magic.startswith(b"Rar!"):
        return _rar_to_cbz(path)
    if magic.startswith(b"7z\xbc\xaf\x27\x1c"):
        return _unar_to_cbz(path)
    # Unrecognized magic: fall back to the extension's converter.
    if ext in (".cbr", ".rar"):
        return _rar_to_cbz(path)
    if ext in (".cb7", ".7z"):
        return _unar_to_cbz(path)
    raise ValueError(f"unsupported archive type: {path.name}")


def _rar_to_cbz(path: Path) -> Path:
    """Convert with the official UnRAR engine (unar mangles some RAR5 files)."""
    from unrar.cffi import rarfile as unrarfile

    rf = unrarfile.RarFile(str(path))
    infos = [i for i in rf.infolist() if not i.is_dir()]
    if not any(Path(i.filename).suffix.lower() in IMAGE_EXTS for i in infos):
        raise ValueError(f"no images found inside {path.name}")
    target = path.with_suffix(".cbz")
    tmp = target.with_suffix(".cbz.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        for i in sorted(infos, key=lambda i: i.filename.lower()):
            data = rf.read(i)
            if len(data) != i.file_size:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"short read on {i.filename} — archive damaged?")
            zf.writestr(i.filename, data)
    tmp.rename(target)
    path.unlink()
    return target


def _unar_to_cbz(path: Path) -> Path:
    target = path.with_suffix(".cbz")
    with tempfile.TemporaryDirectory(prefix="cbconv-") as td:
        try:
            subprocess.run(
                ["unar", "-quiet", "-no-directory", "-output-directory", td, str(path)],
                check=True, capture_output=True, text=True, timeout=600,
            )
        except subprocess.CalledProcessError as e:
            tail = (e.stdout or e.stderr or "").strip().splitlines()[-1:]
            raise ValueError(f"extraction failed: {' '.join(tail) or e}") from e
        files = sorted(
            (f for f in Path(td).rglob("*") if f.is_file()),
            key=lambda f: str(f).lower(),
        )
        if not any(f.suffix.lower() in IMAGE_EXTS for f in files):
            raise ValueError(f"no images found inside {path.name}")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as zf:
            for f in files:
                zf.write(f, f.relative_to(td).as_posix())
    path.unlink()
    return target


# --------------------------------------------------------------------------- #
# ComicTagger
# --------------------------------------------------------------------------- #
def _run_ct(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(config.DATA))
    # ComicTagger 1.6 CLI: --comicvine-key (was --cv-api-key), --no-gui to force
    # the commandline; -s/--save writes tags now (the old 1.5.x -w is gone).
    cmd = ["comictagger", "--comicvine-key", config.CV_API_KEY, "--no-gui", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)


def read_tags(path: Path) -> dict:
    """Parse ComicInfo.xml inside the cbz. Returns {} if absent."""
    try:
        with zipfile.ZipFile(path) as zf:
            name = next((n for n in zf.namelist() if n.lower() == "comicinfo.xml"), None)
            if not name:
                return {}
            root = ET.fromstring(zf.read(name))
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return {}
    tags = {el.tag: (el.text or "") for el in root}
    issue_id = None
    # Only trust an issue id as a COMICVINE id if the tags say so — manual
    # tagging may use other sources (e.g. Grand Comics Database) whose ids
    # must not be sent to the ComicVine API.
    m = None
    if "comic vine" in tags.get("Notes", "").lower():
        m = re.search(r"Issue ID (\d+)", tags.get("Notes", ""))
    if not m:
        m = re.search(r"comicvine\.gamespot\.com/[^\s]*/4000-(\d+)", tags.get("Web", ""))
    if m:
        issue_id = int(m.group(1))
    tags["issue_id"] = issue_id
    return tags


def normalize_numbering(s: str) -> str:
    """Spanish/euro numbering: 'nº2'/'núm. 2' → '#2'; drop volume markers
    ('vol3', 'Vol. 3', 'tomo 2') so they aren't mistaken for issue numbers."""
    s = re.sub(r"(?:nº|n°|núm\.?|núm|no\.)\s*(?=\d)", "#", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:vol(?:umen|ume)?|tomo|libro|book|v)\.?\s*\d+", " ", s, flags=re.IGNORECASE)
    return s


# --------------------------------------------------------------------------- #
# Structured caption fields ("Comicverso" style: emoji | value per line) and the
# publisher->language map used to pick the right EDITION of a multi-language
# series (e.g. Thorgal, printed under the same cover art by ~10 publishers).
# --------------------------------------------------------------------------- #
_CAPTION_FIELDS = {  # emoji marker -> field
    "📔": "series", "🗞": "publisher", "💬": "language", "📂": "count", "🗓": "year",
}

PUBLISHER_LANG = {
    "es": ("norma", "panini españa", "panini espana", "ecc ediciones", "ecc",
           "planeta", "ediciones b", "la cúpula", "la cupula", "astiberri",
           "yermo", "dolmen", "kraken", "ponent mon", "aleta", "salvat",
           "sd edicions", "órbita", "orbita", "dibbuks"),
    "en": ("marvel", "dc comics", "image", "dark horse", "idw", "boom",
           "dynamite", "vertigo", "valiant", "oni press", "titan", "fantagraphics",
           "drawn & quarterly", "mad cave", "vault", "ablaze", "abstract"),
    "fr": ("le lombard", "lombard", "dargaud", "dupuis", "casterman", "glénat",
           "glenat", "delcourt", "soleil", "bamboo", "hachette", "albatros"),
    "de": ("splitter", "carlsen", "egmont", "cross cult", "panini deutschland"),
}


def publisher_language(name: str | None) -> str | None:
    n = (name or "").lower()
    for lang, markers in PUBLISHER_LANG.items():
        if any(mk in n for mk in markers):
            return lang
    return None


def norm_language(v: str) -> str | None:
    v = (v or "").lower()
    table = {
        "es": ("español", "espanol", "castellano", "spanish", "🇪🇸", "🇲🇽", "🇦🇷", "🇨🇱"),
        "en": ("english", "inglés", "ingles", "🇺🇸", "🇬🇧"),
        "fr": ("français", "francais", "french", "🇫🇷"),
        "de": ("deutsch", "german", "alemán", "aleman", "🇩🇪"),
    }
    for lang, toks in table.items():
        if any(t in v for t in toks):
            return lang
    return None


def _pub_display(s: str) -> str:
    """'#LeLombard' -> 'Le Lombard', 'DCComics' -> 'DC Comics'."""
    s = s.strip().lstrip("#")
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", s)
    return " ".join(parts) if parts else s


def _parse_structured(text: str) -> dict:
    """Pull the emoji-tagged caption fields (first value per field wins)."""
    out: dict = {}
    for line in (text or "").splitlines():
        s = line.strip()
        for emo, field in _CAPTION_FIELDS.items():
            if s.startswith(emo) and field not in out:
                val = s[len(emo):].lstrip(" |\t️").strip()
                if val:
                    out[field] = val
                break
    return out


def parse_hints(text: str) -> dict:
    """Extract series/issue/year/publisher/language/count guesses from the note.

    Free text falls back to the line-heuristic below; the structured Comicverso
    caption (📔 series, 🗞 publisher, 💬 language, 📂 count) overrides it with
    cleaner, explicitly-labelled values."""
    if not text:
        return {}
    clean = re.sub(r"https?://\S+", "", normalize_numbering(text))
    candidates = [ln for ln in clean.splitlines() if re.search(r"[A-Za-z]{2}", ln)]
    boilerplate = re.compile(
        r"download|mega|mediafire|pixeldrain|zippyshare|terabox|gofile|1fichier"
        r"|rapidgator|katfile|link|mirror|password|size|formato?|weight",
        re.IGNORECASE,
    )
    line = (next((ln for ln in candidates if re.search(r"#\s*\d", ln)), None)
            or next((ln for ln in candidates if not boilerplate.search(ln)), None)
            or (candidates[0] if candidates else ""))
    line = re.sub(r"[#@]\w+$", "", line).strip()
    out: dict = {}
    m = (re.search(r"#\s*(\d+(?:\.\d+)?)", line)
         or re.search(r"\b(\d{1,3})\s*(?=\((?:19|20)\d{2}\))", line)
         or re.search(r"\b(\d{1,3})\s*$", line)
         or re.search(r"#\s*(\d+(?:\.\d+)?)", clean))
    if m:
        out["issue"] = m.group(1)
    y = (re.search(r"\((19|20)\d{2}\)", line) or re.search(r"\b((?:19|20)\d{2})\b", line)
         or re.search(r"\((19|20)\d{2}\)", clean) or re.search(r"\b((?:19|20)\d{2})\b", clean))
    if y:
        out["year"] = y.group(0).strip("()")
    series = re.split(r"#|\(", line)[0]
    series = re.sub(r"[^\w' .\-&]+", " ", series)
    series = re.sub(r"\s{2,}", " ", series).strip(" -.")
    if out.get("issue"):
        # Drop a trailing issue number ("Absolute Superman 001" -> "Absolute Superman")
        series = re.sub(rf"\s+0*{re.escape(out['issue'])}$", "", series)
    if len(series) >= 3:
        out["series"] = series

    # Structured caption fields win — they are explicitly labelled.
    st = _parse_structured(text)
    if st.get("series"):
        s = re.sub(r"#\w+", " ", st["series"])
        s = re.sub(r"[^\w' .\-&:]+", " ", s)          # keep ':' for "X: Subtitle"
        s = re.sub(r"\s{2,}", " ", s).strip(" -.:")
        if len(s) >= 2:
            out["series"] = s
    if st.get("publisher"):
        out["publisher"] = _pub_display(st["publisher"])
    if st.get("language"):
        lang = norm_language(st["language"])
        if lang:
            out["language"] = lang
    if st.get("count") and "?" not in st["count"]:
        nums = [int(n) for n in re.findall(r"\d+", st["count"])]
        if nums:
            out["count"] = max(nums)
    if st.get("year") and not out.get("year"):
        ym = re.search(r"(?:19|20)\d{2}", st["year"])
        if ym:
            out["year"] = ym.group(0)
    return out


def _hints_to_m(h: dict) -> str:
    """Build ComicTagger 1.6 `-m` metadata (YAML). Single-quote every value
    (doubling internal quotes) so a colon/comma in a value can't break the map.

    Deliberately OMITS 'year': fan-scan captions carry the ORIGINAL series /
    reference year (e.g. Thorgal's "1997"), almost never the ComicVine edition's
    start-year, and ComicTagger uses year as a HARD filter — a wrong year makes
    the search return "Found 0 series" and forces a needless prompt (verified).
    Series + issue is enough; covers do the disambiguation."""
    def q(v: str) -> str:
        return "'" + str(v).replace("'", "''") + "'"
    parts = [f"{k}: {q(h[k])}" for k in ("series", "issue") if h.get(k)]
    return ", ".join(parts)


def tag_file(path: Path, hint_meta: dict) -> bool:
    """Try to auto-identify+tag. Success == ComicInfo.xml with a CV issue id."""
    # --no-use-year-when-identifying: never let a stray year (from -m or the
    # filename) FILTER out candidates — see _hints_to_m.
    base = ["-s", "--tags-write", "CR", "-o", "--no-use-year-when-identifying"]
    attempts: list[list[str]] = [[*base, "-f"]]
    m = _hints_to_m(hint_meta)
    if m:
        # Anchor the online search to the message-text hints (series/issue).
        attempts.append([*base, "-f", "-m", m])
        # Last resort — assume issue #1 when none was parsed, but keep it
        # anchored to the hinted series via -m. A *bare* "-f -1" (no -m) lets
        # ComicTagger's fuzzy search wander to an unrelated volume that merely
        # shares a stray number in the filename: that is how "Maxentius_02" got
        # filed as "Kikaider Code 02 #1". With no hints at all we'd rather fall
        # through and ask the owner than guess a wrong series.
        attempts.append([*base, "-f", "-m", m, "-1"])
    for extra in attempts:
        try:
            r = _run_ct([*extra, str(path)])
        except subprocess.TimeoutExpired:
            log.warning("comictagger timed out on %s", path.name)
            continue
        log.info("comictagger %s -> rc=%s", extra[:6], r.returncode)
        if read_tags(path).get("issue_id"):
            return True
    return False


def write_basic_tags(path: Path, meta: dict) -> None:
    """Write a minimal ComicInfo.xml from message hints (no ComicVine)."""
    root = ET.Element("ComicInfo")
    fields = {
        "Series": meta.get("series"),
        "Number": meta.get("issue"),
        "Year": meta.get("year"),
        "Publisher": meta.get("publisher"),
        "Summary": meta.get("summary"),
        "Notes": "Tagged by comics-bot from Telegram message text (not on ComicVine).",
    }
    for tag, value in fields.items():
        if value:
            ET.SubElement(root, tag).text = str(value)
    xml = ET.tostring(root, encoding="unicode")
    with zipfile.ZipFile(path, "a") as zf:
        if not any(n.lower() == "comicinfo.xml" for n in zf.namelist()):
            zf.writestr("ComicInfo.xml", '<?xml version="1.0"?>\n' + xml)


def _extract_synopsis(text: str) -> str | None:
    """The note's prose blurb — the longest non-field, non-link line with real
    sentences. Skips the emoji caption fields and short lines."""
    best = ""
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith(tuple(_CAPTION_FIELDS)) or re.search(r"https?://", s):
            continue
        if len(re.findall(r"\w+", s)) >= 8 and len(s) > len(best):
            best = s
    return best[:1500] or None


def _replace_zip_entry(path: Path, entry: str, data: bytes) -> None:
    with zipfile.ZipFile(path) as zin:
        items = [(n, zin.read(n)) for n in zin.namelist() if n != entry]
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zout:
        for n, d in items:
            zout.writestr(n, d)
        zout.writestr(entry, data)
    tmp.replace(path)


def ensure_summary(path: Path, text: str) -> None:
    """If the archive's ComicInfo has no Summary, fill it from the note's blurb
    (so a rich forwarded synopsis isn't lost when ComicVine has no description).
    Never overwrites an existing summary."""
    synopsis = _extract_synopsis(text)
    if not synopsis:
        return
    try:
        with zipfile.ZipFile(path) as zf:
            name = next((n for n in zf.namelist() if n.lower() == "comicinfo.xml"), None)
            if not name:
                return
            root = ET.fromstring(zf.read(name))
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return
    el = root.find("Summary")
    if el is not None and (el.text or "").strip():
        return
    if el is None:
        el = ET.SubElement(root, "Summary")
    el.text = synopsis
    _replace_zip_entry(path, name, ('<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")).encode("utf-8"))


def tag_with_issue_id(path: Path, issue_id: int) -> bool:
    try:
        _run_ct(["-s", "--tags-write", "CR", "-o", "--id", str(issue_id), str(path)])
    except subprocess.TimeoutExpired:
        return False
    return read_tags(path).get("issue_id") == issue_id


def clear_tags(path: Path) -> None:
    """Remove ComicInfo.xml from the archive so a distrusted auto-match is not
    reused downstream as if it were the file's own embedded metadata."""
    with zipfile.ZipFile(path) as zin:
        keep = [n for n in zin.namelist() if n.lower() != "comicinfo.xml"]
        if len(keep) == len(zin.namelist()):
            return
        payload = [(n, zin.read(n)) for n in keep]
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zout:
        for n, data in payload:
            zout.writestr(n, data)
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# ComicVine API (for candidates and series metadata)
# --------------------------------------------------------------------------- #
def _cv_get(path: str, **params):
    params.update(api_key=config.CV_API_KEY, format="json")
    r = requests.get(f"{CV_BASE}/{path}", params=params, headers=CV_HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("status_code") != 1:
        raise RuntimeError(f"ComicVine error: {j.get('error')}")
    return j.get("results")


def search_volumes(name: str, limit: int = 6) -> list[dict]:
    res = _cv_get("search/", query=name, resources="volume", limit=limit) or []
    out = []
    for v in res:
        out.append({
            "id": v["id"],
            "name": v.get("name") or "?",
            "year": v.get("start_year") or "?",
            "publisher": (v.get("publisher") or {}).get("name", "?"),
            "issues": v.get("count_of_issues"),
        })
    return out


def _norm_name(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


_PUB_STOP = {"comics", "comic", "editorial", "ediciones", "editions", "entertainment",
             "the", "le", "la", "el", "los", "las", "de", "and", "y", "verlag"}


def _pub_overlap(a: str | None, b: str | None) -> bool:
    wa = set(re.findall(r"\w+", (a or "").lower())) - _PUB_STOP
    wb = set(re.findall(r"\w+", (b or "").lower())) - _PUB_STOP
    return bool(wa & wb)


def rank_volumes(name: str, hint: dict, limit: int = 8) -> list[dict]:
    """search_volumes, re-ordered by how well each volume fits the note: same
    language (publisher-inferred) first, then publisher-name overlap, then a
    plausible issue count (📂), then exact name and completeness."""
    cands = search_volumes(name, limit=limit)
    lang, pub, cnt = hint.get("language"), hint.get("publisher"), hint.get("count")

    def score(c: dict) -> float:
        s = 0.0
        if lang and publisher_language(c.get("publisher")) == lang:
            s += 100
        if pub and _pub_overlap(pub, c.get("publisher")):
            s += 10
        iss = c.get("issues") or 0
        if cnt:
            s += 5 if iss >= cnt else -25          # too small to hold the run
        if _norm_name(c.get("name")) == _norm_name(name):
            s += 3
        s += min(iss, 60) / 100.0
        return s

    return sorted(cands, key=score, reverse=True)


def pick_edition(candidates: list[dict], hint: dict) -> dict | None:
    """Auto-select a volume only when the note's language pins a SINGLE edition
    (same series name, matching language, and — if given — able to hold the run).
    Returns None when it is ambiguous, so the caller falls back to asking."""
    lang = hint.get("language")
    if not lang or not candidates:
        return None
    name = hint.get("series") or ""
    same = [c for c in candidates if _norm_name(c.get("name")) == _norm_name(name)] or candidates
    hits = [c for c in same if publisher_language(c.get("publisher")) == lang]
    cnt = hint.get("count")
    if cnt:
        fit = [c for c in hits if (c.get("issues") or 0) >= cnt]
        if fit:
            hits = fit
    return hits[0] if len(hits) == 1 else None


def volume_of_issue(issue_id: int) -> dict | None:
    res = _cv_get(f"issue/4000-{issue_id}/", field_list="volume")
    return (res or {}).get("volume")


def volume_info(volume_id: int) -> dict:
    return _cv_get(
        f"volume/4050-{volume_id}/",
        field_list="id,name,start_year,publisher,count_of_issues,image,"
                   "site_detail_url,description",
    )


def find_issue(volume_id: int, number: str) -> dict | None:
    res = _cv_get(
        "issues/",
        filter=f"volume:{volume_id},issue_number:{number}",
        field_list="id,issue_number,cover_date",
    )
    return res[0] if res else None
