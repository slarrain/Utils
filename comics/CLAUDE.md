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

- **ComicVine** — rate-limited (HTTP 420). `identify._cv_get` is the single choke point and
  now self-throttles (~1 req/s via `_CV_MIN_INTERVAL`) and retries 420 with escalating
  back-off; without this a large batch (a whole Dago run forwarded at once) trips the limit
  and every lookup after it fails, dumping issues into `failed/`. Runs inside
  `asyncio.to_thread` so the blocking sleeps don't stall the bot's event loop. `tagkit`
  wraps the same function for the `/tag` path (so batch tagging is throttled there too).
- **Komga** — `filer.komga_scan()` (library id autodetected; `0FSAPZZ0CBEAX` = "Comics").
  Crossover **read lists** (story arcs, à la Mylar) and the **slow bulk-reindex** gotcha
  (`analyzeDimensions`/`hashFiles` re-read every page over NFS) are documented in
  `docs/komga-readlists-and-bulk-reindex.md`.
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
For a comic that isn't on ComicVine, **read the metadata out of the archive** rather than
guessing: extract the cover (title/authors/publisher logo), the title/indicia page
(`© Publisher YYYY`, ISBN, dépôt légal), and the back cover (blurb + ISBN country prefix,
e.g. `978-84-` = Spanish edition) and `Read` them; internal page filenames often leak the
original-language title too. Details in the `/tag` skill's gotchas.

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
  extension crashed the UnRAR engine ("OpenResult is 13"). Formats: zip/rar/**7z** — 7z has
  no stdlib reader, so both paths shell out to `unar` (in the image). A **multi-comic `.7z`
  container** (a 7z of inner `.cbz`/`.cbr`) is exploded by `explode_container`; a 7z of loose
  page images is a single comic that `ensure_cbz` converts. (Before this, a `.7z` container
  fell through to `ensure_cbz` and died as "no images found inside".)
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
- **Not-on-ComicVine series auto-file** via `series_map.json`: `map_set` stores a ComicVine
  `volume_id`; `map_set_asis` stores an `{asis: {publisher, series, year, prefix}}` block so a
  series CV doesn't index (e.g. *Cuentos de Walt Disney*, Editorial Novaro) files every future
  issue with no prompt. Set via `/series set <series> | <publisher> | [year]`; fold a
  differently-named line (an "Extra"/annual sub-series) into an existing one with
  `/series merge <sub> into <series> | [prefix]` — the prefix (`Extra `) keeps its numbering
  from colliding with the main run. `processor.process_file` stamps these tags with
  `identify.write_basic_tags(..., overwrite=True)`, which overrides the uploader's embedded
  ComicInfo (fixing a wrong/typo'd Series) instead of filing under it. Add `| dated` to
  `/series set` for periodic specials numbered by date (Novaro's *Extra*/*Extraordinario*,
  *Especial Avestruz*): `identify.date_number` turns the filename's `…1954-12…` / `…Mayo 1959…`
  into `YYYY.MM` so they sort chronologically instead of reusing month/day fragments (which
  collided — two "Extra 5"). `merge` inherits the target's numbering mode.

## Conventions

- Library scheme: `Publisher/Series (Year)/Series N (Year).cbz` + `cvinfo` + `series.json`
  (Komga reads `series.json`); embedded `ComicInfo.xml` carries the tags.
- Match the surrounding code's comment density and idiom; comments explain *why*, not *what*.
- Commit only when asked; keep `deploy.secrets` out of git.
