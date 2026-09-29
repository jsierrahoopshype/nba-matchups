#!/usr/bin/env python3
"""Pre-render each m/ and p/ page's own title into its static <head>.

The page JS sets a per-page title once its data loads:

    m/  document.title = `${state.data.playerA.name} vs ${state.data.playerB.name} — NBA Head-to-Head Stats | HoopsMatic`;
    p/  document.title = `${state.data.name} — NBA Matchup Stats | HoopsMatic`;

but the static <title>, og:title and twitter:title the page ships with say
something else, so a crawler that doesn't run the JS, and every social
preview, sees a different title from the one a visitor's tab shows. This
writes the exact string the JS will set - the template is read from each
page's own <script> and filled from the same data file the page fetches
(data/m/<slug>.json, data/p/<slug>.json) - into:

    <title>                          (the JS's exact string, text-escaped)
    <meta property="og:title">       (the same string)
    <meta name="twitter:title">      (the same string)

Nothing else changes: not the H1, the tables, the legend, the "More matchups"
block, the meta descriptions, the canonicals, or any <script>. index.html is
not touched. A page whose JS has no document.title, or uses a placeholder this
script doesn't know, is reported as an error, not guessed.

Idempotent: a second run changes 0 files. --dry-run counts without writing;
--check exits 1 if any page would change.

    python build/prerender_page_titles.py [--dry-run] [--check] [--only SLUG ...]

Run it after every regeneration of m/ and/or p/ (step 6 of the Action).
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP = {"template"}

JS_TITLE = re.compile(r"document\.title = `([^`]*)`;")
PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
TITLE = re.compile(r"<title>[^<]*</title>")
OG = re.compile(r'<meta property="og:title" content="[^"]*">')
TW = re.compile(r'<meta name="twitter:title" content="[^"]*">')


def text_escape(s: str) -> str:
    """For <title> text: parses back to exactly `s`."""
    return s.replace("&", "&amp;").replace("<", "&lt;")


def attr_escape(s: str) -> str:
    """For a double-quoted attribute; apostrophes stay raw, as elsewhere in the pages."""
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


def lookup(expr: str, data: dict):
    """`state.data.playerA.name` -> data["playerA"]["name"]. Plain property
    paths only; anything else is refused rather than evaluated."""
    if not re.fullmatch(r"state\.data(\.[A-Za-z_][A-Za-z0-9_]*)+", expr):
        raise ValueError("unsupported placeholder ${%s}" % expr)
    v = data
    for key in expr.split(".")[2:]:
        if not isinstance(v, dict) or key not in v:
            raise ValueError("${%s}: no such field in the data file" % expr)
        v = v[key]
    if not isinstance(v, str):
        raise ValueError("${%s}: not a string" % expr)
    return v


def page_title(text: str, data: dict) -> str:
    found = JS_TITLE.findall(text)
    if len(found) != 1:
        raise ValueError("expected one document.title assignment, found %d" % len(found))
    return PLACEHOLDER.sub(lambda m: lookup(m.group(1), data), found[0])


def rewrite(text: str, title: str) -> str:
    head_end = text.index("</head>")
    head, rest = text[:head_end], text[head_end:]
    for pat, new in ((TITLE, "<title>%s</title>" % text_escape(title)),
                     (OG, '<meta property="og:title" content="%s">' % attr_escape(title)),
                     (TW, '<meta name="twitter:title" content="%s">' % attr_escape(title))):
        n = len(pat.findall(head))
        if pat is TITLE and n != 1:
            raise ValueError("expected one <title> in <head>, found %d" % n)
        if n > 1:
            raise ValueError("more than one %s in <head>" % pat.pattern[:30])
        head = pat.sub(lambda _m, new=new: new, head, count=1)
    return head + rest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if any page would change")
    ap.add_argument("--only", nargs="*", default=None, help="page slugs to process")
    args = ap.parse_args()

    changed = unchanged = 0
    errors = []
    for kind in ("m", "p"):
        for path in sorted((REPO / kind).glob("*.html")):
            if path.stem in SKIP or (args.only is not None and path.stem not in args.only):
                continue
            rel = path.relative_to(REPO).as_posix()
            data_path = REPO / "data" / kind / ("%s.json" % path.stem)
            if not data_path.exists():
                errors.append("%s: no %s" % (rel, data_path.relative_to(REPO).as_posix()))
                continue
            text = path.read_bytes().decode("utf-8")        # bytes: line endings untouched
            try:
                title = page_title(text, json.loads(data_path.read_text(encoding="utf-8")))
                new = rewrite(text, title)
            except ValueError as exc:
                errors.append("%s: %s" % (rel, exc))
                continue
            if new == text:
                unchanged += 1
                continue
            changed += 1
            if not (args.dry_run or args.check):
                path.write_bytes(new.encode("utf-8"))

    verb = "would update" if (args.dry_run or args.check) else "updated"
    print("prerender_page_titles: %s %d page(s), %d already current" % (verb, changed, unchanged))
    for e in errors:
        print("  ! " + e, file=sys.stderr)
    if errors:
        return 1
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
