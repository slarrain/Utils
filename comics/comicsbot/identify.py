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
    and return them; None means `path` is a normal comic (or not a container)."""
    inner_exts = config.ARCHIVE_EXTS
    ext = path.suffix.lower()
    if ext in (".zip", ".cbz"):
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
    if ext in (".rar", ".cbr"):
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
    """Return a .cbz for `path`, converting RAR/7z archives if needed."""
    ext = path.suffix.lower()
    if ext == ".cbz":
        return path
    if ext == ".zip":
        target = path.with_suffix(".cbz")
        path.rename(target)
        return target
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
    cmd = ["comictagger", "--cv-api-key", config.CV_API_KEY, "-w", *args]
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
    m = re.search(r"Issue ID (\d+)", tags.get("Notes", ""))
    if not m:
        m = re.search(r"/4000-(\d+)", tags.get("Web", ""))
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


def parse_hints(text: str) -> dict:
    """Extract series/issue/year guesses from the Telegram message text."""
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
    return out


def _hints_to_m(h: dict) -> str:
    def esc(v: str) -> str:
        return v.replace(",", "^,").replace("=", "^=")
    parts = [f"{k}={esc(str(h[k]))}" for k in ("series", "issue", "year") if h.get(k)]
    return ", ".join(parts)


def tag_file(path: Path, hint_meta: dict) -> bool:
    """Try to auto-identify+tag. Success == ComicInfo.xml with a CV issue id."""
    attempts: list[list[str]] = [["-s", "-t", "CR", "-o", "-f"]]
    m = _hints_to_m(hint_meta)
    if m:
        attempts.append(["-s", "-t", "CR", "-o", "-f", "-m", m])
    attempts.append(["-s", "-t", "CR", "-o", "-f", "-1"])
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


def tag_with_issue_id(path: Path, issue_id: int) -> bool:
    try:
        _run_ct(["-s", "-t", "CR", "-o", "--id", str(issue_id), str(path)])
    except subprocess.TimeoutExpired:
        return False
    return read_tags(path).get("issue_id") == issue_id


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
