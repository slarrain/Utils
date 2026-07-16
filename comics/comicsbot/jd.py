"""My.JDownloader API client: submit links and verify they actually appear.

Why not just crawljob files: FolderWatch proved unreliable for some hosts
(florenfile) — JD consumed the .crawljob but the links sometimes never surfaced
anywhere (docs/florenfile-jdownloader-issue.md). `linkgrabber/addLinks` over
My.JDownloader is the same path as the UI's "Add Links" dialog, which always
worked, so the API is the primary route; the crawljob is only a fallback when
the API is unreachable. Either way the caller verifies with find_package().

All functions here are blocking (myjdapi uses requests) — call them through
asyncio.to_thread from the bot.
"""
import logging
import re
import threading
import time
import urllib.parse

import myjdapi

log = logging.getLogger("comicsbot.jd")

_lock = threading.Lock()
_api: myjdapi.Myjdapi | None = None


def _credentials() -> tuple[str, str, str, str]:
    from . import config
    if not (config.MYJD_EMAIL and config.MYJD_PASSWORD):
        raise RuntimeError("MYJD_EMAIL / MYJD_PASSWORD not configured")
    return config.MYJD_EMAIL, config.MYJD_PASSWORD, config.MYJD_DEVICE, config.MYJD_APP_KEY


def _device(fresh: bool = False):
    """Connected device handle; the session is cached and rebuilt on demand
    (My.JDownloader sessions die when another client with the same key logs in)."""
    global _api
    email, password, device_name, app_key = _credentials()
    if fresh or _api is None:
        api = myjdapi.Myjdapi()
        api.set_app_key(app_key)
        api.connect(email, password)
        _api = api
    return _api.get_device(device_name)


def _call(fn):
    """Run fn(device), reconnecting once if the cached session went stale."""
    with _lock:
        try:
            return fn(_device())
        except myjdapi.exception.MYJDException:
            return fn(_device(fresh=True))


def add_links(package_name: str, urls: list[str], download_folder: str,
              autostart: bool = True) -> None:
    """Add urls to JD's LinkGrabber exactly like the UI's Add Links dialog.
    With autostart the package auto-confirms into Downloads once checked."""
    payload = {
        "assignJobID": True,
        "autoExtract": True,
        "autostart": autostart,
        "deepDecrypt": True,
        "destinationFolder": download_folder,
        "links": "\n".join(urls),
        "overwritePackagizerRules": True,
        "packageName": package_name,
    }
    _call(lambda d: d.linkgrabber.add_links(params=[payload]))
    log.info("myjd add_links %r (%d links)", package_name, len(urls))


def find_package(package_name: str) -> dict | None:
    """Locate a package by name in Downloads or the LinkGrabber.

    Returns {"where": "downloads"|"linkgrabber", "status": str, ...} or None if
    JD shows no trace of it (the silent-drop failure mode we guard against)."""
    def _find(d):
        for p in d.downloads.query_packages([{
                "status": True, "bytesTotal": True, "enabled": True,
                "finished": True, "hosts": True, "maxResults": -1, "startAt": 0}]):
            if p.get("name") == package_name:
                return {"where": "downloads",
                        "status": p.get("status") or ("finished" if p.get("finished") else "queued"),
                        "bytes": p.get("bytesTotal", 0), "hosts": p.get("hosts", [])}
        for p in d.linkgrabber.query_packages([{
                "bytesTotal": True, "hosts": True, "availableOnlineCount": True,
                "availableOfflineCount": True, "availableUnknownCount": True,
                "maxResults": -1, "startAt": 0}]):
            if p.get("name") == package_name:
                online, offline = p.get("onlineCount", 0), p.get("offlineCount", 0)
                return {"where": "linkgrabber",
                        "status": f"collected ({online} online, {offline} offline)",
                        "bytes": p.get("bytesTotal", 0), "hosts": p.get("hosts", [])}
        return None
    return _call(_find)


def remove_from_linkgrabber(package_name: str) -> bool:
    """Drop a package from the LinkGrabber (used by tests/cleanup)."""
    def _remove(d):
        for p in d.linkgrabber.query_packages([{"maxResults": -1, "startAt": 0}]):
            if p.get("name") == package_name:
                d.linkgrabber.remove_links(package_ids=[p["uuid"]])
                return True
        return False
    return _call(_remove)


# --------------------------------------------------------------------------- #
# getcomics.org mirror pruning
#
# JD's GetComicsInfo decrypter resolves a getcomics release page into one link per
# mirror per file (verified: it does NOT dedupe, and keeps the packageName/folder we
# set via the API). It is slow (minutes), so the bot adds the page PAUSED, waits for
# the crawl to settle, keeps one mirror per file, and starts only those.
# --------------------------------------------------------------------------- #
_COMIC_EXTS = (".cbz", ".cbr", ".cb7", ".zip", ".rar", ".7z", ".pdf", ".epub")


def is_collecting() -> bool:
    """True while the LinkGrabber is still crawling/decrypting."""
    return bool(_call(lambda d: d.linkgrabber.is_collecting()))


def _lg_package(d, package_name: str) -> dict | None:
    for p in d.linkgrabber.query_packages([{
            "saveTo": True, "childCount": True, "bytesTotal": True,
            "availableOnlineCount": True, "availableOfflineCount": True,
            "maxResults": -1, "startAt": 0}]):
        if p.get("name") == package_name:
            return p
    return None


def linkgrabber_package(package_name: str) -> dict | None:
    """LinkGrabber package by name (with childCount/online counts), or None."""
    return _call(lambda d: _lg_package(d, package_name))


def _norm_filename(name: str) -> str:
    """Grouping key that makes mirrors of the same file collide. datanodes encodes
    the filename in its URL path (underscores, and %2526 for '&'), so decode twice
    and reduce to lowercase words — that matches the space-named mirrors."""
    n = urllib.parse.unquote(urllib.parse.unquote(name or ""))
    n = re.sub(r"\.[a-z0-9]{2,4}$", "", n, flags=re.I)      # drop the extension
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def _host_rank(host: str, priority) -> int:
    h = (host or "").lower()
    for i, key in enumerate(priority):
        if key in h:
            return i
    return len(priority) + 1                                 # unknown host: keep, but last


def prune_getcomics_mirrors(package_name: str, priority, drop_hosts=(),
                            keep_per_file: int = 4) -> dict | None:
    """For a resolved getcomics package, keep — per file — the set of *same-filename*
    mirrors so JD's own mirror detection downloads one and fails over to the next if a
    host errors (a link checking ONLINE does not guarantee it downloads). Everything
    else is dropped and the survivors moved to Downloads.

    Selection: real comic files only (drops ad.js, Cloudflare/"Content offline" stubs
    and unresolved mega hashes), never `drop_hosts` (terabox/mega), grouped into a
    file by normalized name; within a file the canonical mirror set is the raw-filename
    group with the most members (so JD groups them — a lone odd-named host like
    datanodes is excluded), capped at `keep_per_file`, ordered by `priority`. Returns
    {"kept": [{"file", "mirrors": [{"host","bytes"}]}], "dropped": n, "files": n} or
    None if the package isn't in the LinkGrabber.

    Read and move are split so the SAME link ids are moved even if a call is retried:
    under a flaky connection `move_to_downloadlist`'s response can be lost after JD
    already executed it — retrying the whole select-then-move would re-pick different
    leftovers and move them too (a duplicate download, observed under load). Moving
    fixed ids is idempotent: re-moving links already in Downloads is a no-op."""
    def _read(d):
        pkg = _lg_package(d, package_name)
        if not pkg:
            return None
        return d.linkgrabber.query_links([{
            "packageUUIDs": [pkg["uuid"]], "url": True, "host": True, "bytesTotal": True,
            "availability": True, "status": True, "maxResults": -1, "startAt": 0}])
    links = _call(_read)
    if links is None:
        return None

    def _rank(lk):
        return _host_rank(lk.get("host"), priority)

    real = [lk for lk in links
            if (lk.get("name") or "").lower().endswith(_COMIC_EXTS)
            and (lk.get("bytesTotal") or 0) > 1_000_000
            and lk.get("availability") != "OFFLINE"
            and not any(h in (lk.get("host") or "").lower() for h in drop_hosts)]
    files: dict[str, list] = {}
    for lk in real:
        files.setdefault(_norm_filename(lk.get("name")), []).append(lk)
    keep_ids, kept = [], []
    for mirrors in files.values():
        # JD groups by raw filename; pick the raw-name group with the most members
        # (the canonical set) so JD treats them as one file's mirrors + fails over.
        by_raw: dict[str, list] = {}
        for lk in mirrors:
            by_raw.setdefault((lk.get("name") or "").lower(), []).append(lk)
        canon = max(by_raw.values(),
                    key=lambda g: (len(g), -min(_rank(x) for x in g)))
        canon.sort(key=lambda lk: (_rank(lk),
                                   0 if lk.get("availability") == "ONLINE" else 1,
                                   -(lk.get("bytesTotal") or 0)))
        chosen = canon[:keep_per_file]
        keep_ids.extend(m["uuid"] for m in chosen)
        kept.append({"file": chosen[0].get("name"),
                     "mirrors": [{"host": m.get("host"), "bytes": m.get("bytesTotal", 0)}
                                 for m in chosen]})
    keep_set = set(keep_ids)
    reject_ids = [lk["uuid"] for lk in links if lk["uuid"] not in keep_set]
    if keep_ids:  # fixed ids -> retry-safe (see docstring)
        _call(lambda d: d.linkgrabber.move_to_downloadlist(keep_ids, []))
    if reject_ids:
        _call(lambda d: d.linkgrabber.remove_links(link_ids=reject_ids, package_ids=[]))
    return {"kept": kept, "dropped": len(reject_ids), "files": len(kept),
            "mirrors_kept": len(keep_ids)}


def start_getcomics_download(package_name: str) -> bool:
    """Force just this package's links to download after pruning, without resuming
    the user's other (possibly intentionally paused) downloads via a global start.
    Retries briefly because the package may take a moment to appear in Downloads
    after move_to_downloadlist."""
    def _start(d):
        for _ in range(6):
            for p in d.downloads.query_packages([{"maxResults": -1, "startAt": 0}]):
                if p.get("name") == package_name:
                    d.downloadcontroller.force_download([], [p["uuid"]])
                    return True
            time.sleep(2)
        return False
    return _call(_start)
