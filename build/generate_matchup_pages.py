#!/usr/bin/env python3
"""Stage 2 of the pipeline: data/ -> the HTML pages in m/ and p/.

The original generator was lost; this is a reconstruction from its output,
which is the only surviving specification. It is verified the only way that
means anything: regenerate all 2,545 pages and diff against what is committed.

WHAT THIS EMITS: "RAW" PAGES
----------------------------
The generator produces the pages as they come out of the templates, with the
GitHub Pages canonical/OG URLs, the footer credit still present, relative
paths, no colour legend and no pre-rendered tables. The four scripts in
build/ are what finish them - see build/README.md for the pipeline and the
order. So the correct way to check this stage is:

    generate  ->  fix_matchup_paths  ->  apply_ui_tweaks
              ->  fix_canonical_urls ->  prerender_matchup_tables
              ->  diff against HEAD

Keeping the two stages separate means the generator stays a faithful
reconstruction of the original rather than absorbing five later fixes.

HOW A PAGE IS BUILT
-------------------
Each page is its template with exactly two lines replaced - the placeholder
<title> and <meta name="description"> - by a per-page head block. Everything
else in the file, CSS and JavaScript included, comes from the template
verbatim. That is why the pages are byte-identical to each other outside the
head: the generator never touched the body.

One quirk is reproduced deliberately. The templates carry their own
`<meta property="og:type">` on the line after the description, and the
injected block emits og:type as well, so every generated page has the tag
twice. It is harmless, it is what the committed pages contain, and
"byte-identical" beats "tidier".

INPUTS
------
  data/m/<slug>.json   one per head-to-head page  -> m/<slug>.html
  data/p/<slug>.json   one per player page        -> p/<slug>.html
  m/template.html, p/template.html

The shared files in data/ (meta.json, player_index.json, pairs_top.json,
pairs_recent.json, hero_matchups.json) drive index.html, which is hand-
maintained and NOT regenerated here. meta.json is read only to report the
generated_at stamp and the season list.

    python build/generate_matchup_pages.py [--out DIR] [--dry-run] [--only SLUG ...]

--out writes elsewhere (for diffing) instead of over m/ and p/. Without it the
pages are written in place, which is what a real regeneration does.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The canonical/OG host the generator writes. fix_canonical_urls.py rewrites
# this to https://hoopsmatic.com/matchups/ afterwards; see build/README.md.
BASE = "https://jsierrahoopshype.github.io/nba-matchups/"

POS_LABEL = {"G": "Guard", "F": "Forward", "C": "Center"}

# The two template lines the generator replaces, verbatim.
M_PLACEHOLDER = (
    "<title>NBA Head-to-Head Matchup | HoopsMatic</title>\n"
    '<meta name="description" content="NBA head-to-head matchup stats: career '
    'H2H possessions, points, FG% between two players since 2017-18.">\n'
)
P_PLACEHOLDER = (
    "<title>NBA Matchup Database | HoopsMatic</title>\n"
    '<meta name="description" content="NBA player matchup stats: career H2H '
    "possessions, points, FG% on every defender they've faced since 2017-18.\">\n"
)


def m_head(slug: str, data: dict) -> str:
    """The per-page head block for a head-to-head page."""
    a = data["playerA"]["name"]
    b = data["playerB"]["name"]
    url = "%sm/%s.html" % (BASE, slug)
    desc = ("Head-to-head NBA stats between %s and %s since 2017-18. "
            "Possessions, points, FG%% in both directions, every season." % (a, b))
    return (
        "<title>%s vs %s — NBA Head-to-Head Stats Since 2017-18 | HoopsMatic</title>\n"
        '<link rel="canonical" href="%s">\n'
        '<meta property="og:title" content="%s vs %s — NBA H2H Stats | HoopsMatic">\n'
        '<meta property="og:description" content="%s">\n'
        '<meta property="og:type" content="article">\n'
        '<meta property="og:url" content="%s">\n'
        '<meta property="og:site_name" content="HoopsMatic">\n'
        '<meta name="twitter:card" content="summary">\n'
        '<meta name="twitter:title" content="%s vs %s — NBA H2H Stats">\n'
        '<meta name="twitter:description" content="%s">\n'
        '<meta name="description" content="%s">\n'
        % (a, b, url, a, b, desc, url, a, b, desc, desc)
    )


def p_head(slug: str, data: dict) -> str:
    """The per-page head block for a player page."""
    name = data["name"]
    url = "%sp/%s.html" % (BASE, slug)
    pos = POS_LABEL.get(data.get("pos") or "", "")
    country = data.get("country") or ""

    # The parenthetical appears only when both the position and the country
    # are known. NOTE: the data contains no player with a country but no
    # position, so "both present", "country present" and "iso present" are
    # indistinguishable here - all three agree on every one of the 1,224
    # pages. "Both present" is the reading used.
    qualifier = " (%s, %s)" % (pos, country) if (pos and country) else ""

    desc = ("%s's career NBA matchup data since 2017-18. Possessions, points, "
            "FG%% on every defender they've faced, plus every offensive player "
            "they've guarded." % name)

    # Compact separators and non-escaped unicode, matching the committed pages
    # (e.g. "Nikola Jokić" appears literally, not as ć).
    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Person",
        "name": name,
        "url": url,
        "jobTitle": "NBA Player",
    }, ensure_ascii=False, separators=(",", ":"))

    return (
        "<title>%s%s — NBA Matchup Stats Since 2017-18 | HoopsMatic</title>\n"
        '<link rel="canonical" href="%s">\n'
        '<meta property="og:title" content="%s — NBA Matchup Stats | HoopsMatic">\n'
        '<meta property="og:description" content="%s">\n'
        '<meta property="og:type" content="profile">\n'
        '<meta property="og:url" content="%s">\n'
        '<meta property="og:site_name" content="HoopsMatic">\n'
        '<meta name="twitter:card" content="summary">\n'
        '<meta name="twitter:title" content="%s — NBA Matchup Stats">\n'
        '<meta name="twitter:description" content="%s">\n'
        '<script type="application/ld+json">%s</script>\n'
        '<meta name="description" content="%s">\n'
        % (name, qualifier, url, name, desc, url, name, desc, ld, desc)
    )


def render(template: str, placeholder: str, head: str, rel: str) -> str:
    n = template.count(placeholder)
    if n != 1:
        raise ValueError("%s: title/description placeholder found %d times, expected 1"
                         % (rel, n))
    return template.replace(placeholder, head, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None,
                    help="write pages under this directory instead of in place "
                         "(creates <out>/m and <out>/p)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written without writing")
    ap.add_argument("--only", nargs="*", default=None,
                    help="limit to these slugs")
    ap.add_argument("--templates", default=None,
                    help="directory holding m/template.html and p/template.html "
                         "(default: the repo itself)")
    args = ap.parse_args()

    tpl_root = Path(args.templates).resolve() if args.templates else REPO
    out_root = Path(args.out).resolve() if args.out else REPO

    meta_path = REPO / "data" / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print("data/meta.json: generated_at=%s, seasons=%s"
              % (meta.get("generated_at"), ",".join(meta.get("seasons_loaded", []))))

    specs = [
        ("m", M_PLACEHOLDER, m_head),
        ("p", P_PLACEHOLDER, p_head),
    ]

    written = unchanged = 0
    errors: list[str] = []

    for sub, placeholder, head_fn in specs:
        tpl_file = tpl_root / sub / "template.html"
        if not tpl_file.exists():
            errors.append("missing template %s" % tpl_file)
            continue
        template = tpl_file.read_text(encoding="utf-8")

        data_dir = REPO / "data" / sub
        if not data_dir.is_dir():
            errors.append("missing data directory %s" % data_dir)
            continue

        out_dir = out_root / sub
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)

        for data_file in sorted(data_dir.glob("*.json")):
            slug = data_file.stem
            if args.only and slug not in args.only:
                continue
            rel = "%s/%s.html" % (sub, slug)
            try:
                data = json.loads(data_file.read_text(encoding="utf-8"))
                html = render(template, placeholder, head_fn(slug, data), rel)
            except Exception as exc:                  # noqa: BLE001 - reported
                errors.append("%s: %s: %s" % (rel, type(exc).__name__, exc))
                continue

            target = out_dir / ("%s.html" % slug)
            if target.exists() and target.read_text(encoding="utf-8") == html:
                unchanged += 1
                continue
            written += 1
            if not args.dry_run:
                target.write_text(html, encoding="utf-8")

    verb = "would write" if args.dry_run else "wrote"
    print("%s: %d page(s), unchanged: %d, errors: %d" % (verb, written, unchanged, len(errors)))
    for e in errors[:20]:
        print("  ! %s" % e, file=sys.stderr)
    if len(errors) > 20:
        print("  ... and %d more" % (len(errors) - 20), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
