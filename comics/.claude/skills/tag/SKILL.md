---
name: tag
description: >-
  Manually tag comics that failed automatic identification and file them into
  the Komga library. Use when the user runs /tag (tag every untagged comic in
  downloads/COMICS/failed/), /tag "<name>" (only matching failed/ files), or
  /tag --unknown "<name>" (re-tag the named comics sitting in the library's
  Unknown/ publisher and move them to their real home). Groups files by series,
  confirms the ComicVine edition once per series, tags with ComicTagger, files
  them as Publisher/Series (Year)/…, and triggers a Komga scan.
---

# /tag — tag & file comics that missed auto-identification

Two sources, chosen by the flag:

- **`/tag`** or **`/tag "<name>"`** → archives in `downloads/COMICS/failed/`
  (comics that were downloaded but never identified). `<name>` filters by path.
- **`/tag --unknown "<name>"`** → comics already filed under the library's
  `Unknown/` publisher. **The name is REQUIRED** — only touch folders matching
  it, never a blanket sweep. `Unknown/` holds intentionally-not-on-ComicVine
  comics (bitterkomix, El Huaso Ramón, …); leave everything you weren't asked
  about exactly where it is.

## Engine

`tagkit.py` (next to this file) does the mechanics: it auto-loads config from
`deploy.conf`/`deploy.secrets` (NAS paths → `/mnt/nas`), reuses the bot's own
`identify`/`filer` code, drives the local **ComicTagger AppImage**
(`~/Downloads/ComicTagger-x86_64.AppImage`, or set `COMICTAGGER_APPIMAGE`), and
throttles ComicVine. It only needs `requests`.

Set up a Python once, then use it for every call:

```bash
cd ~/github/Utils/comics/.claude/skills/tag
if python3 -c "import requests" 2>/dev/null; then PY=python3; else
  python3 -m venv /tmp/tagkit-venv && /tmp/tagkit-venv/bin/pip -q install requests
  PY=/tmp/tagkit-venv/bin/python
fi
```

Commands (all JSON in/out): `list`, `resolve`, `tag-series`, `asis`, `scan`.

## Procedure

1. **List the targets.**
   `$PY tagkit.py list`  •  `list "<name>"`  •  `list --unknown "<name>"`
   → `[{path, series_guess, issue_guess, has_cv_id, current_series, current_publisher}]`.
   Ignore entries with `has_cv_id: true` unless the user explicitly wants a retag.

2. **Group by `series_guess`.** Handle one series at a time:

   a. **Find the volume:** `$PY tagkit.py resolve "<series>"`. If the files are a
      foreign-language edition (e.g. Spanish scans) or a known long run, add
      `--language es` and/or `--count <N>` so the right edition ranks first —
      multi-language series (Thorgal, Asterix, Corto Maltés…) reuse the same
      cover art, so language + issue-count is what distinguishes editions.

   b. **Confirm ONCE with the user** via AskUserQuestion: show the top volume
      candidates (`name (year) · publisher · N iss`) and let them pick. Always
      include a **"Not on ComicVine — file as-is"** option and a **"Skip this
      series"** option. Never ask per file — one decision covers the whole run.

   c. **Tag + file the whole series.** Build a JSON list of `{path, issue}`
      (issue from `issue_guess`; apply any correction the user gave) and:
      ```bash
      echo '[{"path":"…/X #1.cbz","issue":"1"}, …]' > /tmp/series.json
      $PY tagkit.py tag-series --volume <chosen_id> --files /tmp/series.json
      ```
      It returns per-file `{status, dest}`. Any file whose issue isn't in the
      chosen volume comes back as `no issue #N in volume …` — re-check those
      (wrong volume, or a variant/annual numbering) rather than forcing them.

   d. **Not on ComicVine?** Agree the publisher/year with the user, then per file:
      ```bash
      $PY tagkit.py asis --path "…/File.cbz" --series "Las guerras silenciosas" \
        --publisher "Norma Editorial" --year 2014 --summary "…"
      ```
      Give a real publisher so it doesn't land back in `Unknown/`.

3. **Scan Komga once** at the very end: `$PY tagkit.py scan`.

4. **Report**: filed destinations, plus anything skipped or left for the user.

## Rules & gotchas (learned the hard way)

- **One confirmation per series, then batch.** Don't re-ask per issue.
- **Editions matter.** ComicVine's cover-hash can't tell a Spanish Thorgal from
  the German one (shared art). Pick by the caption's **language** + **issue
  count** — `resolve --language es --count 34` puts the right volume first.
- **Watch for the wrong-edition trap.** If a match's publisher/language
  contradicts what the user said, it's probably the wrong edition — re-resolve.
- **Zip-named-`.cbr` (and vice-versa)** are common; tagkit sniffs content, so
  just pass the path. Real `.cbr` needs the `unrar` CLI.
- **Leading zeros are fine** (`001` == `#1`); tagkit strips them.
- **`--unknown` is surgical:** only the named series; those files are already in
  the library, so a successful retag *moves* them out of `Unknown/`.
- After a batch, a quick sanity check of one filed `ComicInfo.xml`
  (Series/Number/Publisher/Web) confirms the edition is right.
