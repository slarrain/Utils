# comics-bot

Telegram → NAS comic ingestion pipeline. Forward a message from any comics
channel to your bot and the comic ends up identified, tagged, and readable in
Komga a couple of minutes later.

```
Telegram message ──► comics-bot (Telethon)
    │ attachment (.cbz/.cbr)          │ download links
    ▼                                 ▼
 downloads directly            .crawljob → JDownloader FolderWatch
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
3. **JDownloader FolderWatch** (for hoster links): in JD Settings →
   Extension Modules → enable **FolderWatch**, and set its folder to
   `/output/COMICS/folderwatch`. Direct Telegram attachments work without this.
4. **Deploy**: `./deploy.sh` (builds locally, ships to the NAS over SSH,
   (re)starts the container — same pattern as comidas_campo).
5. In Telegram, send `/start` to your bot — the first user to do so becomes
   the owner (or pin it beforehand with `TELEGRAM_OWNER_ID`).

## Daily use

Forward any message from a comics channel to the bot (or into a
group/channel where the bot is admin). It replies with progress and either
files the comic automatically or asks you which series it is with buttons.

Unidentifiable files are parked in `/inbox/failed/<slug>/`.

## Paths (as mounted in the container)

- `/data` → `/volume1/docker/comics-bot/data` — bot session, hints, pending state
- `/inbox` → `/volume1/NAS/downloads/COMICS` — shared with JDownloader's `/output/COMICS`
- `/library` → `/volume1/NAS/comics` — the library Komga/Codex/Mylar read
