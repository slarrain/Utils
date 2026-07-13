# CLAUDE.md — comics-bot

Telegram → Komga comic ingestion pipeline. User-facing setup/overview is in
`README.md`; this file is the working guide for making changes safely.

## Modules (`comicsbot/`)

| File | Role |
|---|---|
| `main.py` | Telethon bot: auth, owner, event wiring |
| `ingest.py` | Incoming messages → download attachments / route links to JDownloader |
| `processor.py` | Inbox watcher: identify → auto-file or ask with buttons; callbacks; `/rescan_failed` |
| `identify.py` | Archive normalization, ComicTagger wrapper, ComicVine API, caption parsing, edition selection |
| `filer.py` | Library filing (Mylar layout + `cvinfo`/`series.json` sidecars), Komga scan |
| `jd.py` | My.JDownloader API client (submit links + verify they appear) |
| `hints.py` | Per-slug message hints + remembered series→volume answers |
| `config.py` | Env-var config |

Flow: message → (attachment downloaded to `/inbox/telegram/<slug>/`) or (links → JD)
→ watcher converts to `.cbz`, tags via ComicTagger, files to
`/library/Publisher/Series (Year)/Series N (Year).cbz`, triggers a Komga scan.

## Paths & local access

Container mounts: `/data` = `/volume1/docker/comics-bot` (session/hints/pending),
`/inbox` = `/volume1/NAS/downloads/COMICS` (shared with JDownloader's `/output/COMICS`),
`/library` = `/volume1/NAS/comics`.

From this machine, `/volume1/NAS` is NFS-mounted at **`/mnt/nas`**, so the library is
`/mnt/nas/comics` and the inbox is `/mnt/nas/downloads/COMICS`. **`/data` is NOT
mounted** — hints/pending state need SSH/container access. Config lives in
`deploy.conf` (non-secret) and `deploy.secrets` (gitignored: CV key, Komga, MyJD,
Telegram).

## Deploy

`./deploy.sh` builds the image **from the working tree** (committed or not), ships it
over SSH, and restarts the container. It **requires an interactive terminal** — SSH
password + sudo password; there is no passwordless/key SSH to the NAS, so an agent
cannot deploy on its own. ComicTagger is pinned to `comictagger==1.6.0b11.dev0` (1.6
has no stable PyPI release yet; the exact pre-release pin is what pip accepts). PyICU
builds inside the image (the Dockerfile installs `pkg-config`/`libicu-dev`).

## External services

- **ComicVine** — rate-limited; keep to ~1 req/s and back off on HTTP 420. `identify._cv_get`
  is the single choke point (wrap it to throttle/cache when batch-processing).
- **Komga** — `filer.komga_scan()` (library id autodetected; `0FSAPZZ0CBEAX` = "Comics").
- **My.JDownloader** — links go via the API first (`jd.add_links`, same path as the UI's
  Add Links), `.crawljob` FolderWatch only as fallback; `confirm_in_jd` verifies they land.

## Manual tagging / recovery — the `/tag` skill

When comics fail auto-identification (they sit in `downloads/COMICS/failed/`) or need a
retag (library `Unknown/`), use the **`/tag` skill** (`.claude/skills/tag/`). It reuses
the bot's own `identify`/`filer` over NFS + the local ComicTagger AppImage, so it works
even when the container is unreachable. `tagkit.py` there is also the reference for the
"reuse comicsbot modules over NFS with env overrides" pattern (set `LIBRARY_DIR`,
`INBOX_DIR`, `COMICVINE_API_KEY`, `KOMGA_*` and import `comicsbot.identify`/`filer`).
Tag via ComicTagger `--id <issue_id>`, then `filer.file_comic`, then `komga_scan`.

## Gotchas & design decisions (hard-won — don't regress these)

- **Never feed the caption's year to ComicTagger's online search.** ComicTagger uses year
  as a *hard filter*, and the caption year is usually the original series year, not the CV
  edition's start-year (a `1997` on Thorgal returned "Found 0 series"). `_hints_to_m` omits
  year and `tag_file` passes `--no-use-year-when-identifying`.
- **Multi-edition series (Thorgal, Asterix, …) reuse the same cover art across languages,**
  so ComicTagger's cover-hash cannot tell editions apart → "Multiple good matches" or an
  arbitrary wrong-edition winner (a Spanish scan once auto-filed as the German Splitter
  edition). Pick the edition from the caption's **language** (`💬`) + issue **count** (`📂`)
  via the CV API — `identify.rank_volumes` / `pick_edition` — not the cover match. A
  publisher/language conflict (`processor._edition_conflict`) distrusts a wrong auto-match.
- **Sniff archive format from content, not extension** — a zip named `.cbr` (and vice-versa)
  is common. `explode_container` and `ensure_cbz` both content-sniff; dispatching on the
  extension crashed the UnRAR engine ("OpenResult is 13").
- **A cover PHOTO with a caption is context, not a download.** Its only link is the release
  group's credit link (blog/forum/Facebook); routing it to JDownloader made JD *scrape the
  web page*. `ingest.py` treats photo/image messages as context and never mines them for
  download links (plus a social/blog host skip-list).
- **Clean release-group noise from the filename before tagging** — `[2015 - 01]` cover-date
  prefixes and `@handle`/`[CRG]` tags make ComicTagger's parser give up ("Not enough info
  for a search"). `processor._clean_stem_for_tagging`.
- **ComicTagger 1.6 CLI** (in `identify._run_ct`): `--comicvine-key`, `--no-gui`, `-s`,
  `--tags-write CR`, `-m` is **YAML** (`series: 'x', issue: 'n'`), `--id`, `-1`. This differs
  from 1.5.x (`--cv-api-key -w -t CR`, `key=value` `-m`); the requirements pin and these
  flags must move together.
- **Comicverso captions are structured**: `📔` series, `🗞` publisher, `💬` language,
  `📂` count, `🗓` year — parsed by `identify._parse_structured` / `parse_hints`.
- **"Your tags are law"**: a human-tagged file (drop in `downloads/COMICS/tagged/`, or tag
  in place + `/rescan_failed`) is filed from its embedded tags with no re-identification —
  so tag typos are filed faithfully too.

## Conventions

- Library scheme: `Publisher/Series (Year)/Series N (Year).cbz` + `cvinfo` + `series.json`
  (Komga reads `series.json`); embedded `ComicInfo.xml` carries the tags.
- Match the surrounding code's comment density and idiom; comments explain *why*, not *what*.
- Commit only when asked; keep `deploy.secrets` out of git.
