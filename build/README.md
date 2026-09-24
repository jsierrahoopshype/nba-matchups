# build/

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
a GitHub tree API lookup at runtime, so image handling is left to the JS. (The
opponent flag `<img>` tags in `p/` rows *are* baked — they come straight from
the `iso` field in the JSON, with no lookup, and the JS emits the same tags.)

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

Idempotent: containers already carrying `data-prerendered="1"` are skipped, so
re-running is a no-op. Use `--dry-run` to count without writing, `--only` to
limit to named pages, and `--root` to bake a different site root. It does not
touch the `ROOT` / `${ROOT}` logic, the heat legends, the canonical/OG URLs, or
any `<script>` block.

**Re-run it after regenerating data.** The baked markup is a snapshot; if
`data/` changes and the pages are rewritten, the marker goes with them and the
tables are baked afresh. If you ever hand-edit a page and leave the marker in
place, the stale table stays until you remove the marker.
