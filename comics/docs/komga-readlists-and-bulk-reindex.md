# Komga read lists (story arcs) for crossovers + bulk-reindex behavior

**Status:** REFERENCE (2026-07-15) — findings from filing/reorganizing a batch of
Marvel crossover-event reading orders (Civil War, House of M, Onslaught, Age of
Apocalypse, the Secret Wars 2015 chronology) plus several one-shots.
**Component:** Komga side of the `comicsbot` pipeline (library **"Comics"**, id
`0FSAPZZ0CBEAX`), reached over the My-Komga REST API from `.claude/skills/tag`.

---

## 1. TL;DR

- Komga's **Read Lists** are the equivalent of Mylar's *story arcs*: an **ordered
  list of books that spans multiple series**. Perfect for crossovers.
- Two ways to populate them, and **both are enabled** on our library:
  1. **Embedded** — ComicInfo.xml `StoryArc` + `StoryArcNumber` (Komga auto-creates
     the list on scan; `importComicInfoReadList = True`).
  2. **API** — `POST /api/v1/readlists` with an explicit ordered `bookIds` list
     (no file changes).
- A book stays in exactly **one home series** (its folder); the read list is an
  **overlay** on top, threading across series. Pick the home-series layout and the
  read-list layer independently.
- **The one operational hazard is the scan.** Our library has `hashFiles` and
  `analyzeDimensions` on, so every added/moved file is read in full and every page
  decoded — over NFS on the Synology this is *slow*. A ~500-file move took **~40
  min**, committing series **folder-by-folder**, and the REST API **500s / times
  out under scan load**. Plan for a long tail; poll gently.

---

## 2. What a read list is (vs. a series, vs. a collection)

| Concept | Komga meaning | Analogy |
| --- | --- | --- |
| **Series** | one folder of books (the thing you browse) | a run / volume |
| **Read List** | an **ordered, cross-series** list of books | Mylar **story arc** / a reading order |
| **Collection** | an (unordered) group of *series* | a shelf / saga grouping |

A read list is the right tool for a crossover: the "Civil War" thread runs across
Amazing Spider-Man, New Avengers, Wolverine, … in one sequence, regardless of which
series each issue lives in. Books keep their home series; the list is additive.

---

## 3. Creating read lists — option A: embedded ComicInfo (portable)

Komga imports read lists from these ComicInfo.xml fields (docs:
<https://komga.org/docs/guides/scan-analysis-refresh/>):

- **`StoryArc`** (or `AlternateSeries`) → the read-list **name**.
- **`StoryArcNumber`** (or `AlternateNumber`) → the book's **position** in the list.
- Both `StoryArc` and `StoryArcNumber` may hold **comma-separated** values, so one
  issue can belong to **several arcs at once** (shared crossover issues). If the two
  lists differ in length the extra values are dropped; blanks/invalid numbers void
  that pair.

Komga creates/updates the list automatically on the next scan. This travels with the
files (re-imports anywhere) but requires writing ComicInfo → a `.cbr` must be
converted to `.cbz` first. Our `identify.write_basic_tags` does **not** emit
`StoryArc` today; a driver would have to write ComicInfo directly (or extend it).

Relevant library options (all `True` on "Comics"): `importComicInfoReadList`,
`importComicInfoSeries`, `importComicInfoSeriesAppendVolume`, `importMylarSeries`.

---

## 4. Creating read lists — option B: the REST API (no file changes)

Used for this batch (avoids rewriting hundreds of `.cbr`). Auth = HTTP Basic with
`KOMGA_EMAIL` / `KOMGA_PASSWORD` (from `deploy.secrets`).

```
POST /api/v1/readlists
{ "name": "Civil War", "summary": "...", "ordered": true, "bookIds": ["<id>", ...] }
→ 200/201, returns the created object incl. "id"
```

- **Order = the order of `bookIds`.** Build it yourself.
- **Resolve books per series** (in reading order) with:
  `GET /api/v1/series/{seriesId}/books?unpaged=true&size=2000` — each book has
  `name` (= filename without extension, so **sort by `name`** to get file order).
- **Resolve a series id/count by name:**
  `GET /api/v1/series?search=<name>&library_id=0FSAPZZ0CBEAX&size=20` then exact-match
  on `name`. `booksCount` is set as soon as the series is discovered.
- Idempotency: check for an existing list first (see the gotcha below), skip if present.

### API gotchas (learned the hard way)
- **`GET /api/v1/readlists?search=<name>` ignores `search`** — it returns the first
  page of *all* lists. To verify a list exists, fetch it by id:
  `GET /api/v1/readlists/{id}` (authoritative). `GET /api/v1/series?search=` *does*
  honor search.
- **`GET /api/v1/series?...&page=1` 500'd** during a scan. Prefer per-name `search`
  queries over paginating the whole library while a scan is running.
- Under scan load, single calls **time out** (saw 20–90 s+). Use long timeouts,
  retry transient 5xx/timeout, and poll infrequently.

---

## 5. Home-series layout — the model we chose (and rejected)

Curated event packs are reading-order bundles (each file is a *different* series'
issue), not single series. Three models were considered:

- **A — one folder per event.** Simple; each event = one synthetic series.
- **B — spread issues into their real per-title series + a story-arc read list.**
  The "correct" Mylar model, but for these packs it means identifying ~450 mixed
  EN/ES issues to their exact ComicVine series/year, and it litters the library with
  **stub series** (a `Daredevil (1998)` holding only #87). **Rejected.**
- **C — split multi-part events into sub-series, then thread them with a read list.**
  Chosen. Each event is one (or a few) clean home series; a read list re-unifies the
  parts into a continuous read. Best value without the stub-series explosion.

For flat single events (House of M, Onslaught, Era de Apocalipsis) A ≡ C — the folder
is already the order; a read list only adds value when an event is **split**.

---

## 6. The bulk-reindex behavior (the real time sink)

Moving/renaming folders and adding files, then triggering a scan
(`POST /api/v1/libraries/{id}/scan` → **202**, async; or `filer.komga_scan()`):

1. **Removals are fast** — old series (`civil_war`, …) vanish from the DB almost
   immediately (metadata only).
2. **Adds are slow** — each new/moved file is **hash-read in full** (`hashFiles`) and
   **every page decoded for dimensions** (`analyzeDimensions`). Over NFS this is the
   bottleneck. `convertToCbz` is **off**, so at least nothing is recompressed.
3. **Series commit incrementally**, roughly folder-by-folder, each appearing with its
   correct `booksCount` once its folder finishes. `.cbz` folders land faster than
   `.cbr`; the long pole was Secret Wars II (43 `.cbr`).

**Measured:** ~500 files (≈450 moved + 55 Blueberry `.cbz` + a few) took **~40 min**
end-to-end, surfacing a few series at a time. The API was flaky throughout.

**Implications / how to run a big move:**
- Poll **gently**: one `series?search=<name>` per ~60–75 s, skip already-resolved
  names, tolerate timeouts. Don't hammer — it slows the scan and 500s.
- Files added *after* a scan starts aren't in it → run a **final scan** and verify.
- To make a large bulk op fly, **temporarily** set `analyzeDimensions` (and
  `hashFiles`) off on the library, scan, then re-enable — **only with the user's OK**
  (`PATCH /api/v1/libraries/{id}` / library options). Default: just wait it out.

---

## 7. Worked example — what this batch produced (2026-07-15)

Filed/rehomed under `/mnt/nas/comics`, publisher `Marvel` unless noted:

| Home series | Books | Notes |
| --- | --- | --- |
| `Civil War - Road to Civil War (2006)` | 12 | from `civil_war/road_to_civil_war` |
| `Civil War (2006)` | 109 | incl. `covers.cbz` (excluded from the read list) |
| `Civil War - The Initiative (2007)` | 84 | |
| `Secret Wars Chronology 02–11 - … (2015)` | 121 | 10 sub-series; empty `01 Secret Wars (1984)` dropped |
| `House of M (2005)` | 53 | |
| `La Era de Apocalipsis (1995)` | 45 | |
| `Onslaught Saga (1996)` | 39 | |
| `Estela Plateada - La Muerte de Galactus (1995)` | 2 | Planeta DeAgostini ed., kept under Marvel |
| `Norma Editorial/Blueberry (1999)` | 55 | full saga #00–54 (not just the Youth sub-line); album title kept in Summary |
| `Nuevo Nueve Editores/Soy la Malinche (2022)` | 1 | Alicia Jaraba, not on ComicVine |

Read lists created via the API:

| Read list | Books | Threads |
| --- | --- | --- |
| **Civil War** (`0R0CJ5YBYSTTW`) | 204 | Road to → main → Initiative, in file order |
| **Secret Wars Chronology** (`0R0CJCEEYSPDW`) | 121 | the 10 sub-series in order |

Torrent junk (`Torrent downloaded from Demonoid…`, `tracked_by_h33t…`, `.directory`)
and redundant nesting were removed during the restructure.

---

## 8. Reusable recipe (API read list from folder order)

The drivers for this run lived in a scratchpad, but the pattern is:

```python
import os, requests
url = os.environ["KOMGA_URL"].rstrip("/"); LIB = "0FSAPZZ0CBEAX"
s = requests.Session(); s.auth = (os.environ["KOMGA_EMAIL"], os.environ["KOMGA_PASSWORD"])

def series_id(name):
    r = s.get(f"{url}/api/v1/series", params={"search": name, "library_id": LIB, "size": 20}, timeout=90)
    return next(c["id"] for c in r.json()["content"] if c["name"] == name)

def book_ids(sid):                     # reading order = filename order
    r = s.get(f"{url}/api/v1/series/{sid}/books", params={"unpaged": "true", "size": 2000}, timeout=90)
    return [b["id"] for b in sorted(r.json()["content"], key=lambda b: b["name"])]

ids = [bid for name in ORDERED_SERIES_NAMES for bid in book_ids(series_id(name))]
s.post(f"{url}/api/v1/readlists",
       json={"name": "Civil War", "summary": "...", "ordered": True, "bookIds": ids}, timeout=90)
```

Config (paths, Komga creds) auto-loads via `import tagkit` from
`.claude/skills/tag` — the same "reuse comicsbot modules over NFS" pattern as the
`/tag` skill. Verify the result with `GET /api/v1/readlists/{id}`, **not** a search.

---

## 9. See also

- `.claude/skills/tag/` — the `/tag` skill + `tagkit.py` (filing, `filer.komga_scan()`).
- `CLAUDE.md` §"External services" — Komga library id, scan entry point.
- `docs/florenfile-jdownloader-issue.md` — the JDownloader side of the pipeline.
