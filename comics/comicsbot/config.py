"""Configuration via environment variables (set by deploy scripts / docker run)."""
import os
from pathlib import Path


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"Missing required environment variable: {name}")
    return v or ""


API_ID = int(_env("TELEGRAM_API_ID", required=True))
API_HASH = _env("TELEGRAM_API_HASH", required=True)
BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", required=True)
# Optional: pin the owner. If 0, the first user to /start the bot becomes owner.
OWNER_ID = int(_env("TELEGRAM_OWNER_ID", "0") or 0)

CV_API_KEY = _env("COMICVINE_API_KEY", required=True)

KOMGA_URL = _env("KOMGA_URL").rstrip("/")
KOMGA_EMAIL = _env("KOMGA_EMAIL")
KOMGA_PASSWORD = _env("KOMGA_PASSWORD")
KOMGA_LIBRARY_ID = _env("KOMGA_LIBRARY_ID")  # optional; autodetected if empty

# My.JDownloader account (same credentials as the JD app on the NAS). Optional:
# without them the bot falls back to crawljob files only.
MYJD_EMAIL = _env("MYJD_EMAIL")
MYJD_PASSWORD = _env("MYJD_PASSWORD")
MYJD_DEVICE = _env("MYJD_DEVICE", "NAS")
MYJD_APP_KEY = _env("MYJD_APP_KEY", "comicsbot")

INBOX = Path(_env("INBOX_DIR", "/inbox"))
LIBRARY = Path(_env("LIBRARY_DIR", "/library"))
DATA = Path(_env("DATA_DIR", "/data"))
# The same INBOX folder as seen from *inside* the JDownloader container.
JD_DOWNLOAD_ROOT = _env("JD_DOWNLOAD_ROOT", "/output/COMICS")

TELEGRAM_INBOX = INBOX / "telegram"
FOLDERWATCH = INBOX / "folderwatch"
FAILED = INBOX / "failed"
# Manually-tagged comics dropped here are filed from their embedded tags,
# with no re-identification — the human's tagging always wins.
TAGGED = INBOX / "tagged"
HINTS = DATA / "hints"
PENDING = DATA / "pending"

ARCHIVE_EXTS = {".cbz", ".cbr", ".cb7", ".zip", ".rar", ".7z"}
OTHER_EXTS = {".pdf", ".epub"}


def ensure_dirs() -> None:
    for p in (TELEGRAM_INBOX, FOLDERWATCH, FAILED, TAGGED, HINTS, PENDING, DATA):
        p.mkdir(parents=True, exist_ok=True)
