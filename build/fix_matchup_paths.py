#!/usr/bin/env python3
"""
Rewrite relative internal paths in generated matchup (m/) and player (p/) pages
so they work both on GitHub Pages (/nba-matchups/) and on hoopsmatic.com,
where a Cloudflare Worker injects <base href="/matchups/"> into every page.

Under that injected <base>, "../data/..." resolves to the site root and 404s.
The fix derives the site root from location.pathname at runtime and builds
every internal path from it with absolute paths, which <base> does not affect:

    const ROOT = location.pathname.replace(/\/(m|p)\/[^/]*$/, "/");

Idempotent: a file that already contains the ROOT marker is skipped, so the
script is safe to re-run after any regeneration of m/ and p/.

Usage (from the repo root, or anywhere):
    python build/fix_matchup_paths.py            # fix m/ and p/
    python build/fix_matchup_paths.py --dry-run  # report only, write nothing
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIRS = ["m", "p"]

MARKER = 'const ROOT = location.pathname.replace('

# JS block injected at the top of the page's inline <script>. It defines ROOT
# and points the static back link (<a class="back" href="#">, see
# REPLACEMENTS) to `${ROOT}index.html` once the DOM is available.
ROOT_JS = (
    '\n'
    '// Site root derived from the current URL, so paths work on GitHub Pages\n'
    '// (/nba-matchups/) and on hoopsmatic.com (/matchups/ via <base href>).\n'
    'const ROOT = location.pathname.replace(/\\/(m|p)\\/[^/]*$/, "/");\n'
    '(function fixBackLink() {\n'
    '  const fix = () => document.querySelectorAll("a.back")\n'
    '    .forEach(a => a.setAttribute("href", `${ROOT}index.html`));\n'
    '  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fix);\n'
    '  else fix();\n'
    '})();\n'
)

# Plain string replacements, applied in order.
REPLACEMENTS = [
    # Static back link: no relative path can work on both hosts, so leave a
    # placeholder and let fixBackLink() set the real href at runtime.
    ('<a class="back" href="../index.html">', '<a class="back" href="#">'),
    ("fetch(`../data/m/${", "fetch(`${ROOT}data/m/${"),
    ("fetch(`../data/p/${", "fetch(`${ROOT}data/p/${"),
    ("fetch(`../data/pairs_top.json`)", "fetch(`${ROOT}data/pairs_top.json`)"),
    ("`../m/${pairKey}.html`", "`${ROOT}m/${pairKey}.html`"),
    ('href="../p/${esc(p.slug)}.html"', 'href="${ROOT}p/${esc(p.slug)}.html"'),
    # Opponent fallback link in p/ pages: "<slug>.html" -> "${ROOT}p/<slug>.html"
    ("`${esc(o.slug)}.html`", "`${ROOT}p/${esc(o.slug)}.html`"),
]

# The page's main inline script is a bare <script> tag - ROOT_JS goes right
# after it. Tags with attributes (src=..., type="application/ld+json") are
# deliberately not matched: injecting JS into the JSON-LD block would break it.
SCRIPT_OPEN = re.compile(r"<script\s*>", re.IGNORECASE)


def fix_html(text: str):
    """Return (new_text, changed). changed=False when already fixed or nothing to do."""
    if MARKER in text:
        return text, False

    new = text
    for old, rep in REPLACEMENTS:
        new = new.replace(old, rep)

    m = SCRIPT_OPEN.search(new)
    if not m:
        return text, False  # no inline script to anchor ROOT on; leave untouched

    new = new[: m.end()] + ROOT_JS + new[m.end():]
    return new, new != text


def main(argv):
    dry_run = "--dry-run" in argv
    changed = skipped = untouched = 0
    changed_files = []

    for d in DIRS:
        for path in sorted((REPO_ROOT / d).glob("*.html")):
            text = path.read_text(encoding="utf-8")
            new, did = fix_html(text)
            if MARKER in text:
                skipped += 1
                continue
            if not did:
                untouched += 1
                print(f"WARN no changes possible: {path.relative_to(REPO_ROOT)}")
                continue
            if not dry_run:
                path.write_text(new, encoding="utf-8", newline="")
            changed += 1
            changed_files.append(path.relative_to(REPO_ROOT))

    verb = "would change" if dry_run else "changed"
    print(f"{verb}: {changed}  already fixed (skipped): {skipped}  untouched: {untouched}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
