"""Handle incoming Telegram messages: download attachments, route links to JDownloader."""
import json
import logging
import re
import time
from urllib.parse import quote

from . import config, hints

log = logging.getLogger("comicsbot.ingest")

# Channels often split one comic across messages (cover photo + summary text +
# file/links, as adjacent channel posts). Messages without files/links are kept
# as context and merged into the hints of a nearby download.
#
# "Nearby" is decided by the forward origin when available: a forwarded message
# carries its source channel id and original post number, and posts of the same
# bundle have adjacent numbers. Without origin info (typed text, hidden
# forwards), we fall back to "same chat within the time window".
CONTEXT_WINDOW = 900      # seconds (large downloads keep bundles open a while)
ORIGIN_ADJACENCY = 8      # max distance between original post numbers
_recent_context: dict[int, list[dict]] = {}  # chat -> [{ts, text, origin, used}]
_recent_slugs: dict[int, list[dict]] = {}    # chat -> [{ts, slug, origin}]


def origin_of(msg) -> tuple:
    """(source_channel_id, original_post_id) of a forwarded message, or (None, None)."""
    f = msg.fwd_from
    if not f or f.channel_post is None:
        return (None, None)
    channel = getattr(getattr(f, "from_id", None), "channel_id", None)
    return (channel, f.channel_post)


def _prune(store: dict, chat_id: int) -> list[dict]:
    now = time.time()
    items = [e for e in store.get(chat_id, []) if now - e["ts"] < CONTEXT_WINDOW]
    store[chat_id] = items[-16:]
    return store[chat_id]


def _remember_slug(chat_id: int, slug: str, origin: tuple) -> None:
    _prune(_recent_slugs, chat_id).append({"ts": time.time(), "slug": slug, "origin": origin})


def _remember_context(chat_id: int, text: str, origin: tuple, used: str | None = None) -> None:
    _prune(_recent_context, chat_id).append(
        {"ts": time.time(), "text": text, "origin": origin, "used": used})


def _nearest_slug(chat_id: int, ctx_origin: tuple, max_distance: int = ORIGIN_ADJACENCY) -> str | None:
    """The recent download whose original post number is closest to the context's."""
    if ctx_origin[0] is None:
        return None
    best, best_d = None, None
    for e in _prune(_recent_slugs, chat_id):
        so = e["origin"]
        if so[0] != ctx_origin[0]:
            continue
        d = abs(so[1] - ctx_origin[1])
        if d <= max_distance and (best_d is None or d < best_d):
            best, best_d = e["slug"], d
    return best


def assign_context(chat_id: int, slug: str, origin: tuple) -> list[str]:
    """Context messages belonging to `slug`, decided when the download is done —
    each origin-tagged context goes only to the file with the NEAREST original
    post number (posts 5072/5073 are one comic; 5076/5077 are another).
    Origin-less messages fall back to the time window."""
    out = []
    for e in _prune(_recent_context, chat_id):
        if e["used"] and e["used"] != slug:
            continue
        co = e["origin"]
        if co[0] is None or origin[0] is None:
            if not e["used"]:
                e["used"] = slug
                out.append(e["text"])
            continue
        if co[0] != origin[0] or abs(co[1] - origin[1]) > ORIGIN_ADJACENCY:
            continue
        if _nearest_slug(chat_id, co) == slug:
            e["used"] = slug
            out.append(e["text"])
    return out

# Match greedily up to whitespace/angle-brackets/double-quote only. Apostrophes
# and parentheses are LEGAL url characters and routinely appear in comic-release
# links (e.g. .../X-Men_'97_..._(2026)_(Digital).cbz.html) — excluding them here
# truncated such urls mid-path and handed JDownloader a dead link. Trailing
# punctuation and unbalanced brackets are trimmed afterwards by _clean_url.
URL_RE = re.compile(r"https?://[^\s<>\"]+")
# Links that are Telegram-internal (channel invites, post references) — never downloadable.
SKIP_HOSTS = ("t.me/", "telegram.me/", "telegram.dog/")


def _clean_url(u: str) -> str:
    """Trim trailing punctuation/quotes and unbalanced closing brackets that come
    from prose wrapping (e.g. "(see https://x/y)." or 'https://x/y'), while
    keeping brackets that are balanced inside the url itself (Wikipedia-style)."""
    u = u.rstrip(".,;:!?'\"")
    for open_c, close_c in (("(", ")"), ("[", "]")):
        while u.endswith(close_c) and u.count(open_c) < u.count(close_c):
            u = u[:-1]
    return u

HELP = (
    "Forward me a message from a comics channel and I'll take it from there:\n"
    "• If it has a .cbz/.cbr attached, I download it directly.\n"
    "• If it has download links, I hand them to JDownloader.\n"
    "Either way the file gets identified against ComicVine, tagged, "
    "filed into the library, and Komga is told to rescan. "
    "If I'm not sure which comic it is, I'll ask you with buttons — and I "
    "remember your answer for the rest of that series.\n\n"
    "Commands:\n"
    "/series — list remembered series→volume answers\n"
    "/forget <series name> — drop a remembered answer\n"
    "/rescan_failed — file anything in failed/ that you've since tagged\n\n"
    "Manual tagging: tag a failed file in place with ComicTagger and send "
    "/rescan_failed, or drop any tagged comic into downloads/COMICS/tagged/ — "
    "either way I file it from your tags, no questions."
)


def make_slug(base: str, chat_id: int, msg_id: int) -> str:
    base = re.sub(r"[^\w '.\-&]+", " ", base or "", flags=re.UNICODE)
    base = re.sub(r"\s{2,}", " ", base).strip()[:60] or "comic"
    return f"{base} [{abs(chat_id) % 100000}-{msg_id}]"


def extract_urls(message) -> list[str]:
    """URLs from the raw text plus hyperlinked entities (hidden URLs)."""
    urls: list[str] = URL_RE.findall(message.message or "")
    try:
        for ent, _txt in message.get_entities_text() or []:
            url = getattr(ent, "url", None)
            if url:
                urls.append(url)
    except (TypeError, ValueError):
        pass
    seen, out = set(), []
    for u in urls:
        u = _clean_url(u)
        if any(h in u for h in SKIP_HOSTS):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _encode_for_crawljob(url: str) -> str:
    """Percent-encode characters a link parser might treat as delimiters
    (apostrophes, parentheses, brackets, spaces) so JDownloader's own crawler
    can't re-truncate the URL the way our extractor used to — e.g. florenfile
    links whose filename slug contains "'97" or "(2026)". URL structure and any
    existing %XX escapes are preserved; the file host decodes these back."""
    return quote(url, safe="%:/?#@!$&*+,;=~")


def write_crawljob(slug: str, urls: list[str]) -> None:
    job = [{
        "text": "\n".join(_encode_for_crawljob(u) for u in urls),
        "packageName": slug,
        "downloadFolder": f"{config.JD_DOWNLOAD_ROOT}/telegram/{slug}",
        "autoStart": "TRUE",
        "autoConfirm": "TRUE",
        "enabled": "TRUE",
        "extractAfterDownload": "TRUE",
    }]
    path = config.FOLDERWATCH / f"{slug}.crawljob"
    tmp = path.with_suffix(".crawljob.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1))
    tmp.rename(path)


async def handle_message(event) -> None:
    msg = event.message
    text = msg.message or ""

    cmd = text.strip()
    if cmd.startswith("/start") or cmd.startswith("/help"):
        await event.reply(HELP)
        return
    if cmd.startswith("/series"):
        entries = hints.map_all()
        if not entries:
            await event.reply("No remembered series yet.")
        else:
            lines = [f"• {k} → {v['label']}" for k, v in sorted(entries.items())]
            await event.reply("Remembered series answers:\n" + "\n".join(lines)[:3500])
        return
    if cmd.startswith("/rescan"):
        from . import processor
        await processor.rescan_failed(event.client, event)
        return
    if cmd.startswith("/forget"):
        name = cmd[len("/forget"):].strip()
        if not name:
            await event.reply("Usage: /forget <series name> (see /series for the list)")
        elif hints.map_delete(name):
            await event.reply(f"🗑 Forgot “{name}”.")
        else:
            await event.reply(f"“{name}” wasn't in the list — see /series.")
        return

    name = msg.file.name if msg.file else None
    # Trust the filename's extension first: channels often upload comics as
    # application/octet-stream, which makes Telethon's file.ext report ".bin".
    if name and "." in name:
        ext = "." + name.rsplit(".", 1)[1].lower()
    else:
        ext = (msg.file.ext or "").lower() if msg.file else ""

    origin = origin_of(msg)

    if msg.file and (ext in config.ARCHIVE_EXTS or ext in config.OTHER_EXTS):
        name = name or f"comic{ext}"
        slug = make_slug(name.rsplit(".", 1)[0], event.chat_id, msg.id)
        hints.save(slug, text, event.chat_id, msg.id)
        _remember_slug(event.chat_id, slug, origin)
        dest_dir = config.TELEGRAM_INBOX / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        status = await event.reply(f"⬇️ Downloading **{name}** …")
        tmp = dest_dir / (name + ".part")
        try:
            await msg.download_media(file=str(tmp))
        except Exception as e:  # noqa: BLE001 - report any failure to the user
            log.exception("download failed for %s", slug)
            tmp.unlink(missing_ok=True)
            await status.edit(f"❌ Download failed: {e}")
            return
        # Attach context only now, when the whole bundle has had time to arrive:
        # each context message goes to the nearest original post, not to
        # whichever download happened to exist first.
        context = assign_context(event.chat_id, slug, origin)
        if context:
            hints.append_text(slug, "\n".join(context))
        tmp.rename(dest_dir / name)
        log.info("downloaded %s (%s)", slug, name)
        await status.edit(f"✅ Downloaded **{name}** — identifying, I'll report back.")
        return

    urls = extract_urls(msg)
    if urls:
        first_line = next((ln for ln in text.splitlines() if ln.strip()), name or "comic")
        slug = make_slug(re.sub(r"https?://\S+", "", first_line), event.chat_id, msg.id)
        _remember_slug(event.chat_id, slug, origin)
        context = assign_context(event.chat_id, slug, origin)
        hints.save(slug, (text + "\n" + "\n".join(context)).strip(), event.chat_id, msg.id)
        write_crawljob(slug, urls)
        log.info("crawljob %s (%d links)", slug, len(urls))
        await event.reply(
            f"📨 Sent {len(urls)} link(s) to JDownloader as **{slug}**.\n"
            "I'll identify and file the comic when the download finishes."
        )
        return

    # No file, no links — treat any text (e.g. a cover's caption or a summary
    # post) as context for a nearby download from the same chat.
    if text.strip():
        # Attach immediately only when the origin pins it right next to one
        # specific download (its own file may simply not have arrived yet —
        # a farther match now could belong to a comic still being forwarded).
        target = _nearest_slug(event.chat_id, origin, max_distance=2)
        if target and hints.append_text(target, text):
            _remember_context(event.chat_id, text, origin, used=target)
            log.info("context attached to %s", target)
            await event.reply(f"📝 Noted — added as extra info for **{target}**.")
        else:
            _remember_context(event.chat_id, text, origin)
            if event.is_private:
                await event.reply(
                    "📝 Noted — I'll use this as extra info for the next comic "
                    "you forward (within a few minutes)."
                )
        return

    if msg.photo:
        # A bare cover image (no caption) — nothing to extract, nothing to complain about.
        return

    if event.is_private:
        await event.reply("No comic file or downloadable links found in that message.\n\n" + HELP)
