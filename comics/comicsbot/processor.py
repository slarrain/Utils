"""Inbox watcher: identify stable files, file them, or ask the owner via buttons."""
import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from telethon import Button

from . import config, filer, hints, identify

log = logging.getLogger("comicsbot.processor")

_sizes: dict[str, tuple[int, float]] = {}   # path -> (size, first_seen_stable)
_reported_pdf: set[str] = set()

SCAN_INTERVAL = 20
SETTLE_SECONDS = 30


def _slug_of(path: Path) -> str:
    try:
        return path.relative_to(config.TELEGRAM_INBOX).parts[0]
    except (ValueError, IndexError):
        return path.parent.name


async def _notify(client, hint: dict, text: str, buttons=None):
    chat = hint.get("chat_id")
    if chat is None:
        from .main import get_owner
        chat = get_owner()
    if not chat:
        log.warning("no chat to notify: %s", text)
        return None
    try:
        return await client.send_message(chat, text, buttons=buttons)
    except Exception:  # noqa: BLE001
        log.exception("notify failed")
        return None


def _is_stable(f: Path) -> bool:
    """True when the file stopped growing and no partial files sit next to it."""
    if any(p.suffix in (".part", ".tmp") for p in f.parent.iterdir()):
        return False
    try:
        size = f.stat().st_size
    except OSError:
        return False
    key = str(f)
    prev = _sizes.get(key)
    now = time.time()
    if prev and prev[0] == size:
        return now - prev[1] >= SETTLE_SECONDS
    _sizes[key] = (size, now)
    return False


async def loop(client) -> None:
    while True:
        try:
            await scan_once(client)
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("scan failed")
        await asyncio.sleep(SCAN_INTERVAL)


def _files_awaiting_answer() -> set[str]:
    """Files with an open button-question — don't re-process (and re-ask) them."""
    out = set()
    for p in config.PENDING.glob("*.json"):
        try:
            out.add(json.loads(p.read_text()).get("file", ""))
        except (json.JSONDecodeError, OSError):
            pass
    return out


async def scan_once(client) -> None:
    if not config.TELEGRAM_INBOX.is_dir():
        return
    awaiting = _files_awaiting_answer()
    for f in sorted(config.TELEGRAM_INBOX.rglob("*")):
        if str(f) in awaiting or str(f.with_suffix(".cbz")) in awaiting:
            continue
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in config.OTHER_EXTS and str(f) not in _reported_pdf:
            _reported_pdf.add(str(f))
            slug = _slug_of(f)
            await _notify(client, hints.load(slug),
                          f"⚠️ **{f.name}** is a {ext} — I only auto-tag comic archives. "
                          f"Left in `inbox/telegram/{slug}/` for manual handling.")
            continue
        if ext not in config.ARCHIVE_EXTS:
            continue
        if not _is_stable(f):
            continue
        _sizes.pop(str(f), None)
        await process_file(client, f)

    # Manually-tagged drop folder: file from embedded tags, never re-identify.
    for f in sorted(config.TAGGED.rglob("*")) if config.TAGGED.is_dir() else []:
        if not f.is_file() or f.suffix.lower() not in config.ARCHIVE_EXTS:
            continue
        if not _is_stable(f):
            continue
        _sizes.pop(str(f), None)
        await process_tagged(client, f)


async def rescan_failed(client, event) -> None:
    """/rescan_failed: file anything in failed/ that now carries manual tags."""
    files = [f for f in sorted(config.FAILED.rglob("*"))
             if f.is_file() and f.suffix.lower() in config.ARCHIVE_EXTS]
    if not files:
        await event.reply("failed/ is empty — nothing to rescan.")
        return
    status = await event.reply(f"🔎 Rescanning {len(files)} file(s) in failed/ …")
    filed, untagged = 0, []
    for f in files:
        try:
            cbz = await asyncio.to_thread(identify.ensure_cbz, f)
            tags = identify.read_tags(cbz)
        except Exception as e:  # noqa: BLE001
            untagged.append(f"{f.name} (unreadable: {e})")
            continue
        if not tags.get("Series"):
            untagged.append(cbz.name)
            continue
        parent = cbz.parent
        await _file_and_report(client, cbz, parent.name, {"chat_id": event.chat_id},
                               note="ℹ️ Filed from failed/ using its tags.")
        _cleanup_slug_dir(parent)
        filed += 1
    msg = f"Done — filed {filed}, {len(untagged)} still untagged in failed/."
    if untagged:
        msg += "\n" + "\n".join(f"• {n}" for n in untagged[:15])
    await status.edit(msg)


async def process_tagged(client, f: Path) -> None:
    slug = f.stem
    log.info("processing manually-tagged %s", f.name)
    try:
        cbz = await asyncio.to_thread(identify.ensure_cbz, f)
    except Exception as e:  # noqa: BLE001
        _park(f, slug)
        await _notify(client, {}, f"❌ **{f.name}** (tagged/): couldn't open archive ({e}). Moved to failed/.")
        return
    tags = identify.read_tags(cbz)
    if not tags.get("Series"):
        _park(cbz, slug)
        await _notify(client, {},
                      f"⚠️ **{cbz.name}** from tagged/ has no ComicRack (ComicInfo.xml) tags — "
                      "moved to failed/. Tag it with ComicTagger first, then drop it in tagged/ again.")
        return
    await _file_and_report(client, cbz, slug, {}, note="ℹ️ Filed from your manual tags.")


async def process_file(client, f: Path) -> None:
    slug = _slug_of(f)
    hint = hints.load(slug)
    log.info("processing %s (slug=%s)", f.name, slug)

    try:
        inner = await asyncio.to_thread(identify.explode_container, f)
    except Exception as e:  # noqa: BLE001
        log.exception("container check failed")
        _park(f, slug)
        await _notify(client, hint, f"❌ **{f.name}**: couldn't open archive ({e}). Moved to failed/.")
        return
    if inner:
        await _notify(client, hint,
                      f"📦 **{f.name}** contained {len(inner)} comic file(s) — processing each:\n"
                      + "\n".join(f"• {p.name}" for p in inner[:10]))
        return  # the scanner picks the extracted files up on its next pass

    try:
        cbz = await asyncio.to_thread(identify.ensure_cbz, f)
    except Exception as e:  # noqa: BLE001
        log.exception("archive conversion failed")
        _park(f.parent if f.parent != config.TELEGRAM_INBOX else f, slug)
        await _notify(client, hint, f"❌ **{f.name}**: couldn't open archive ({e}). Moved to failed/.")
        return

    hint_meta = identify.parse_hints(hint.get("text", ""))
    # The filename's own issue number beats one parsed from (possibly shared)
    # context text — "vol. 3" in a channel caption must not relabel every file.
    fn_issue = _issue_from_name(cbz.stem)
    if fn_issue:
        hint_meta["issue"] = fn_issue

    # A filename with no real words can't help ComicTagger — rebuild it from the hints.
    if hint_meta.get("series") and not _has_words(cbz.stem):
        new = f"{hint_meta['series']} {hint_meta.get('issue', '')} ({hint_meta.get('year', '')})"
        new = " ".join(new.split()).replace("()", "").strip()
        renamed = cbz.with_name(filer.sanitize(new) + ".cbz")
        if not renamed.exists():
            cbz.rename(renamed)
            cbz = renamed

    ok = await asyncio.to_thread(identify.tag_file, cbz, hint_meta)
    if ok:
        await _file_and_report(client, cbz, slug, hint)
        return

    guess = hint_meta.get("series") or _series_from_name(cbz.stem)

    # A previous button answer for this series? Apply it without asking.
    mapped = hints.map_get(guess) if guess else None
    if mapped:
        issue_no = re.sub(r"^0+(?=\d)", "", hint_meta.get("issue") or "1")
        try:
            issue = await asyncio.to_thread(identify.find_issue, mapped["volume_id"], issue_no)
        except Exception:  # noqa: BLE001
            issue = None
        if issue and await asyncio.to_thread(identify.tag_with_issue_id, cbz, issue["id"]):
            await _file_and_report(
                client, cbz, slug, hint,
                note=f"ℹ️ Auto-matched from your earlier answer: “{guess}” → {mapped['label']}.")
            return

    # Not matched on ComicVine, but many releases ship with embedded
    # ComicInfo.xml (e.g. Europe Comics) — good enough to file without asking.
    existing = identify.read_tags(cbz)
    if existing.get("Series"):
        log.info("using embedded metadata for %s", cbz.name)
        await _file_and_report(client, cbz, slug, hint,
                               note="ℹ️ Not on ComicVine — filed using the file's embedded metadata.")
        return

    # Ask the owner: which series is it?
    candidates = []
    if guess:
        try:
            candidates = await asyncio.to_thread(identify.search_volumes, guess)
        except Exception:  # noqa: BLE001
            log.exception("comicvine search failed")

    pid = uuid.uuid4().hex[:10]
    buttons = [
        [Button.inline(f"{c['name']} ({c['year']}) · {c['publisher']} · {c['issues']} iss."[:64],
                       data=f"p|{pid}|{c['id']}")]
        for c in candidates[:6]
    ]
    buttons.append([Button.inline("📁 File as-is (use message info, no ComicVine)",
                                  data=f"p|{pid}|asis")])
    buttons.append([Button.inline("❌ Skip (move to failed/)", data=f"p|{pid}|skip")])
    question = (f"❓ Couldn't auto-identify **{cbz.name}**"
                f"{' (issue #' + hint_meta['issue'] + ')' if hint_meta.get('issue') else ''}.")
    question += ("\nWhich series is it?" if candidates
                 else "\nNo ComicVine candidates found either — it may not be indexed there.")
    ask_msg = await _notify(client, hint, question, buttons=buttons)
    (config.PENDING / f"{pid}.json").write_text(json.dumps({
        "file": str(cbz),
        "slug": slug,
        "series": guess or "",
        "issue": hint_meta.get("issue") or "1",
        "chat_id": hint.get("chat_id"),
        "ask_chat": getattr(ask_msg, "chat_id", None),
        "ask_msg": getattr(ask_msg, "id", None),
    }))


async def _file_and_report(client, cbz: Path, slug: str, hint: dict, note: str = "") -> None:
    src_name = cbz.name
    tags = identify.read_tags(cbz)
    try:
        dest = await asyncio.to_thread(filer.file_comic, cbz, tags)
    except Exception as e:  # noqa: BLE001
        log.exception("filing failed")
        _park(cbz, slug)
        await _notify(client, hint, f"❌ Tagged **{cbz.name}** but filing failed ({e}). Moved to failed/.")
        return
    _cleanup_slug_dir(cbz.parent)
    hints.delete(slug)
    scanned = await asyncio.to_thread(filer.komga_scan)
    rel = dest.relative_to(config.LIBRARY)
    num = tags.get("Number")
    title = tags.get("Series", "?") + (f" #{num}" if num else "") + f" ({tags.get('Year', '?')})"
    await _notify(
        client, hint,
        f"✅ **{title}**\n`{src_name}` → `{rel}`"
        + ("\n📚 Komga rescan triggered." if scanned else "")
        + (f"\n{note}" if note else ""),
    )


async def handle_callback(event) -> None:
    try:
        kind, pid, choice = event.data.decode().split("|", 2)
    except ValueError:
        await event.answer()
        return
    if kind != "p":
        await event.answer()
        return
    pending_path = config.PENDING / f"{pid}.json"
    if not pending_path.is_file():
        await event.answer("Already handled.")
        return
    pending = json.loads(pending_path.read_text())
    cbz = Path(pending["file"])
    slug = pending["slug"]
    hint = hints.load(slug) or {"chat_id": pending.get("chat_id")}

    if choice == "skip":
        if cbz.exists():
            _park(cbz, slug)
        pending_path.unlink(missing_ok=True)
        await event.edit(f"⏭ **{cbz.name}**: skipped — moved to failed/.")
        return

    if not cbz.exists():
        pending_path.unlink(missing_ok=True)
        await event.edit("⚠️ File no longer exists.")
        return

    if choice == "asis":
        await event.answer("Filing…")
        pending_path.unlink(missing_ok=True)
        text = hint.get("text", "")
        meta = identify.parse_hints(text)
        fname_meta = identify.parse_hints(cbz.stem.replace("_", " "))
        meta.setdefault("series", _series_from_name(cbz.stem) or cbz.stem)
        meta["issue"] = meta.get("issue") or pending.get("issue") or ""
        meta.setdefault("year", fname_meta.get("year"))
        meta["publisher"] = filer.guess_publisher(text)
        meta["summary"] = text[:1500] or None
        try:
            await asyncio.to_thread(identify.write_basic_tags, cbz, meta)
        except Exception as e:  # noqa: BLE001
            log.exception("write_basic_tags failed")
            await event.edit(f"❌ Couldn't write tags: {e}")
            return
        await event.edit(f"📁 **{cbz.name}**: filing with message info…")
        await _file_and_report(event.client, cbz, slug, hint)
        return

    await event.answer("Tagging…")
    volume_id = int(choice)
    issue_number = re.sub(r"^0+(?=\d)", "", pending.get("issue", "1"))
    try:
        issue = await asyncio.to_thread(identify.find_issue, volume_id, issue_number)
    except Exception as e:  # noqa: BLE001
        await event.edit(f"❌ ComicVine lookup failed: {e}")
        return
    if issue is None:
        # Keep the pending question open (deleting it would make the scanner
        # re-ask in a loop) and offer the remaining ways out.
        await event.edit(
            f"❌ **{cbz.name}**: issue #{issue_number} isn't in that volume on "
            "ComicVine (the volume may be incompletely indexed). What should I do?",
            buttons=[
                [Button.inline("📁 File as-is (use message info)", data=f"p|{pid}|asis")],
                [Button.inline("❌ Skip (move to failed/)", data=f"p|{pid}|skip")],
            ])
        return
    ok = await asyncio.to_thread(identify.tag_with_issue_id, cbz, issue["id"])
    pending_path.unlink(missing_ok=True)
    if not ok:
        _park(cbz, slug)
        await event.edit(f"❌ **{cbz.name}**: tagging with the chosen issue failed — "
                         "moved to failed/.")
        return
    await event.edit(f"✅ **{cbz.name}**: tagged as issue #{issue['issue_number']} — filing…")

    # Remember the answer for this series and apply it to waiting siblings
    # (and to any future forwards of the same series).
    label = str(volume_id)
    try:
        vi = await asyncio.to_thread(identify.volume_info, volume_id)
        label = f"{vi.get('name')} ({vi.get('start_year')})"
    except Exception:  # noqa: BLE001
        pass
    series = pending.get("series") or ""
    if series:
        hints.map_set(series, volume_id, label)

    await _file_and_report(event.client, cbz, slug, hint)
    if series:
        await _resolve_siblings(event.client, series, volume_id, label)


async def _resolve_siblings(client, series: str, volume_id: int, label: str) -> None:
    """Apply a just-answered series→volume mapping to other pending questions."""
    key = hints.series_key(series)
    for p in sorted(config.PENDING.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if hints.series_key(d.get("series") or "") != key:
            continue
        f = Path(d.get("file", ""))
        if not f.exists():
            p.unlink(missing_ok=True)
            continue
        issue_no = re.sub(r"^0+(?=\d)", "", d.get("issue") or "1")
        try:
            issue = await asyncio.to_thread(identify.find_issue, volume_id, issue_no)
        except Exception:  # noqa: BLE001
            continue
        if not issue or not await asyncio.to_thread(identify.tag_with_issue_id, f, issue["id"]):
            continue
        p.unlink(missing_ok=True)
        if d.get("ask_chat") and d.get("ask_msg"):
            try:
                await client.edit_message(
                    d["ask_chat"], d["ask_msg"],
                    f"✅ **{f.name}**: resolved by your answer — {label}, issue #{issue['issue_number']}.")
            except Exception:  # noqa: BLE001
                pass
        h = hints.load(d.get("slug", "")) or {"chat_id": d.get("chat_id")}
        await _file_and_report(client, f, d.get("slug", ""), h)


# --------------------------------------------------------------------------- #
def _park(path: Path, slug: str) -> None:
    dest = config.FAILED / slug
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest / path.name)
    if path.parent != config.TELEGRAM_INBOX:
        _cleanup_slug_dir(path.parent)


def _cleanup_slug_dir(d: Path) -> None:
    try:
        if (d not in (config.TELEGRAM_INBOX, config.TAGGED, config.FAILED)
                and d.is_dir() and not any(d.iterdir())):
            d.rmdir()
    except OSError:
        pass


def _has_words(stem: str) -> bool:
    return len(re.findall(r"[A-Za-z]", stem)) >= 4


def _series_from_name(stem: str):
    stem = identify.normalize_numbering(stem)
    s = re.split(r"#|\d{3,}|\(", stem)[0]
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s+\d{1,2}\s*$", "", s).strip(" -")
    return s if len(s) >= 3 else None


def _issue_from_name(stem: str):
    stem = identify.normalize_numbering(stem)
    m = re.search(r"#\s*(\d+(?:\.\d+)?)", stem)
    if m:
        return m.group(1)
    # Last standalone 1-4 digit number that isn't a year ("Hermelinda 0225 ... 2026" -> 0225)
    nums = [n for n in re.findall(r"(?<![\w.])(\d{1,4})(?![\w.])", stem)
            if not re.fullmatch(r"(?:19|20)\d{2}", n)]
    return nums[-1] if nums else None
