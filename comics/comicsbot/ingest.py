"""Handle incoming Telegram messages: download attachments, route links to JDownloader."""
import asyncio
import json
import logging
import re
import time
from urllib.parse import quote

from . import config, hints, jd

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
# Links that are never a comic download: Telegram-internal (channel invites,
# post references) and the social/blog/video homes that comic channels cite as
# credits ("Únete a @Comicverso", "LadronCorps" → a blogspot page). JDownloader
# would happily *scrape those web pages* into junk (87 MB of blogspot assets for
# one Gargoyles cover), so they must never reach it.
SKIP_HOSTS = ("t.me/", "telegram.me/", "telegram.dog/",
              "facebook.com/", "fb.watch/", "instagram.com/", "twitter.com/",
              "x.com/", "youtube.com/", "youtu.be/", "blogspot.", "blogger.com")
# A forwarded comic post is often a cover PHOTO + caption in one message and the
# actual archive in a sibling message. The caption's only link is a credit link,
# so a cover image must be treated as context, never mined for download links.
COVER_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


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
    "/series — list remembered series answers\n"
    "/series set <series> | <publisher> | [year] — auto-file a series that "
    "isn't on ComicVine (every future issue, no prompt)\n"
    "/series merge <sub> into <series> | [prefix] — fold a differently-named "
    "line into a set series (prefix keeps its numbers distinct)\n"
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


async def send_to_jd(slug: str, urls: list[str]) -> str:
    """Hand urls to JDownloader, API first (the reliable path — same as the UI's
    Add Links dialog), crawljob file as fallback. Returns which route was used."""
    encoded = [_encode_for_crawljob(u) for u in urls]
    try:
        await asyncio.to_thread(
            jd.add_links, slug, encoded, f"{config.JD_DOWNLOAD_ROOT}/telegram/{slug}")
        return "api"
    except Exception:  # noqa: BLE001 - any API failure falls back to FolderWatch
        log.exception("myjd add_links failed for %s; falling back to crawljob", slug)
        write_crawljob(slug, urls)
        return "crawljob"


async def confirm_in_jd(slug: str, urls: list[str], status_msg) -> None:
    """Watch JD for up to ~2 minutes and report what actually happened —
    FolderWatch has silently dropped links before (florenfile), so absence of
    errors is not success. Edits the bot's reply with the verified state."""
    state = None
    for delay in (10, 15, 20, 25, 25, 30):
        await asyncio.sleep(delay)
        try:
            state = await asyncio.to_thread(jd.find_package, slug)
        except Exception:  # noqa: BLE001 - can't verify without the API
            log.exception("myjd find_package failed for %s", slug)
            await status_msg.edit(
                f"📨 Sent {len(urls)} link(s) to JDownloader as **{slug}** — "
                "couldn't verify they were accepted (My.JDownloader API unreachable); "
                "worth a glance at the JD web UI.")
            return
        if state and state["where"] == "downloads":
            break
    if state:
        mb = state["bytes"] / 1e6
        size = f", {mb:,.1f} MB" if mb else ""
        await status_msg.edit(
            f"📥 JDownloader queued **{slug}** "
            f"({state['status']}{size}).\n"
            "I'll identify and file the comic when the download finishes.")
    else:
        links = "\n".join(urls)
        await status_msg.edit(
            f"⚠️ JDownloader silently dropped the links for **{slug}** — "
            f"please add them manually (JD web UI → Add Links):\n{links}")


async def handle_message(event) -> None:
    msg = event.message
    text = msg.message or ""

    cmd = text.strip()
    if cmd.startswith("/start") or cmd.startswith("/help"):
        await event.reply(HELP)
        return
    if cmd.startswith("/series"):
        rest = cmd[len("/series"):].strip()
        if rest[:3].lower() == "set":
            parts = [p.strip() for p in rest[3:].split("|")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                await event.reply(
                    "Usage: `/series set <series> | <publisher> | [year] | [dated]`\n"
                    "e.g. `/series set Cuentos de Walt Disney | Editorial Novaro | 1949`\n"
                    "Add `| dated` for specials numbered by date (→ YYYY.MM):\n"
                    "`/series set Cuentos de Walt Disney Extra | Editorial Novaro | 1953 | dated`\n\n"
                    "Files every future issue of that (not-on-ComicVine) series "
                    "automatically, no prompt. Undo with `/forget <series>`.")
                return
            series_name, publisher = parts[0], parts[1]
            extra = [p for p in parts[2:] if p]
            _DATED = ("dated", "date", "por fecha")
            dated = any(x.lower() in _DATED for x in extra)
            year = next((x for x in extra if x.lower() not in _DATED), None)
            hints.map_set_asis(series_name, publisher, series_name, year,
                               numbering=("date" if dated else "seq"))
            await event.reply(
                f"✅ Remembered **{series_name}** → file as-is under "
                f"*{publisher}*{f' ({year})' if year else ''}"
                f"{', numbered by date (YYYY.MM)' if dated else ''}.\n"
                "Future issues auto-file with no prompt.")
            return
        if rest[:5].lower() == "merge":
            m = re.match(r"(?is)^(.+?)\s+into\s+(.+)$", rest[5:].strip())
            if not m:
                await event.reply(
                    "Usage: `/series merge <sub-series> into <target series> | [number prefix]`\n"
                    "e.g. `/series merge Cuentos de Walt Disney Novaro Extra into "
                    "Cuentos de Walt Disney | Extra`\n\n"
                    "Folds a differently-named line into an already-`set` series. The "
                    "prefix keeps its numbering distinct (Extra 12), so it doesn't "
                    "collide with the main run.")
                return
            sub = m.group(1).strip()
            tparts = [p.strip() for p in m.group(2).split("|")]
            target, prefix = tparts[0], (tparts[1] if len(tparts) > 1 else "")
            tgt = hints.map_get(target)
            if not tgt or not tgt.get("asis"):
                await event.reply(
                    f"“{target}” isn't a remembered as-is series yet — set it first "
                    "with `/series set …`, then merge into it.")
                return
            if prefix and not prefix.endswith(" "):
                prefix += " "
            a = tgt["asis"]
            hints.map_set_asis(sub, a["publisher"], a["series"], a.get("year") or None,
                               None, prefix, a.get("numbering", "seq"))
            await event.reply(
                f"✅ Merged **{sub}** into **{a['series']}**"
                + (f" (numbered “{prefix.strip()} N”)" if prefix else "")
                + ". Future issues fold in automatically.")
            return
        entries = hints.map_all()
        if not entries:
            await event.reply("No remembered series yet. Teach one with "
                              "`/series set <series> | <publisher> | [year]`.")
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

    # A cover photo with a caption is context/attribution, not a download — its
    # only links are the channel's credit links (release-group blog/forum/
    # Facebook). Skip link extraction so the caption falls through to the
    # context path and enriches the sibling comic's hints instead of feeding
    # JDownloader a web page to scrape.
    is_cover = bool(msg.photo) or ext in COVER_EXTS
    urls = [] if is_cover else extract_urls(msg)
    if urls:
        first_line = next((ln for ln in text.splitlines() if ln.strip()), name or "comic")
        slug = make_slug(re.sub(r"https?://\S+", "", first_line), event.chat_id, msg.id)
        _remember_slug(event.chat_id, slug, origin)
        context = assign_context(event.chat_id, slug, origin)
        hints.save(slug, (text + "\n" + "\n".join(context)).strip(), event.chat_id, msg.id)
        route = await send_to_jd(slug, urls)
        log.info("sent to JD via %s: %s (%d links)", route, slug, len(urls))
        status = await event.reply(
            f"📨 Sent {len(urls)} link(s) to JDownloader as **{slug}** — "
            "verifying they were accepted…"
        )
        asyncio.create_task(confirm_in_jd(slug, urls, status))
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
