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
import threading

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
