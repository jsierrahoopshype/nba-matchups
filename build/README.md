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
