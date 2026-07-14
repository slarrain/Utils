#!/usr/bin/env python3
"""Read the last N messages from Santiago's Telegram chat with the comics bot.

Read-only debugging helper. Copies the live Telethon *user* session to a temp
file (so it never locks the running titularia monitor), connects, finds the
ComicsDownloader bot chat, prints the most recent messages, then cleans up.
It never sends anything.

Invoke through the ``readbot`` wrapper, which picks a Python that has telethon:

    scripts/readbot          # last 10 messages
    scripts/readbot 2        # last 2
"""
import asyncio
import pathlib
import shutil
import sys
import tempfile

HOME = pathlib.Path.home()
ENV = HOME / "github/titularia/extraccion_texto/.env"
LIVE_SESSION = HOME / "github/titularia/extraccion_texto/data/.telegram_monitor_session.session"


def load_creds():
    api_id = api_hash = None
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("TELEGRAM_API_ID="):
            api_id = int(line.split("=", 1)[1].strip())
        elif line.startswith("TELEGRAM_API_HASH="):
            api_hash = line.split("=", 1)[1].strip()
    if not api_id or not api_hash:
        sys.exit(f"Could not read TELEGRAM_API_ID/HASH from {ENV}")
    return api_id, api_hash


async def main(n):
    from telethon import TelegramClient

    api_id, api_hash = load_creds()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tgprobe_"))
    session = tmp / "probe.session"
    shutil.copy(LIVE_SESSION, session)
    client = TelegramClient(str(session.with_suffix("")), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            sys.exit("Copied session is not authorized")
        target = None
        async for d in client.iter_dialogs():
            if getattr(d.entity, "bot", False) and "comic" in (d.name or "").lower():
                target = d
                break
        if target is None:
            sys.exit("Comics bot chat not found in dialogs")
        print(f"# {target.name} — last {n} message(s)\n")
        msgs = await client.get_messages(target.entity, limit=n)
        for m in reversed(msgs):
            who = "ME " if m.out else "BOT"
            ts = m.date.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] {who} (id {m.id})")
            if m.text:
                print(m.text)
            if m.media:
                print(f"  <media: {type(m.media).__name__}>")
            for row in (m.buttons or []):
                print("  [buttons] " + " | ".join(b.text for b in row))
            print("-" * 64)
    finally:
        await client.disconnect()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(n))
