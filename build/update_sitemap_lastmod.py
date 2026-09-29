#!/usr/bin/env python3
"""Give every sitemap.xml URL an accurate <lastmod>: the date that page's
content last changed, not the date of the last build.

For each <loc> it hashes what a visitor of that URL gets:

    https://hoopsmatic.com/matchups/        index.html + the data files it
                                            loads on start (player_index,
                                            hero_matchups, pairs_recent)
    .../matchups/m/<slug>.html              m/<slug>.html + data/m/<slug>.json
    .../matchups/p/<slug>.html              p/<slug>.html + data/p/<slug>.json

(the JSON is what the page's JS renders every view other than the baked
default from, so a data refresh that only changes another phase or window
still counts as a change). The hash is compared with the one stored for that
URL in build/sitemap-hashes.json:

    same hash       keep the stored date
    new or changed  today's date (UTC), and store the new hash

so a build with no content change leaves every <lastmod> exactly as it was;
a URL's date never moves just because a build ran. The first run, with no
hashes stored yet, dates every URL today.

VOLATILE CONTENT: nothing in the pages or their data changes from one build
to the next unless the content does (no build timestamps, no random ids), so
nothing is excluded from the hash. data/meta.json, which carries the fetch
time, is deliberately not part of any hash. If something volatile is ever
added to the pages, strip it in `content_hash` via VOLATILE.

Only <lastmod> is written: <loc>, <changefreq> and <priority> are untouched,
and a <lastmod> is added right after <loc> where one is missing. Every <loc>
must be on https://hoopsmatic.com/matchups/ and map to a file in the repo;
anything else fails the run rather than being guessed at.

    python build/update_sitemap_lastmod.py [--dry-run] [--check] [--today YYYY-MM-DD]

Runs last in the build (step 7 of the Action), after every script that can
change a page.
"""

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITEMAP = REPO / "sitemap.xml"
STORE = REPO / "build" / "sitemap-hashes.json"
PREFIX = "https://hoopsmatic.com/matchups/"

INDEX_DATA = ("data/player_index.json", "data/hero_matchups.json", "data/pairs_recent.json")

# (regex, replacement) pairs stripped from page bytes before hashing.
# Empty: the pages carry nothing that changes between builds on its own.
VOLATILE = []

URL = re.compile(r"(<url>\s*<loc>)([^<]*)(</loc>)(\s*<lastmod>[^<]*</lastmod>)?")


def sources(loc: str):
    """Repo-relative files whose bytes make up this URL's content."""
    if not loc.startswith(PREFIX):
        raise ValueError("<loc> not on %s: %s" % (PREFIX, loc))
    path = loc[len(PREFIX):]
    if path in ("", "index.html"):
        return ["index.html"] + list(INDEX_DATA)
    m = re.fullmatch(r"([mp])/([a-z0-9-]+)\.html", path)
    if not m:
        raise ValueError("unrecognised <loc>: %s" % loc)
    return [path, "data/%s/%s.json" % (m.group(1), m.group(2))]


def content_hash(files) -> str:
    h = hashlib.sha256()
    for rel in files:
        p = REPO / rel
        if not p.exists():
            raise ValueError("missing file for sitemap URL: %s" % rel)
        data = p.read_bytes()
        if rel.endswith(".html"):
            for pat, repl in VOLATILE:
                data = pat.sub(repl, data)
        h.update(rel.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def load_store():
    if not STORE.exists():
        return {}
    return json.loads(STORE.read_text(encoding="utf-8")).get("urls", {})


def dump_store(urls) -> bytes:
    doc = {"_about": "Content hash and <lastmod> per sitemap URL. Written by "
                     "build/update_sitemap_lastmod.py; commit it with sitemap.xml.",
           "urls": {k: urls[k] for k in sorted(urls)}}
    return (json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if anything would change")
    ap.add_argument("--today", default=None, help="date to stamp on changed URLs (default: UTC today)")
    args = ap.parse_args()
    today = args.today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        print("--today must be YYYY-MM-DD", file=sys.stderr)
        return 2

    xml = SITEMAP.read_bytes().decode("utf-8")
    old = load_store()
    new_store, errors = {}, []
    stats = {"unchanged": 0, "changed": 0, "new": 0}

    def fix(m):
        loc = m.group(2)
        try:
            digest = content_hash(sources(loc))
        except ValueError as exc:
            errors.append(str(exc))
            return m.group(0)
        prev = old.get(loc)
        if prev and prev.get("hash") == digest and prev.get("lastmod"):
            date = prev["lastmod"]
            stats["unchanged"] += 1
        else:
            date = today
            stats["changed" if prev else "new"] += 1
        new_store[loc] = {"hash": digest, "lastmod": date}
        indent = re.search(r"\n([ \t]*)<loc>", m.group(0))
        pad = indent.group(1) if indent else "    "
        return "%s%s%s\n%s<lastmod>%s</lastmod>" % (m.group(1), loc, m.group(3), pad, date)

    new_xml = URL.sub(fix, xml)
    seen = set(new_store)
    if len(seen) != len(URL.findall(xml)):
        errors.append("duplicate <loc> entries in sitemap.xml")
    dropped = sorted(set(old) - seen)

    for e in errors:
        print("  ! " + e, file=sys.stderr)
    if errors:
        return 1

    new_store_bytes = dump_store(new_store)
    old_store_bytes = STORE.read_bytes() if STORE.exists() else b""
    will_change = new_xml != xml or new_store_bytes != old_store_bytes
    print("update_sitemap_lastmod: %d URL(s): %d unchanged (date kept), %d changed, %d new"
          " -> %s; %d dropped from the store"
          % (len(seen), stats["unchanged"], stats["changed"], stats["new"], today, len(dropped)))
    print("  %s" % ("sitemap.xml / sitemap-hashes.json %s" %
                    (("would change" if (args.dry_run or args.check) else "updated")
                     if will_change else "already current")))
    if will_change and not (args.dry_run or args.check):
        SITEMAP.write_bytes(new_xml.encode("utf-8"))
        STORE.write_bytes(new_store_bytes)
    return 1 if (args.check and will_change) else 0


if __name__ == "__main__":
    raise SystemExit(main())
