# build/

These scripts re-apply everything this repo adds on top of the generated
pages. `m/` and `p/` are produced by a generator that lives **outside** this
repo, so every regeneration overwrites the pages and wipes all of it: the
`ROOT` path fix, the colour legends, the footer removal, the hoopsmatic.com
canonicals, and the pre-rendered tables and headers.

## The pipeline

Three stages. Only the first needs the internet.

| stage | script | network | where it runs |
|---|---|---|---|
| 1. fetch | `fetch_matchup_data.py` | **yes** — stats.nba.com | your machine only |
| 2. generate | `generate_matchup_pages.py` | no | anywhere |
| 3. fix | the four scripts below | no | automatic, on every push to `main` |

**Stage 1 cannot run in CI.** stats.nba.com blocks datacenter IPs, so the
fetch fails from a GitHub Action or any cloud sandbox. Run it locally — on
Windows, double-click `build/refresh-matchup-data.bat`, which does all three
stages and then tells you what to commit.

**Stage 2 emits "raw" pages.** The generator writes each page from its
template with the GitHub Pages canonical, the footer credit still in place,
relative paths, no colour legend and no pre-rendered tables. Stage 3 is what
finishes them. Keeping the two apart means the generator stays a faithful
reconstruction of the original rather than absorbing five later fixes.

So the only meaningful way to check stage 2 is end to end:

```
generate  ->  the four fixes below, in order  ->  diff against HEAD
```

which is exactly how it was verified: delete all 2,545 pages, regenerate from
`data/`, run the fixes, and zero files differ from what is committed.

**Stage 3 is automatic** and is described in the next section.

## This runs automatically

`.github/workflows/apply-build-fixes.yml` runs all four scripts on every push
to `main` and commits the result back as
`Auto: re-apply build/ fixes after regeneration`. Push regenerated pages and
the fixes come back on their own; if nothing needs fixing the run exits without
committing. A script that errors fails the run loudly instead of pushing a
half-applied tree.

The workflow runs on `main` pushes only — never on pull requests, never on
other branches. It cannot loop: GitHub does not trigger workflows for pushes
made with the built-in `GITHUB_TOKEN`, and the job additionally skips itself
when the head commit is its own. (It is also naturally loop-safe: a second pass
over an already-fixed tree changes nothing, so there is no commit to make.)

## Order matters

Run them in this order — the workflow does:

| # | script | why here |
|---|---|---|
| 1 | `fix_matchup_paths.py` | **Must be first.** It rewrites the page JS to build paths from `${ROOT}`, including the opponent links that step 4 bakes. Bake before this and the baked hrefs will not match what the JS produces. |
| 2 | `apply_ui_tweaks.py` | Footer removal and the heat legend. Independent of 1 and 3; before 4 so the page structure is final. |
| 3 | `fix_canonical_urls.py` | Canonical / OG / JSON-LD / sitemap / robots URLs. Touches `<head>`, `sitemap.xml` and `robots.txt` only, so it is independent of the others. |
| 4 | `prerender_matchup_tables.py` | **Must be last.** It snapshots what the page JS renders, and that output depends on the `${ROOT}` paths from step 1. |

Only 1 → 4 is a hard dependency; 2 and 3 can go anywhere before 4.

## Running them by hand

From the repo root, after a regeneration:

```
python build/fix_matchup_paths.py
python build/apply_ui_tweaks.py
python build/fix_canonical_urls.py
python build/prerender_matchup_tables.py
```

About 25 seconds for the full set over all 2,547 pages, whether or not
anything needs changing. Every script is idempotent and supports `--dry-run`,
so running them again — or running them when you are not sure whether the
workflow already has — is safe and cheap.

## fetch_matchup_data.py

Stage 1: rebuilds `data/m/*.json` and `data/p/*.json` from the NBA's
season-matchup endpoint. **Run it on your own machine** — see the pipeline
table above.

Polite by default: 3s between requests, browser headers (stats.nba.com
enforces `Referer` and `User-Agent`), five retries with exponential backoff
and jitter, and every `(season, season type)` response cached under
`build/.cache/matchups/`. A run that dies part-way resumes from the cache
instead of starting over; `--refresh` forces a re-request.

Read the module docstring before the first run. It separates what is **proven
against the committed data** (every derived-field formula, the
`career == sum(byPhase) == sum(bySeason)` identity, the `byWindow` windows,
the `poss >= 10` opponent cut, the slug rule, the country→ISO map) from what
is **written to spec and never executed against the live API** (the endpoint
URL and parameter names, the response shape, the source of
name/country/position). `--self-test` exercises the transform offline;
`--verify-slug <slug>` transforms one page from fetched rows and diffs it
against the committed file, which is the real proof once you can reach the
API.

`hero_matchups.json` is hand-written editorial copy and is never touched.

### Verify before you refresh

The endpoint is an informed guess, so nothing overwrites 2,545 pages until it
is confirmed against real data. Two gates, both double-clickable:

| file | what it does | writes |
|---|---|---|
| `build/verify-matchup-fetch.bat` | Fetches one player, transforms in memory, diffs against the committed `data/p/nikola-jokic.json`, prints PASS/FAIL and the diff | **nothing in the repo** — its cache goes to `%TEMP%` |
| `build/refresh-matchup-data.bat` | The full rebuild | `data/`, `m/`, `p/` — but only after both gates pass |

`refresh` refuses to start unless `verify` has passed **for the current
contents of `fetch_matchup_data.py`** — the marker records the file's
SHA-256, so editing the fetcher invalidates it. It then re-runs the same
check live, against the cache the real run will use, so the requests are not
wasted. A mismatch aborts before the backup, the fetch or any write.

`refresh` also copies `data/` to `..\nba-matchups-data-backup\data-<timestamp>`
(outside the repo) before writing, and aborts if that copy fails. `data/` is
tracked in git too, so `git checkout -- data m p` undoes a bad run.

The fetch cache lives in `build/.cache/`, which is git-ignored along with
`__pycache__/`. Without that, the `git add -A` that `refresh` suggests at the
end would commit hundreds of MB of raw API responses.

If the verification fails in a way the diff does not explain, run
`build/diagnose-matchup-fetch.bat`. It is read-only and makes no requests — it
just describes what the cached responses actually contain (result set names,
columns, row counts, `SEASON_ID` prefixes, one sample row) and writes the
output to a file to send on.

### One-click check rounds

While the fetcher is being fixed, its changes land on the `fetcher-dev`
branch, not on `main`. `build/run-matchup-check.bat` (on `main`) runs a round:

1. downloads every file listed in `build/fetcher-files.txt` from
   `fetcher-dev` into `build\` (all or nothing; it never replaces itself),
   and prints which ones are new, updated or unchanged;
2. runs `build/check_runner.py`, which runs `verify-matchup-fetch.bat`
   and, if that fails, `fetch_matchup_data.py --verify-slug nikola-jokic
   --investigate` against the same `%TEMP%` cache;
3. writes all of it to `build\last-check.txt` and opens it in Notepad.

No keypress prompts: `verify-matchup-fetch.bat` skips its `pause` when
`HOOPSMATIC_NONINTERACTIVE` is set. Nothing under `data\`, `m\` or `p\` is
read for writing. `last-check.txt` is git-ignored.

The downloaded files show up in `git status` as local changes. Before pulling
`main` after `fetcher-dev` is merged, discard them with `git checkout -- build`.

### Investigating differences from the June snapshot

`--investigate` (with `--verify-slug`) is read-only and explains a failing
strict gate instead of just counting it:

1. **Every differing cell, classified**: regular-season only vs containing
   playoffs, and by size (`poss rounding`, `poss only`, `small`, `medium`,
   `large`, `games differ`), with tallies by season and the direction of the
   poss difference.
2. **The hypothesis test.** For the named cells (Horford and Sengun vs Jokić,
   2024-25), two control cells that already match, and then the other
   differing cells up to `--investigate-budget` boxscores (default 40), it
   fetches the regular-season game list (`leaguegamelog`,
   `SeasonType=Regular Season`) and `boxscorematchupsv3` for every game both
   players appeared in, sums them and compares with the snapshot and today's
   season endpoint:
   - per-game = snapshot, season endpoint differs → **(b)**, the snapshot was
     built from per-game data;
   - per-game = season endpoint, snapshot differs → **(a)**, the NBA revised
     its numbers after June 3;
   - neither → something else.
   The controls must reproduce exactly first. Otherwise the per-game path is
   not proven and no verdict is drawn.
3. A weak supporting signal from row counts.
4. A conclusion: a verdict needs 80% of the tested cells on one side.

Regular-season games are cached under `rs_lists/` and `rs_games/` in the
verify cache. A second run makes no new boxscore requests.

### Where playoffs come from

**Not from `leagueseasonmatchups`.** Probed from a residential connection,
its regular-season control returned 137,763 rows while `SeasonType=Playoffs`
returned a valid, empty table in every variant — `PerGame`, blank ID params
dropped, and filtered by `OffTeamID`, `DefTeamID`, `OffPlayerID` and
`DefPlayerID`. `Post Season` and `Playoff` were rejected with HTTP 400, so
`Playoffs` is a recognised value with nothing behind it.

**Not from the committed data either.** It stores playoffs only in aggregate:
`byPhase.PO` across all seasons, and `bySeason` with the two phases mixed. No
season × phase cell exists anywhere. Per-season playoff numbers can be
recovered exactly only for the 1,321 `m/` pairs (`bySeason` minus the fetched
regular season) — 5.9% of the 51,062 opponent rows that carry playoff data.

So `playoff_games.py` rebuilds them game by game: `leaguegamelog`
(`SeasonType=Playoffs`) for each season's game IDs, `boxscorematchupsv3` for
each game, then aggregation into rows of exactly the season endpoint's shape,
so nothing downstream changes. Play-in games (IDs `005…`) are excluded; the
committed data has only RS and PO.

- **Finished games are cached for good**, and `--refresh` does not touch
  them. Completed seasons' game lists too; only the latest season's list is
  re-requested each run.
- **Empty responses are never cached** — a played game always has matchups —
  and a cached empty entry is discarded and refetched.
- **A one-game probe runs before the per-game data is relied on**, the first
  time a cache is used (`--probe-boxscore` runs it by hand). It fetches one
  known playoff game, checks every field the aggregation needs is present,
  reports how many decimals `partialPossessions` carries, and records the
  request parameters that worked. A failing probe records nothing, so it is
  retried next run.
- **Orientation is proven, not assumed.** In the nested V3 shape it is not
  certain whether the outer player is the scorer or the defender. The probe
  gives a hint from one game's points; the verification then aggregates both
  ways and keeps whichever reproduces the committed data exactly. A full
  build refuses to run until a verification has recorded one.

### What PASS looks like

Know this before running it, so a plausible-but-wrong result cannot pass for
success. On `nikola-jokic` a correct run prints:

```
loaded 1,225,797 matchup rows from cache
  rows by phase (from SEASON_ID): {'RS': 1225797}
  playoffs: ~94-115 game(s) in scope (the verified player's), ...
  playoff rows: ..., aggregated from ~94-115 game(s)
...
  identity               PASS
  metadata               PASS
  ORIENTATION  outer player = ...  (verified: 0 mismatches, 18 read the other way)
  PLAYOFFS     ~94-115 game(s); completed-season cells carrying playoff data N, matching N
  STRICT  pairs 40, season-cells 528, mismatches 0   PASS
  DRIFT   ... pair-direction(s) differ on 2025-26  (expected, not a failure)
 RESULT: PASS
```

| line | expected | why |
|---|---|---|
| regular-season rows | **1,225,797** | your own count from the last run; the cache is reused |
| playoff games | **94**, plus Denver's 2025-26 games | Denver 2018-19 → 2024-25: 14 + 19 + 10 + 5 + 20 + 12 + 14 |
| `ORIENTATION` | **0** mismatches, and **18** the other way | read backwards, every one of the 18 Jokić pairs with playoff data breaks |
| `PLAYOFFS … matching` | equal to the cells count | every completed-season cell carrying playoff data reproduces exactly |
| `pairs` / `season-cells` | **40** / **528** | unchanged from before |
| `mismatches` | **0** | anything above 0 fails |
| `DRIFT` | small, possibly **0** | see below — never fails either way |

**If it fails:** `mismatches 18` means playoffs are still missing entirely.
`NEITHER reading reproduces the committed data` means the per-game numbers
disagree with the committed ones whichever way they are read — send the output.
A failure where the output says the differing cells differ **only in poss, by
0.1 or less, with every count matching** is per-game rounding, not wrong data;
the probe's `partialPossessions decimals seen` line says whether that is
possible.

`metadata` covers `pos` too: `G`/`G-F` → `G`, `F`/`F-C`/`F-G` → `F`,
`C`/`C-F` → `C`, and the literal string `None` → `''` — the committed data's
own vocabulary (`G`, `F`, `C`, `''`).

### Requests and runtime

At the default 3-second spacing, a request costs roughly 3.5–4.5 s in total.

| run | requests | time |
|---|---|---|
| **verify**, first run on your existing cache | 9 game lists + 3 probe + ~94–115 games; **0** regular season | ~8 min |
| **verify**, again | 1 (the latest season's game list) | seconds, plus local processing |
| **refresh**, first run — the backfill | seeded from the verify cache, then ~650–750 games | **~40–60 min**, resumable |
| **refresh**, afterwards | 1 game list + games new since last time — 0 in the offseason | a minute or two, plus several minutes of local processing |

Playoffs run 60–105 games a season by format and have been about 80–90 in
practice, so all nine seasons come to roughly 720–810 games; the verify has
already fetched Jokić's ~100 of them and `refresh` copies those, and the
regular-season cache, across from the verify cache instead of downloading them
again. The exact counts print as it runs.

**Before next season:** `SEASONS` ends at 2025-26, so 2026-27 is not fetched
until it is added (a one-line change), and a cached regular season never
expires — fine for finished seasons, wrong for one in progress. Both need
handling when 2026-27 starts; neither is changed here.

### What the strict gate compares, and why not everything

`data/` was generated on **2026-06-03**. The 2025-26 regular season had ended
in April, but its playoffs were still being played. So:

- **2017-18 … 2024-25** were finished and are frozen. These are compared
  strictly, per season, and any difference is a failure.
- **2025-26** can legitimately differ wherever playoff games were played after
  the build, so it is reported as **drift**, never as a failure. Only pairs
  that met in those late playoff games can drift, so expect a small number —
  possibly zero. If it does come back zero, 2025-26 could later be promoted
  into the strict set; it is not here.

The strict comparison runs on `m/` pair files, because they are the only
committed files with a per-season breakdown. A `p/` page stores only career,
`byPhase` and `byWindow` totals, every one of which mixes the in-progress
season in. Identity and metadata on the `p/` page are still compared strictly,
since neither drifts.

The **opponent-list counts are informational, not a gate**. Membership is
`poss >= 10` measured over all seasons. With playoffs now included they should
match or come very close; late 2025-26 playoff games can still move a player
across the threshold.

## generate_matchup_pages.py

Stage 2: `data/` → the HTML in `m/` and `p/`. The original generator was lost;
this is a reconstruction from its output. Each page is its template with
exactly two lines replaced — the placeholder `<title>` and
`<meta name="description">` — by a per-page head block. Everything else,
CSS and JavaScript included, comes from the template verbatim.

One quirk is reproduced on purpose: the templates carry their own
`<meta property="og:type">` and the injected block emits one too, so every
page has the tag twice. That is what the committed pages contain, and
byte-identical beats tidier.

`index.html` is hand-maintained and is **not** regenerated.

```
python build/generate_matchup_pages.py            # write in place
python build/generate_matchup_pages.py --out /tmp/x   # write elsewhere, for diffing
```

## fix_matchup_paths.py

Rewrites relative internal paths in the generated pages under `m/` and `p/`
(templates included) so the site works on both hosts:

- GitHub Pages: `https://jsierrahoopshype.github.io/nba-matchups/`
- hoopsmatic.com: `https://hoopsmatic.com/matchups/` (Cloudflare Worker proxy
  that injects `<base href="/matchups/">` into every page)

Under the injected `<base>`, paths like `../data/m/x.json` resolve to the site
root (`https://hoopsmatic.com/data/m/x.json`) and 404, which makes every
matchup page show "No head-to-head data for this matchup."

The script inserts at the top of each page's inline script:

```js
const ROOT = location.pathname.replace(/\/(m|p)\/[^/]*$/, "/");
```

and builds every internal path from it (`${ROOT}data/...`, `${ROOT}m/...`,
`${ROOT}p/...`). Absolute paths are not affected by `<base>`, so this works on
both hosts. The static back link (`<a class="back">`) becomes `href="#"` in the
HTML and is pointed at `${ROOT}index.html` by that same script on load, since
no relative href can be right on both hosts.

It does not touch `index.html`, `data/`, `sitemap.xml`, `robots.txt`, the
canonical/og meta tags, or the headshot, flagcdn and fonts URLs.

### When to run it

Run it after every regeneration of `m/` and/or `p/` (any time the generator
rewrites pages from `m/template.html` or `p/template.html`), before committing:

```
python build/fix_matchup_paths.py
```

It is idempotent: files that already contain the `ROOT` marker are skipped, so
re-running it on an already-fixed tree is a no-op. Use `--dry-run` to see how
many files would change without writing anything.

## apply_ui_tweaks.py

Two UI tweaks for the generated pages under `m/` and `p/` (templates included),
plus `index.html`:

1. Removes the `<div class="foot">HoopsMatic</div>` credit block. The `.foot`
   CSS rule is left in place.
2. Adds a compact heat-color legend (gradient swatch with `worse`/`better`
   labels, plus one line of text) directly below the last color-coded stat
   table, and the small `.heat-legend` CSS rule it needs. On `m/` and `p/` that
   is exactly where the footer used to be.

The legend wording differs per directory because the pages color different
things:

- `m/` — summary cards use `absHeatStyle()` (fixed league-wide ranges: FG%
  35-55%, 3P% 20-45%, eFG% 40-62%, PTS/100 0-130, AST/100 0-12, TOV/100 0-15);
  season rows use `heatStyle()`, relative to the other seasons in that table,
  falling back to the fixed ranges when a table has only one season.
- `p/` — the summary card uses the local `ah()` helper with those same fixed
  ranges, flipped in the "as defender" view; opponent rows use `heatStyle()`,
  relative to the other opponents shown, with `goodHigh` flipped in the
  defender view.
- `index.html` — the featured-player mini table colors only FG%, 3P% and
  PTS/100, with its own pair of functions: relative to the other opponents
  listed, falling back to fixed ranges only when the range is degenerate. No
  TOV column and no direction flip, so it gets its own wording.

On `index.html` the legend is injected into the JS template literal that builds
the mini table (right after `</table>` in `renderFeatured`), not into the static
HTML, so it exists only when the table does — `#featuredBlock` is filled by JS
and stays empty if the fetch fails. The "Most frequent matchups" section is
left alone on purpose: nothing in it is color-coded.

It does not touch the `ROOT` line or any `${ROOT}` path from
`fix_matchup_paths.py`, the JSON-LD blocks, `data/`, `sitemap.xml` or
`robots.txt`.

### When to run it

After every regeneration of `m/` and/or `p/`, alongside `fix_matchup_paths.py`:

```
python build/apply_ui_tweaks.py
```

It is idempotent: each edit is guarded on its own (the `data-legend="heat"`
marker for the legend, the presence of the footer block for the footer), so
re-running on an already-patched tree is a no-op. Use `--dry-run` to count
what would change without writing anything.

## fix_canonical_urls.py

Points every self-referencing URL at the public host. The generator writes
them against GitHub Pages:

```
https://jsierrahoopshype.github.io/nba-matchups/
```

but the section is served at `https://hoopsmatic.com/matchups/`, so search
engines were being told to index the GitHub copy. The script rewrites that
prefix in:

- `<link rel="canonical" href="...">`
- `<meta property="og:url" content="...">`
- `<meta name="twitter:url" content="...">` (none today; covered in case the
  generator starts emitting it)
- JSON-LD `"url"` and `"@id"` values
- `<loc>` entries in `sitemap.xml`
- the `Sitemap:` line in `robots.txt`

across `m/*.html`, `p/*.html`, `index.html`, `sitemap.xml` and `robots.txt`.
The two templates carry no absolute URLs, so they are untouched.

The headshot assets under
`https://jsierrahoopshype.github.io/nba-headshots/...` are a different repo
path and stay on GitHub Pages. Every pattern is anchored on the
`/nba-matchups/` prefix, so they are never matched, and the script counts them
before and after and fails if the total moved.

The rewrite is attribute-scoped rather than a blind prefix swap, so a future
link that genuinely wants to point at the GitHub copy would not be caught by
accident. After rewriting, the script re-checks each file and reports any
remaining occurrence of the old prefix that its patterns did not cover — which
is how the stale `index.html` canonical was caught after the first manual pass
fixed `m/`, `p/`, `sitemap.xml` and `robots.txt` but missed the homepage.

### When to run it

After every regeneration of `m/`, `p/`, `sitemap.xml` or `robots.txt`:

```
python build/fix_canonical_urls.py
```

It is idempotent: once a URL is on the new prefix there is nothing left to
match, so re-running is a no-op. Use `--dry-run` for the counts without
writing. It does not touch the `ROOT` / `${ROOT}` logic from
`fix_matchup_paths.py`, the heat legends from `apply_ui_tweaks.py`, the
sitemap's `<lastmod>` dates, or `data/`.

## prerender_matchup_tables.py

Bakes the default-view stat tables into the HTML of every page in `m/` and
`p/`, so the content is in the source instead of appearing only after the JS
runs. These pages rendered everything client-side from `data/m/*.json` and
`data/p/*.json`; Google executes JS but crawls JS-dependent pages slowly and
unreliably, which is what "Discovered - currently not indexed" reflects.

### Progressive enhancement, not replacement

No JavaScript is modified, removed or disabled. The baked markup goes into the
same containers the JS writes to:

| page | container | written by |
|---|---|---|
| `m/` | `#content` | `renderDirections()` |
| `p/` | `#title`, `#subtitle` | `renderHeader()` |
| `p/` | `#career`, `#oppContainer` | `renderCareer()`, `renderOpponents()` |

On load the page fetches its JSON exactly as before and overwrites those
containers. Because the baked markup is byte-identical to what the JS produces
for the default state, the swap is invisible — and if the baked markup were
ever wrong, the live page would correct itself. **That self-correcting
property is the safety model.** Do not make the JS conditional on the baked
content.

### What is baked

Only the state the page shows on load:

- `m/` — phase `all`
- `p/` — dir `asOff`, window `all`, phase `all`, sort `pts_per_100` descending,
  min sample 50 POSS, empty search

Every toggle (Regular season / Playoffs / As defender / Range / Min sample /
opponent search) stays JS-only. They are behind a click, so a crawler never
reaches them.

Headshots are **not** baked: the player cards resolve their image URLs through
a GitHub tree API lookup at runtime, so image handling is left to the JS. That
is also why `m/` has no baked header — its header *is* those two cards. `m/`
pages have no `<h1>` and no placeholder text that could go stale, and both
player names already appear in the baked `<h2>` section headings.

The flag `<img>` tags — on `p/` `#title` and in the opponent rows — *are*
baked. They are built from the `iso` field in the JSON with no lookup, and the
JS emits byte-identical tags.

`index.html` is not touched, because its featured player rotates on each load
and a baked table there would go stale. The two templates have no slug and so
no data; they are skipped.

### Fidelity

The helpers are ports of the page's own functions, kept line-for-line
alongside the originals including the exact whitespace of the template
literals. JS number formatting is reproduced rather than approximated:

- `js_to_fixed` — `Number.prototype.toFixed`: round half away from zero on the
  *exact binary value* of the double. Python's `format()` rounds half to even
  and disagrees on ties.
- `js_to_locale` — `Intl.NumberFormat` en-US defaults: at most 3 fraction
  digits, half-expand, trailing zeros stripped, comma grouping.
- `js_math_round` — `Math.round` is `floor(x + 0.5)`, not round-half-even.

The output is verified byte-for-byte against the pages' own JavaScript,
executed in Node against a DOM shim, for every page in `m/` and `p/`.

Two things are inherently host- and locale-dependent, and are baked for the
canonical case:

- **Link paths.** The only `${ROOT}`-dependent markup inside a baked container
  is the opponent link on `p/` pages (`m/` containers have no links). ROOT is
  computed from `location.pathname` at runtime, so a baked href can only be
  right for one host. It is baked for `/matchups/`, the canonical host that
  `fix_canonical_urls.py` points every canonical at. On GitHub Pages the JS
  recomputes ROOT and rewrites the hrefs on load. Pass `--root` to change it.
- **Locale.** `toLocaleString()` follows the visitor's locale, so a visitor in
  a comma-decimal locale sees `1.234,5` where this bakes the en-US `1,234.5`.
  The JS overwrites the markup on load either way, so what a visitor reads is
  always correct; only the crawler-visible source is fixed, and en-US is what
  Googlebot requests.

### Page weight

Baking roughly doubles the section on disk: `m/` 27.5 MB → 40.2 MB, `p/`
30.4 MB → 76.3 MB. A typical `m/` page goes 20.8 KB → 30.6 KB. `p/` pages vary
with opponent count: a short one is 24.8 KB → 25.5 KB, while the largest
(`p/james-harden.html`, 295 opponent rows) is 24.8 KB → 265 KB, or 8.0 KB →
28.8 KB gzipped. The JSON fetch still happens by design, so the largest player
pages do cost a visitor more bytes than before.

### When to run it

After every regeneration of `m/` and/or `p/`, and after `fix_matchup_paths.py`
and `apply_ui_tweaks.py` (it bakes the legend along with everything else):

```
python build/prerender_matchup_tables.py
```

Idempotent **per container**: each container carries its own
`data-prerendered="1"` marker, so a page that already has some containers baked
still picks up one added later (that is how the `#title` / `#subtitle` bake
landed on pages whose tables were already baked). Re-running is a no-op. Use `--dry-run` to count without writing, `--only` to
limit to named pages, and `--root` to bake a different site root. It does not
touch the `ROOT` / `${ROOT}` logic, the heat legends, the canonical/OG URLs, or
any `<script>` block.

**Re-run it after regenerating data.** The baked markup is a snapshot; if
`data/` changes and the pages are rewritten, the marker goes with them and the
tables are baked afresh. If you ever hand-edit a page and leave the marker in
place, the stale table stays until you remove the marker.
