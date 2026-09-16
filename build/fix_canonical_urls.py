#!/usr/bin/env python3
"""Point canonical / OG / JSON-LD / sitemap URLs at hoopsmatic.com.

The section is served publicly at

    https://hoopsmatic.com/matchups/

but the generator writes every page's self-referencing URL against the
GitHub Pages host

    https://jsierrahoopshype.github.io/nba-matchups/

which tells search engines to index the GitHub copy instead. This rewrites
that prefix to the hoopsmatic.com one in:

  * `<link rel="canonical" href="...">`
  * `<meta property="og:url" content="...">`
  * `<meta name="twitter:url" content="...">`  (none present today, handled
    so a future generator change is covered)
  * JSON-LD `"url"` and `"@id"` string values
  * `<loc>` entries in sitemap.xml
  * the `Sitemap:` line in robots.txt

Scope: `m/*.html`, `p/*.html`, `index.html`, `sitemap.xml` and `robots.txt`.

IMPORTANT: the headshot assets live under a *different* GitHub Pages repo
path, `https://jsierrahoopshype.github.io/nba-headshots/...`. Those are
images, not pages, and must keep pointing at GitHub Pages. Every pattern
below is anchored on the `/nba-matchups/` prefix, so the headshot URLs are
never matched.

The rewrite is deliberately attribute-scoped rather than a blind
search-and-replace: a bare prefix swap would also hit any future link that
genuinely wants to point at the GitHub copy. After rewriting, the script
re-checks each file and reports any occurrence of the old prefix that its
patterns did not cover, instead of leaving it silently behind.

Idempotent: pages already carrying the new prefix simply have nothing left
to match, so re-running on an already-fixed tree is a no-op. Use --dry-run
to see the counts without writing.

    python build/fix_canonical_urls.py [--dry-run]

Run it after every regeneration of m/, p/, sitemap.xml and robots.txt.
It does not touch the ROOT / ${ROOT} path logic from fix_matchup_paths.py,
the heat legends from apply_ui_tweaks.py, or data/.
"""

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OLD = "https://jsierrahoopshype.github.io/nba-matchups/"
NEW = "https://hoopsmatic.com/matchups/"

# Anything under this prefix is an image asset and stays on GitHub Pages.
KEEP = "https://jsierrahoopshype.github.io/nba-headshots/"

_old = re.escape(OLD)

# (label, compiled pattern). Each pattern captures the part before the URL in
# group 1 and the path after the prefix in group 2, so the replacement only
# swaps the host+prefix.
PATTERNS = [
    ("canonical", re.compile(r'(<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\'])'
                             + _old + r'([^"\']*["\'])')),
    ("og:url", re.compile(r'(<meta\b[^>]*\bproperty=["\']og:url["\'][^>]*\bcontent=["\'])'
                          + _old + r'([^"\']*["\'])')),
    ("twitter:url", re.compile(r'(<meta\b[^>]*\bname=["\']twitter:url["\'][^>]*\bcontent=["\'])'
                               + _old + r'([^"\']*["\'])')),
    # JSON-LD "url": "..." and "@id": "..." (the blocks are minified, but allow
    # optional whitespace around the colon anyway).
    ("json-ld url/@id", re.compile(r'("(?:url|@id)"\s*:\s*")' + _old + r'([^"]*")')),
    ("sitemap <loc>", re.compile(r'(<loc>)' + _old + r'([^<]*</loc>)')),
    # robots.txt: "Sitemap: https://.../sitemap.xml"
    ("robots Sitemap:", re.compile(r'(^Sitemap:[ \t]*)' + _old + r'(\S*)$', re.MULTILINE)),
]


def rewrite(text: str) -> tuple[str, dict[str, int]]:
    """Return (new_text, {label: replacements})."""
    counts: dict[str, int] = {}
    for label, pat in PATTERNS:
        text, n = pat.subn(lambda m: m.group(1) + NEW + m.group(2), text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return text, counts


def targets() -> list[Path]:
    out: list[Path] = []
    for sub in ("m", "p"):
        out.extend(sorted((REPO / sub).glob("*.html")))
    for name in ("index.html", "sitemap.xml", "robots.txt"):
        f = REPO / name
        if f.exists():
            out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    changed = skipped = 0
    totals: dict[str, int] = {}
    leftovers: list[str] = []
    headshots_before = headshots_after = 0

    for path in targets():
        text = path.read_text(encoding="utf-8")
        headshots_before += text.count(KEEP)

        new, counts = rewrite(text)

        # Anything still on the old prefix was not covered by the patterns
        # above; report it rather than leaving it behind unnoticed.
        if OLD in new:
            leftovers.append("%s: %d occurrence(s) of the old prefix not matched"
                             % (path.relative_to(REPO), new.count(OLD)))

        headshots_after += new.count(KEEP)

        if new == text:
            skipped += 1
            continue
        changed += 1
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        if not args.dry_run:
            path.write_text(new, encoding="utf-8")

    verb = "would change" if args.dry_run else "changed"
    print("%s: %d file(s), skipped (already correct): %d" % (verb, changed, skipped))
    for label, _ in PATTERNS:
        if totals.get(label):
            print("  %-16s %d" % (label + ":", totals[label]))
    print("  nba-headshots URLs: %d before, %d after (must be equal)"
          % (headshots_before, headshots_after))

    ok = headshots_before == headshots_after and not leftovers
    if headshots_before != headshots_after:
        print("  ! headshot URL count changed", file=sys.stderr)
    for line in leftovers:
        print("  ! %s" % line, file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
