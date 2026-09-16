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
