# florenfile links never appear in JDownloader when submitted via the bot

**Status:** UNRESOLVED (JDownloader-side). A separate, real bot bug that this
investigation uncovered — URL truncation — **is fixed** (see §8), pending deploy.

**Date of investigation:** 2026-07-12/13
**Component:** `comicsbot` (Telegram → JDownloader → ComicTagger → Komga pipeline)

---

## 1. TL;DR

The bot forwards download links from Telegram to JDownloader by writing
`.crawljob` files into a FolderWatch directory. For **florenfile.com** links,
JDownloader ingests the crawljob (the file is moved to `folderwatch/added/`) but
**no download ever appears in JDownloader's list** — not in Downloads, not
(as far as the user can see) anywhere. The same florenfile URL **added manually**
in JDownloader works fine. Other hosts submitted the same way by the bot
(terabox, via bit.ly short links) **do** appear. So:

- The file is **online** (verified: 81.8 MB and 46.2 MB).
- The crawljob mechanism **works** (verified: terabox crawljobs appear).
- The bot's URL was originally **truncated** (real bug, now fixed) — but even the
  corrected / percent-encoded / id-only URLs, submitted via crawljob, still
  produce nothing in JDownloader.

The mechanism of the JDownloader-side failure was **not determined**, because
JDownloader's crawler decisions and logs live inside the JD Docker container,
which is **not** on the NFS mount available to the investigator. Everything that
could be checked from the filesystem + the network was checked; see §6–§9.

---

## 2. What is fixed vs. open

| Item | Status |
| --- | --- |
| Bot truncated florenfile URLs at `'`/`(`/`)` (→ dead link → "offline") | **FIXED** in code (§8), **not yet deployed** (`./deploy.sh`) |
| florenfile links submitted via crawljob never appear in JDownloader | **OPEN** — JD-side, mechanism unknown |

---

## 3. The two files in question

X-Men '97 – Season Two, forwarded 2026-07-12 as two direct florenfile links.

| # | florenfile file-id | Size | Correct full URL |
| --- | --- | --- | --- |
| 001 | `r32vxttvxa69` | 81.8 MB | `https://florenfile.com/r32vxttvxa69/X-Men_'97_-_Season_Two_001_(2026)_(Digital).cbz.html` |
| 002 | `zorrqcexbls2` | 46.2 MB | `https://florenfile.com/zorrqcexbls2/X-Men_'97_-_Season_Two_002_(2026)_(Digital).cbz.html` |

Original Telegram messages (bot chat `ComicsDownloader`, id `8854935074`):
msg **36977** = the 001 URL, msg **36979** = the 002 URL (each message was *only*
the URL, on its own line).

---

## 4. Environment & how to inspect

- **NAS:** Synology `192.168.1.200`. `/volume1/NAS` exported via NFS, mounted
  locally at `/mnt/nas`.
- **JDownloader:** Docker on the NAS, web UI `http://192.168.1.200:5800`.
  Its config/logs are **inside the JD container** (likely
  `/volume1/docker/jdownloader/...` on the NAS) — **NOT** under `/mnt/nas`, so
  they were **not accessible** during this investigation.
- **Bot data (hints/session):** `/volume1/docker/comics-bot/` on the NAS — also
  not NFS-mounted, not accessible from the dev machine.
- **Shared download/inbox dir** (bot ↔ JDownloader), all three views of the same folder:
  - bot container: `/inbox` → `INBOX_DIR`
  - JD container: `/output/COMICS` (`JD_DOWNLOAD_ROOT`)
  - NAS path: `/volume1/NAS/downloads/COMICS`
  - **dev machine (NFS): `/mnt/nas/downloads/COMICS`** ← this is where everything
    below was inspected.
- **FolderWatch dir the bot writes crawljobs to:**
  `/mnt/nas/downloads/COMICS/folderwatch/` (JD moves processed jobs into
  `folderwatch/added/`).
- **Telegram inbox the bot's processor watches:**
  `/mnt/nas/downloads/COMICS/telegram/<slug>/`.
- **Komga:** `http://192.168.1.200:8341`, library id `0FSAPZZ0CBEAX`.
- **Reading the bot's Telegram chat (read-only):** copy the user's Telethon
  session and connect. `api_id=39284098`, `api_hash` from
  `~/github/titularia/extraccion_texto/.env` (`TELEGRAM_API_HASH`), session from
  `~/github/titularia/extraccion_texto/data/.telegram_monitor_session.session`.
  A Python venv with telethon + requests is at `~/github/titularia/.venv/`.
- **ComicVine / Komga creds:** `~/github/Utils/comics/deploy.secrets`.

---

## 5. Timeline of crawljob attempts (all for file 002 unless noted)

All of these `.crawljob` files were **consumed by JD** (moved to
`folderwatch/added/`), confirming JD's FolderWatch imported them. None produced a
visible entry in JDownloader.

| When | Package name | URL in crawljob | Result |
| --- | --- | --- | --- |
| 18:30 | `comic [77607-254]` (001) | `…/r32vxttvxa69/X-Men_` (**truncated** by bot bug) | absent |
| 18:31 | `comic [77607-256]` (002) | `…/zorrqcexbls2/X-Men_` (**truncated**) | absent |
| 21:15 | `comic [77607-254].1` (001) | full correct URL | absent |
| 21:15 | `comic [77607-256].1` (002) | full correct URL | absent |
| 22:48 | `comic 256 enctest` (002) | percent-encoded full URL | absent |
| 22:58 | `comic 256 idtest` (002) | `https://florenfile.com/zorrqcexbls2` (id-only) | absent |
| (manual) | 001, pasted by user in JD UI | full correct URL | **APPEARS** (waiting on limit) |

Meanwhile terabox crawljobs written by the bot **do** appear in JD.

---

## 6. VERIFIED facts (directly observed)

Each of these was checked by running a command / fetching a page / reading a file.

1. **Original Telegram messages contained the full, correct florenfile URLs.**
   Read via Telethon from the bot chat (msgs 36977/36979).
2. **The bot truncated them.** The crawljobs written at 18:30/18:31 contained
   `https://florenfile.com/<id>/X-Men_` — cut at the apostrophe in `X-Men_'97`.
   Cause: `URL_RE` excluded `'`, `)`, `]`. (Read the crawljob files.)
3. **The files are online.** `curl` of the full URLs returns florenfile download
   pages titled *"Download …X-Men '97 Season Two 00X…"* with **Size: 81.8 MB**
   (001) and **Size: 46.2 MB** (002), plus the XFileSharing `op=download1` form.
4. **A truncated / wrong-slug URL returns florenfile's not-found page**
   (`…/<id>/X-Men_` → 9937-byte "Florenfile.com - Secure Cloud Storage" page,
   no download form). So truncation → "offline".
5. **florenfile accepts all intact URL forms:** id-only
   (`/<id>`), percent-encoded full, and raw full (with `'`/`(`/`)`) — all return
   the same download page. Only a *wrong/truncated slug* 404s.
6. **florenfile free tier is rate-limited, not captcha-walled.** Walking the
   XFileSharing flow (POST `op=download1`) returns a page whose text says:
   *"You have to wait 21 hours, 43 minutes, 21 seconds till next download —
   Download files instantly with Premium-account."* Markers present:
   `method_free`, `download2`, `countdown`, `wait`, `premium`. **No**
   `recaptcha` / `hcaptcha` / `turnstile` / `data-sitekey` markers were found.
   The `op=download2` step returns a `rand` token (e.g. `sp45lb442g5am5pcrylhfs7rlqwtwd`).
7. **JD imported every crawljob.** Each `.crawljob` was moved to
   `folderwatch/added/` (verified by listing that dir).
8. **The working (terabox) crawljobs are structurally identical to the failing
   (florenfile) ones** — same JSON fields, same `autoStart/autoConfirm/enabled/
   extractAfterDownload=TRUE`. The **only** difference is the `text` URL. The
   working ones contain **bit.ly short links** (`https://bit.ly/4nL7xCx`,
   `https://bit.ly/4bDfgxk`) which JD follows via redirect to terabox.
9. **User-observed in the JD UI** (from screenshots; treated as reliable
   observation, not something the investigator could see directly):
   - Manually-added 001 shows: florenfile hoster, 81.8 MiB, status
     *"Download limit reached or wait until next download can be started"*, ETA ~20h.
   - Bot's florenfile jobs (254/256/enctest/idtest): **not present**.
   - Terabox jobs (bit.ly): present, status *"Skipped - Account is missing"*.
     ("Account is missing" is the **terabox** entries, NOT florenfile.)

---

## 7. Explanations RULED OUT (by the evidence above)

- ❌ *"The file is offline."* — No; 81.8/46.2 MB, verified online (§6.3).
- ❌ *"It's the bot's URL truncation."* — That was the **original** cause and is a
  real bug (fixed, §8), but corrected/encoded/id-only crawljobs still fail (§5).
- ❌ *"JDownloader has no florenfile plugin / doesn't support the host."* —
  DISPROVEN by the manual add appearing with correct host + size (§6.9). *(This
  was an incorrect inference stated too confidently earlier in the investigation;
  the screenshot corrected it.)*
- ❌ *"The crawljob path is broken."* — DISPROVEN; terabox crawljobs work (§6.8).
- ❌ *"JD's own parser truncates the special chars."* — Weakened: the
  percent-encoded URL (no special chars at all) still didn't appear (§5).
- ❌ *"It's the `.html` page being crawled as a webpage."* — Weakened: the id-only
  URL (`/<id>`, no `.html`, no slug) still didn't appear (§5). *(Caveat: id-only
  shares the same file-id as earlier attempts, so this does not rule out dedup —
  see §8-hyp.)*

---

## 8-hyp. OPEN hypotheses (UNVERIFIED — need JD internals to test)

Listed as hypotheses, not conclusions. None confirmed.

1. **JD dedup on the florenfile file-id.** Earlier (even truncated/failed)
   attempts may have registered file-ids `r32vxttvxa69` / `zorrqcexbls2` in JD's
   LinkGrabber or download history, so later crawljob adds of the same id are
   silently discarded. *Tension:* the manual 001 add appeared despite a prior
   truncated 001 crawljob — but perhaps the truncated (not-found) link never
   yielded a valid florenfile file object to dedup against, and/or manual
   "Add Links" bypasses the dedup that the FolderWatch/autoConfirm path applies.
2. **Deep-decrypt/availability-check fails silently in the automated path.**
   JD's florenfile plugin may load the page during crawljob processing, hit the
   free-tier wait/premium gate, and return *no* link — so nothing is added.
   Manual "Add Links" instead drops the link into LinkGrabber for the user to see
   regardless of availability.
3. **A FolderWatch / LinkGrabber setting** discards links that don't immediately
   resolve to a confirmable download (e.g. "only auto-confirm online links",
   "skip offline", dupe-check settings).
4. **LinkGrabber vs Downloads tab.** The florenfile links may be sitting in the
   **LinkGrabber** tab (unconfirmed / flagged offline) rather than Downloads —
   the user checked Downloads. Worth checking LinkGrabber explicitly.

---

## 9. What could NOT be determined, and why

The failure is a decision made *inside* JDownloader (its LinkCrawler / FolderWatch
extension). Confirming which of the §8-hyp hypotheses is correct requires:
- JD's logs (inside the JD container, not on the NFS mount), and/or
- JD's settings (Advanced Settings, FolderWatch config, LinkGrabber dupe rules), and/or
- watching JD's **LinkGrabber** tab live while a florenfile crawljob is dropped.

None of these were reachable from the dev machine (no SSH key to the NAS in this
session; JD container FS not NFS-exported). This is the boundary at which the
investigation stopped rather than guess.

---

## 10. The bot code fix that WAS made (real, separate bug)

Local edits in `comicsbot/` (uncommitted, **not deployed**; needs `./deploy.sh`):

- **`ingest.py` — `URL_RE`**: was `r"https?://[^\s<>\"')\]]+"` (excluded `'`,`)`,`]`,
  truncating URLs mid-path). Changed to `r"https?://[^\s<>\"]+"` + a new
  `_clean_url()` that trims only trailing punctuation / unbalanced brackets.
- **`ingest.py` — `_encode_for_crawljob()`** (new): percent-encodes `'`,`(`,`)`,
  `[`,`]`, space etc. before writing the crawljob, so no downstream parser can
  re-truncate. `write_crawljob()` now encodes each URL. *(This did not fix the JD
  ingestion issue, but it is correct and harmless — keep it.)*
- (Also in this same session, unrelated to florenfile: `identify.py`/`processor.py`
  fixes for the "Maxentius_02 → Kikaider Code 02" mis-identification.)

Verification done on the fix: unit-tested `URL_RE`/`_clean_url`/`_encode_for_crawljob`
against the real strings; the corrected extractor returns the full URL, and the
encoded URL was confirmed to resolve at florenfile.

---

## 11. Reproduction

1. Drop a crawljob for a florenfile link into
   `/mnt/nas/downloads/COMICS/folderwatch/`:
   ```json
   [{"text":"https://florenfile.com/zorrqcexbls2",
     "packageName":"floren-test",
     "downloadFolder":"/output/COMICS/telegram/floren-test",
     "autoStart":"TRUE","autoConfirm":"TRUE","enabled":"TRUE","extractAfterDownload":"TRUE"}]
   ```
2. Within seconds JD moves it to `folderwatch/added/`. → **nothing appears in JD.**
3. Now paste the same URL into JD's **Add Links** dialog manually. → **it appears.**

Control: a bit.ly link in the same crawljob format appears fine.

---

## 12. Next investigation steps (require JD access)

1. Open JD → **LinkGrabber** tab (not Downloads) and drop a florenfile crawljob;
   watch whether the link lands there flagged (offline/dupe) or not at all.
2. Read JD logs while processing a florenfile crawljob (JD container, e.g.
   `.../cfg/logs/`), filter for `florenfile`.
3. Check JD settings: LinkGrabber "Do not add duplicate links" / download history
   dedup; FolderWatch extension options; auto-confirm/offline handling.
4. **Dedup test:** clear JD's LinkGrabber + download history, then drop one fresh
   florenfile crawljob. If it now appears → dedup was the cause (§8-hyp.1).
5. **Fresh-id test:** submit a florenfile link whose file-id JD has *never* seen
   (a different file) via crawljob. Appears → the 254/256 ids were poisoned by the
   earlier attempts (dedup). Absent → it's the plugin/decrypt path (§8-hyp.2).
6. Note JD's version + florenfile plugin version; check whether the florenfile
   plugin requires an account even to *check* link status.

---

## 13. Pragmatic fixes / workarounds

- **Immediate (works today):** paste the full florenfile URL into JD's Add Links
  manually. Proven to work; then it waits out the ~20h free-tier limit and
  downloads. Files land in `/output/COMICS/<pkg>/` (not the bot's `telegram/`
  inbox), so the bot won't auto-file them — move into `telegram/` or the bot's
  `tagged/` folder, or tag+file by hand.
- **If JD-side stays unsolved — stop routing florenfile through JD.** Options:
  - Bot downloads florenfile links **directly** itself (XFileSharing free flow:
    GET page → POST `op=download1` → wait N seconds → POST `op=download2` → follow
    the direct link). No captcha observed; but free tier is ~1 file / ~22h per IP,
    so this is slow and must respect the wait. It would bypass JD entirely for
    this host.
  - Bot **detects florenfile** (and other JD-problem hosts) and replies in
    Telegram *"JD can't auto-add this — paste it manually"*, so links don't
    silently vanish.
- **Premium / debrid:** a florenfile premium account or a multihoster/debrid
  (real-debrid, alldebrid, …) added to JD would make it download instantly and
  likely sidesteps the whole issue. User currently has **no** florenfile premium.

---

## 14. Appendix — exact artifacts

**Consumed crawljobs** in `/mnt/nas/downloads/COMICS/folderwatch/added/`:
`comic [77607-254].crawljob` (+`.1`), `comic [77607-256].crawljob` (+`.1`),
`comic 256 enctest.crawljob`, `comic 256 idtest.crawljob`,
plus working terabox: `IN VINO VERITAS … [77607-216].crawljob`,
`HAZAAS BELICAS … [77607-21].crawljob`.

**Working terabox crawljob (appears in JD):**
```json
[{"text":"https://bit.ly/4nL7xCx","packageName":"IN VINO VERITAS TOSCANA … [77607-216]",
  "downloadFolder":"/output/COMICS/telegram/IN VINO VERITAS TOSCANA … [77607-216]",
  "autoStart":"TRUE","autoConfirm":"TRUE","enabled":"TRUE","extractAfterDownload":"TRUE"}]
```

**Failing florenfile crawljob (absent from JD):**
```json
[{"text":"https://florenfile.com/zorrqcexbls2/X-Men_%2797_-_Season_Two_002_%282026%29_%28Digital%29.cbz.html",
  "packageName":"comic 256 enctest",
  "downloadFolder":"/output/COMICS/telegram/comic 256 enctest",
  "autoStart":"TRUE","autoConfirm":"TRUE","enabled":"TRUE","extractAfterDownload":"TRUE"}]
```

**Useful commands** (venv: `~/github/titularia/.venv/bin/python`):
```bash
# Check a florenfile URL form is online (looks for the download form + size):
curl -s -A "Mozilla/5.0" "https://florenfile.com/zorrqcexbls2" | grep -o 'Size: [0-9.]* MB'

# Walk the free flow to see the wait/captcha state (POST op=download1). See
# scratchpad floren_flow.py from the 2026-07-12 session for the full script.
```
