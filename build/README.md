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
   labels, plus one line of text) where that footer used to be, directly below
   the last stat table, and the small `.heat-legend` CSS rule it needs.

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

`index.html` gets the footer removal only. Its featured-player mini table
colors FG%, 3P% and PTS/100 with its own pair of functions, has no TOV column
and no direction flip, so neither legend above describes it accurately.

It does not touch the `ROOT` line or any `${ROOT}` path from
`fix_matchup_paths.py`, the JSON-LD blocks, `data/`, `sitemap.xml` or
`robots.txt`.

### When to run it

After every regeneration of `m/` and/or `p/`, alongside `fix_matchup_paths.py`:

```
python build/apply_ui_tweaks.py
```

It is idempotent: files already carrying the `data-legend="heat"` marker (or
with the footer already stripped) are skipped, so re-running on an
already-patched tree is a no-op. Use `--dry-run` to count what would change
without writing anything.
