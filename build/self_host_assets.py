#!/usr/bin/env python3
"""Point the Matchup Database's fonts and country flags at hoopsmatic.com.

The pages load DM Sans + JetBrains Mono from Google Fonts and country flags
from flagcdn.com, so every visit sent the visitor's IP address to Google and
flagcdn. The hoopsmatic.com Worker already serves both from its own domain
(SELF-HOSTED FONTS AND LIBRARIES in hoopsmatic-worker/src/index.js):

    https://hoopsmatic.com/fonts/css2?<the same Google css2 query>
    https://hoopsmatic.com/img/flagcdn/<size>/<code>.png

but it never rewrites the /matchups/ route (a standing Worker rule), so this
repo does it itself, with the exact rewrite the Worker applies everywhere else:

  * the two preconnect hints to fonts.googleapis.com / fonts.gstatic.com are
    removed (a preconnect alone already contacts Google);
  * https://fonts.googleapis.com/css2?  ->  https://hoopsmatic.com/fonts/css2?
  * https://flagcdn.com/                ->  https://hoopsmatic.com/img/flagcdn/
    (baked <img> tags and the JS templates that build flag URLs at run time).

Absolute hoopsmatic.com URLs, so the github.io preview keeps working too (the
Worker sends Access-Control-Allow-Origin: * on these files).

Runs after every step that can write a flagcdn or Google Fonts address
(prerender_matchup_tables.py bakes flagcdn flags) and before
update_sitemap_lastmod.py, which hashes the pages as if this rewrite had not
happened (its HOSTING entries), so moving the hosting never moves a <lastmod>.
Idempotent: a page already rewritten is left byte for byte as it is.

    python build/self_host_assets.py [--check]

--check changes nothing and exits 1 if any page still points at Google Fonts
or flagcdn.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PRECONNECTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
)
REWRITES = (
    (PRECONNECTS, ""),
    ("https://fonts.googleapis.com/css2?", "https://hoopsmatic.com/fonts/css2?"),
    ("https://flagcdn.com/", "https://hoopsmatic.com/img/flagcdn/"),
)
# Anything still matching after the rewrite fails the run, so a new form the
# generator starts producing (a different query, //flagcdn.com, ...) is caught
# instead of quietly sending visitors to a third party again.
LEFTOVERS = ("fonts.googleapis.com", "fonts.gstatic.com", "flagcdn.com/")


def pages():
    return [REPO / "index.html"] + sorted((REPO / "m").glob("*.html")) + sorted((REPO / "p").glob("*.html"))


def rewrite(text: str) -> str:
    for old, new in REWRITES:
        text = text.replace(old, new)
    return text


def leftovers(text: str):
    # hoopsmatic.com/img/flagcdn/ contains "flagcdn/" but not "flagcdn.com/".
    return [x for x in LEFTOVERS if x in text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if any page still uses a third party")
    args = ap.parse_args()

    changed = done = 0
    bad = []
    for path in pages():
        raw = path.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n")
        new = text if args.check else rewrite(text)
        left = leftovers(new)
        if left:
            bad.append("%s: %s" % (path.relative_to(REPO), ", ".join(left)))
        if new != text:
            # LF on every OS (see build/README.md, "Line endings").
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
            changed += 1
        else:
            done += 1

    print("self_host_assets: %d page(s) rewritten, %d already on hoopsmatic.com" % (changed, done))
    if bad:
        print("!! still loading from a third party:", file=sys.stderr)
        for b in bad[:20]:
            print("   " + b, file=sys.stderr)
        if len(bad) > 20:
            print("   ... and %d more" % (len(bad) - 20), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
