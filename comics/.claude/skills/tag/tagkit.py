#!/usr/bin/env python3
"""tagkit — engine for the /tag skill.

Tags comics that failed automatic identification and files them into the Komga
library, reusing the comics-bot's own identify/filer code plus the local
ComicTagger AppImage. All ComicVine calls are throttled + retried.

Config is read automatically from ../../../deploy.conf and deploy.secrets, with
the NAS paths remapped to the local /mnt/nas NFS mount. Override LIBRARY_DIR /
INBOX_DIR / COMICTAGGER_APPIMAGE via the environment if needed.

Commands (JSON in/out):
  list [--unknown] [NAME]                 untagged archives in failed/ (or Unknown/)
  resolve NAME [--language es --count N]   ranked ComicVine volume candidates
  tag-series --volume V --files F.json     tag+file [{path, issue}, ...] to volume V
  asis --path P --series S [--publisher…]  file a not-on-ComicVine comic as-is
  scan                                     trigger a Komga library scan
"""
import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../comics


# --------------------------------------------------------------------------- #
# Config from deploy.conf / deploy.secrets (shell KEY=VALUE)
# --------------------------------------------------------------------------- #
def _kv(path: Path) -> dict:
    out: dict = {}
    if not path.is_file():
        return out
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith("export "):
            ln = ln[len("export "):]
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        v = v.strip()
        if v[:1] in ("'", '"'):
            v = v[1:].split(v[0], 1)[0]          # quoted value, kept intact
        else:
            v = v.split(" #", 1)[0].strip()      # trim an inline comment
        out[k.strip()] = v
    return out


def _local(p: str | None) -> str | None:
    return p.replace("/volume1/NAS", "/mnt/nas") if p else p


_conf = _kv(REPO / "deploy.conf")
_secr = _kv(REPO / "deploy.secrets")
os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "x")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
os.environ["COMICVINE_API_KEY"] = os.environ.get("COMICVINE_API_KEY") or _secr.get("COMICVINE_API_KEY", "")
os.environ["LIBRARY_DIR"] = os.environ.get("LIBRARY_DIR") or _local(_conf.get("NAS_LIBRARY_DIR")) or "/mnt/nas/comics"
os.environ["INBOX_DIR"] = os.environ.get("INBOX_DIR") or _local(_conf.get("NAS_INBOX_DIR")) or "/mnt/nas/downloads/COMICS"
os.environ["KOMGA_URL"] = os.environ.get("KOMGA_URL") or _conf.get("KOMGA_URL", "")
os.environ["KOMGA_EMAIL"] = os.environ.get("KOMGA_EMAIL") or _secr.get("KOMGA_EMAIL", "")
os.environ["KOMGA_PASSWORD"] = os.environ.get("KOMGA_PASSWORD") or _secr.get("KOMGA_PASSWORD", "")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="tagkit-"))
sys.path.insert(0, str(REPO))

from comicsbot import config, filer, identify  # noqa: E402


# --------------------------------------------------------------------------- #
# ComicTagger AppImage exposed as `comictagger` on PATH (so identify._run_ct
# finds it), and ComicVine throttled + cached.
# --------------------------------------------------------------------------- #
def _find_appimage() -> str | None:
    env = os.environ.get("COMICTAGGER_APPIMAGE")
    if env and Path(env).is_file():
        return env
    cands = [Path.home() / "Downloads" / "ComicTagger-x86_64.AppImage"]
    cands += sorted(Path.home().glob("Downloads/ComicTagger*.AppImage"))
    cands += sorted(Path.home().glob("*/ComicTagger*.AppImage"))
    return next((str(c) for c in cands if Path(c).is_file()), None)


def _install_shim() -> None:
    app = _find_appimage()
    if not app:
        sys.exit("ERROR: ComicTagger AppImage not found. "
                 "Set COMICTAGGER_APPIMAGE=/path/to/ComicTagger-x86_64.AppImage")
    d = Path(tempfile.mkdtemp(prefix="ct-shim-"))
    sh = d / "comictagger"
    sh.write_text(f'#!/bin/sh\nexec "{app}" "$@"\n')
    sh.chmod(0o755)
    os.environ["PATH"] = f"{d}:{os.environ['PATH']}"


_last = [0.0]
_orig_cv = identify._cv_get


def _cv(path, **p):
    for attempt in range(7):
        dt = time.time() - _last[0]
        if dt < 1.2:
            time.sleep(1.2 - dt)
        _last[0] = time.time()
        try:
            return _orig_cv(path, **p)
        except Exception as e:  # noqa: BLE001
            if "420" in str(e) and attempt < 6:
                time.sleep(6 * (attempt + 1))
                continue
            raise


identify._cv_get = _cv
identify.volume_info = functools.lru_cache(maxsize=None)(identify.volume_info)
_KNOWN_VOL: dict = {}
_orig_voi = identify.volume_of_issue


def _voi(issue_id):
    v = _KNOWN_VOL.get(int(issue_id))
    return {"id": v} if v else _orig_voi(issue_id)


identify.volume_of_issue = _voi

ARCHIVE_EXTS = config.ARCHIVE_EXTS
IMAGE_EXTS = identify.IMAGE_EXTS


# --------------------------------------------------------------------------- #
# Archive + filesystem helpers
# --------------------------------------------------------------------------- #
def to_cbz(path: Path) -> Path:
    """Return a .cbz, sniffing the real format (a zip named .cbr is common)."""
    if zipfile.is_zipfile(path):
        if path.suffix.lower() == ".cbz":
            return path
        t = path.with_suffix(".cbz")
        path.rename(t)
        return t
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic.startswith(b"Rar!"):
        td = tempfile.mkdtemp(prefix="tk-rar-")
        subprocess.run(["unrar", "x", "-o+", "-inul", str(path), td + "/"],
                       check=True, timeout=600)
        imgs = sorted((p for p in Path(td).rglob("*") if p.suffix.lower() in IMAGE_EXTS),
                      key=lambda p: str(p).lower())
        if not imgs:
            shutil.rmtree(td, ignore_errors=True)
            raise ValueError("no images inside archive")
        t = path.with_suffix(".cbz")
        with zipfile.ZipFile(t, "w", zipfile.ZIP_STORED) as z:
            for p in imgs:
                z.write(p, p.name)
        path.unlink()
        shutil.rmtree(td, ignore_errors=True)
        return t
    raise ValueError(f"unsupported archive: {path.name}")


def _cleanup_dir(d: Path) -> None:
    try:
        roots = (config.FAILED, config.TELEGRAM_INBOX, config.TAGGED, config.LIBRARY)
        if d not in roots and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass


def _guess_series(stem: str) -> str:
    s = re.sub(r"\[[^\]]*\]", " ", stem)
    s = re.sub(r"@\w+", " ", s)
    s = re.sub(r"#\s*\d.*$", " ", s)
    s = re.split(r"(?<![\w.])\d{1,4}(?![\w.])", s)[0]
    s = re.sub(r"[._]+", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" -")


def _guess_issue(stem: str):
    s = re.sub(r"\[[^\]]*\]", " ", stem).replace("_", " ")
    m = re.search(r"#\s*(\d+(?:\.\d+)?)", s)
    if m:
        return m.group(1)
    nums = [n for n in re.findall(r"(?<![\w.])(\d{1,4})(?![\w.])", s)
            if not re.fullmatch(r"(?:19|20)\d{2}", n)]
    return nums[-1] if nums else None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_list(args) -> None:
    if args.unknown:
        if not args.name:
            sys.exit('ERROR: --unknown requires a NAME, e.g. /tag --unknown "Asterix". '
                     "A blanket Unknown/ sweep is intentionally not allowed.")
        root = config.LIBRARY / "Unknown"
    else:
        root = config.FAILED
    if not root.is_dir():
        print("[]")
        return
    name = (args.name or "").lower()
    out = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in ARCHIVE_EXTS:
            continue
        if name and name not in str(f).lower():
            continue
        try:
            t = identify.read_tags(f)
        except Exception:  # noqa: BLE001
            t = {}
        out.append({
            "path": str(f),
            "series_guess": _guess_series(f.stem),
            "issue_guess": _guess_issue(f.stem),
            "has_cv_id": bool(t.get("issue_id")),
            "current_series": t.get("Series"),
            "current_publisher": t.get("Publisher"),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_resolve(args) -> None:
    hint = {"series": args.name}
    if args.language:
        hint["language"] = args.language
    if args.count:
        hint["count"] = args.count
    print(json.dumps(identify.rank_volumes(args.name, hint), ensure_ascii=False, indent=2))


def cmd_tag_series(args) -> None:
    _install_shim()
    files = json.loads(Path(args.files).read_text()) if args.files else json.loads(sys.stdin.read())
    results = []
    for item in files:
        p = Path(item["path"])
        issue_no = re.sub(r"^0+(?=\d)", "", str(item.get("issue") or "1"))
        if not p.exists():
            results.append({"path": str(p), "status": "missing"})
            continue
        try:
            cbz = to_cbz(p)
        except Exception as e:  # noqa: BLE001
            results.append({"path": str(p), "status": f"convert-failed: {e}"})
            continue
        try:
            issue = identify.find_issue(args.volume, issue_no)
        except Exception as e:  # noqa: BLE001
            results.append({"path": str(cbz), "status": f"cv-error: {e}"})
            continue
        if not issue:
            results.append({"path": str(cbz), "status": f"no issue #{issue_no} in volume {args.volume}"})
            continue
        _KNOWN_VOL[int(issue["id"])] = args.volume
        if not identify.tag_with_issue_id(cbz, issue["id"]):
            results.append({"path": str(cbz), "status": "tag-failed"})
            continue
        parent = cbz.parent
        try:
            dest = filer.file_comic(cbz, identify.read_tags(cbz))
        except Exception as e:  # noqa: BLE001
            results.append({"path": str(cbz), "status": f"file-failed: {e}"})
            continue
        _cleanup_dir(parent)
        results.append({"path": str(cbz), "status": "ok", "dest": str(dest.relative_to(config.LIBRARY))})
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_asis(args) -> None:
    p = Path(args.path)
    if not p.exists():
        sys.exit(f"missing: {p}")
    try:
        cbz = to_cbz(p)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"convert-failed: {e}")
    meta = {"series": args.series, "issue": args.issue or "", "year": args.year,
            "publisher": args.publisher, "summary": args.summary}
    identify.write_basic_tags(cbz, meta)
    parent = cbz.parent
    dest = filer.file_comic(cbz, identify.read_tags(cbz))
    _cleanup_dir(parent)
    print(json.dumps({"path": str(cbz), "status": "ok",
                      "dest": str(dest.relative_to(config.LIBRARY))}, ensure_ascii=False))


def cmd_scan(args) -> None:
    print(json.dumps({"komga_scan": filer.komga_scan()}))


def main() -> None:
    ap = argparse.ArgumentParser(prog="tagkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--unknown", action="store_true")
    p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("resolve")
    p.add_argument("name")
    p.add_argument("--language")
    p.add_argument("--count", type=int)
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("tag-series")
    p.add_argument("--volume", type=int, required=True)
    p.add_argument("--files")
    p.set_defaults(fn=cmd_tag_series)

    p = sub.add_parser("asis")
    p.add_argument("--path", required=True)
    p.add_argument("--series", required=True)
    p.add_argument("--publisher")
    p.add_argument("--year")
    p.add_argument("--issue")
    p.add_argument("--summary")
    p.set_defaults(fn=cmd_asis)

    p = sub.add_parser("scan")
    p.set_defaults(fn=cmd_scan)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
