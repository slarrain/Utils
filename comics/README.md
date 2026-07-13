# comics-bot

Telegram → NAS comic ingestion pipeline. Forward a message from any comics
channel to your bot and the comic ends up identified, tagged, and readable in
Komga a couple of minutes later.

```
Telegram message ──► comics-bot (Telethon)
    │ attachment (.cbz/.cbr)          │ download links
    ▼                                 ▼
 downloads directly            My.JDownloader API  (.crawljob fallback)
    └──────────────┬──────────────────┘
                   ▼
        /inbox/telegram/<slug>/   (= NAS /volume1/NAS/downloads/COMICS/telegram)
                   ▼
   ComicTagger auto-identify (filename + message text + cover-image hash vs ComicVine)
     │ confident                        │ unsure
     ▼                                  ▼
 tag ComicInfo.xml            Telegram asks with candidate buttons
     ▼
 /library/Publisher/Series (Year)/Series N (Year).cbz  (+ cvinfo, series.json)
     ▼
 Komga library rescan via API → readable on the tablet
```

## Components

| File | Role |
|---|---|
| `comicsbot/main.py` | Telethon bot, authorization, wiring |
| `comicsbot/ingest.py` | Incoming messages: download attachments, write crawljobs |
| `comicsbot/processor.py` | Inbox watcher, identify/ask loop, callback buttons |
| `comicsbot/identify.py` | CBR→CBZ conversion, ComicTagger wrapper, ComicVine API |
| `comicsbot/filer.py` | Library filing (Mylar-style layout + sidecars), Komga scan |

## One-time setup

1. **Create the bot**: talk to `@BotFather` in Telegram → `/newbot` → pick a
   name/username → copy the token into `deploy.secrets` (`TELEGRAM_BOT_TOKEN`).
2. **Credentials**: `cp deploy.secrets.example deploy.secrets` and fill in
   (Telegram api_id/api_hash from https://my.telegram.org, ComicVine key,
   Komga login).
3. **JDownloader** (for hoster links): the bot submits links via the
   My.JDownloader API — set `MYJD_EMAIL`/`MYJD_PASSWORD` in `deploy.secrets`. As
   a fallback it writes `.crawljob` files, so also enable **FolderWatch** (JD
   Settings → Extension Modules) pointed at `/output/COMICS/folderwatch`. Direct
   Telegram attachments need neither.
4. **Deploy**: `./deploy.sh` (builds locally, ships to the NAS over SSH,
   (re)starts the container — same pattern as comidas_campo).
5. In Telegram, send `/start` to your bot — the first user to do so becomes
   the owner (or pin it beforehand with `TELEGRAM_OWNER_ID`).

## Daily use

Forward any message from a comics channel to the bot (or into a
group/channel where the bot is admin). It replies with progress and either
files the comic automatically or asks you which series it is with buttons.

When the bot asks with buttons, your pick is remembered for the rest of that
series (`/series` lists them, `/forget <name>` drops one).

Unidentifiable files are parked in `/inbox/failed/<slug>/`. To tag them later,
run the **`/tag`** skill (`.claude/skills/tag/`): it tags everything in `failed/`
(or a named series in the library's `Unknown/`), confirming the ComicVine
edition once per series, and files them — reusing the pipeline over NFS, so it
works even if the container is down.

## Paths (as mounted in the container)

- `/data` → `/volume1/docker/comics-bot/data` — bot session, hints, pending state
- `/inbox` → `/volume1/NAS/downloads/COMICS` — shared with JDownloader's `/output/COMICS`
- `/library` → `/volume1/NAS/comics` — the library Komga/Codex/Mylar read
