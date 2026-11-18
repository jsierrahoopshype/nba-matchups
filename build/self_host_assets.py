#!/usr/bin/env python3
"""Point the Matchup Database's fonts, flags and headshots at hoopsmatic.com.

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

Headshots (second pass, November 2026) the same way: the Worker serves the
nba-headshots repo at https://hoopsmatic.com/img/nba-headshots/ (same file
names), so

  * https://jsierrahoopshype.github.io/nba-headshots/
        ->  https://hoopsmatic.com/img/nba-headshots/
  * the pages' loadHeadshotsIndex(), which asked api.github.com for the
    nba-headshots file tree on every visit, now reads the committed list
    data/headshots/<variant>.json (written by update_headshot_list.py) from
    the page's own site. Same map (playerId -> file name), same fallback when
    it does not load. The old localStorage cache of the GitHub answer is not
    needed any more (the list is a plain cached file) and is no longer read.

Absolute hoopsmatic.com URLs, so the github.io preview keeps working too (the
Worker sends Access-Control-Allow-Origin: * on these files).

Runs after every step that can write a flagcdn or Google Fonts address
(prerender_matchup_tables.py bakes flagcdn flags) and before
update_sitemap_lastmod.py, which hashes the pages as if this rewrite had not
happened (its HOSTING entries), so moving the hosting never moves a <lastmod>.
Idempotent: a page already rewritten is left byte for byte as it is.

    python build/self_host_assets.py [--check]

--check changes nothing and exits 1 if any page still points at Google Fonts,
flagcdn, github.io or api.github.com.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PRECONNECTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
)
# index.html: the GitHub tree API constants and loader.
INDEX_CONSTS_OLD = (
    'const HEADSHOTS_TREE_API = "https://api.github.com/repos/jsierrahoopshype/nba-headshots/git/trees/main?recursive=1";\n'
    'const HEADSHOTS_CACHE_KEY = "hoopsmatic.headshots.facefill.v1";\n'
    'const HEADSHOTS_CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h\n'
)
INDEX_CONSTS_NEW = (
    '// Committed list of available face-fill files (build/update_headshot_list.py).\n'
    'const HEADSHOTS_LIST_URL = "data/headshots/face-fill.json";\n'
)
INDEX_LOADER_OLD = """// Load the nba-headshots repo file list (from cache if fresh, else GitHub API).
// Populates state.headshotsById with playerId -> filename.
async function loadHeadshotsIndex() {
  // Try cache
  try {
    const cached = JSON.parse(localStorage.getItem(HEADSHOTS_CACHE_KEY) || "null");
    if (cached && cached.fetchedAt && (Date.now() - cached.fetchedAt) < HEADSHOTS_CACHE_TTL_MS) {
      for (const [k, v] of Object.entries(cached.map || {})) {
        state.headshotsById.set(k, v);
      }
      state.headshotsReady = true;
      return;
    }
  } catch (e) { /* ignore */ }

  // Fetch fresh
  try {
    const resp = await fetch(HEADSHOTS_TREE_API);
    if (!resp.ok) throw new Error(`tree API ${resp.status}`);
    const data = await resp.json();
    if (!data.tree) throw new Error("no tree in response");
    const map = {};
    for (const entry of data.tree) {
      // path format: players/headshots/face-fill/203999-nikola-joki.webp
      if (!entry.path || entry.type !== "blob") continue;
      if (!entry.path.startsWith("players/headshots/face-fill/")) continue;
      if (!entry.path.endsWith(".webp")) continue;
      const filename = entry.path.split("/").pop();
      // First chunk before "-" is the player ID
      const dashIdx = filename.indexOf("-");
      if (dashIdx <= 0) continue;
      const id = filename.substring(0, dashIdx);
      map[id] = filename;
    }
    for (const [k, v] of Object.entries(map)) state.headshotsById.set(k, v);
    state.headshotsReady = true;
    try {
      localStorage.setItem(HEADSHOTS_CACHE_KEY, JSON.stringify({
        fetchedAt: Date.now(),
        map,
      }));
    } catch (e) { /* localStorage quota or disabled - silently skip */ }
  } catch (e) {
    console.warn("Headshots tree API failed, falling back to deterministic URLs:", e);
    state.headshotsReady = false;
  }
}
"""
INDEX_LOADER_NEW = """// Load the headshot file list committed with the site (no GitHub API call).
// Populates state.headshotsById with playerId -> filename.
async function loadHeadshotsIndex() {
  try {
    const resp = await fetch(HEADSHOTS_LIST_URL);
    if (!resp.ok) throw new Error(`headshot list ${resp.status}`);
    const map = await resp.json();
    for (const [k, v] of Object.entries(map)) state.headshotsById.set(k, v);
    state.headshotsReady = true;
  } catch (e) {
    console.warn("Headshot list failed, falling back to deterministic URLs:", e);
    state.headshotsReady = false;
  }
}
"""

# m/ pages (and m/template.html): the same, for the 320px files.
M_LOADER_OLD = """// Load nba-headshots tree from GitHub API or localStorage cache
const HEADSHOTS_TREE_API = "https://api.github.com/repos/jsierrahoopshype/nba-headshots/git/trees/main?recursive=1";
const HEADSHOTS_CACHE_KEY = "hoopsmatic.headshots.facefill.v1";
const HEADSHOTS_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

async function loadHeadshotsIndex() {
  try {
    const cached = JSON.parse(localStorage.getItem(HEADSHOTS_CACHE_KEY) || "null");
    if (cached && cached.fetchedAt && (Date.now() - cached.fetchedAt) < HEADSHOTS_CACHE_TTL_MS) {
      for (const [k, v] of Object.entries(cached.map || {})) {
        state.headshotsById.set(k, v);
      }
      return;
    }
  } catch (e) { /* ignore */ }
  try {
    const resp = await fetch(HEADSHOTS_TREE_API);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.tree) return;
    const map = {};
    for (const entry of data.tree) {
      if (!entry.path || entry.type !== "blob") continue;
      if (!entry.path.startsWith("players/headshots/face-fill-320/")) continue;
      const filename = entry.path.split("/").pop();
      const dashIdx = filename.indexOf("-");
      if (dashIdx <= 0) continue;
      const id = filename.substring(0, dashIdx);
      map[id] = filename;
    }
    for (const [k, v] of Object.entries(map)) state.headshotsById.set(k, v);
    try {
      localStorage.setItem(HEADSHOTS_CACHE_KEY, JSON.stringify({ fetchedAt: Date.now(), map }));
    } catch (e) { /* ignore */ }
  } catch (e) {
    console.warn("Headshots tree fetch failed; using deterministic URLs:", e);
  }
}
"""
M_LOADER_NEW = """// Load the headshot file list committed with the site (no GitHub API call):
// data/headshots/face-fill-320.json, playerId -> filename.
async function loadHeadshotsIndex() {
  try {
    const resp = await fetch(`${ROOT}data/headshots/face-fill-320.json`);
    if (!resp.ok) return;
    const map = await resp.json();
    for (const [k, v] of Object.entries(map)) state.headshotsById.set(k, v);
  } catch (e) {
    console.warn("Headshot list fetch failed; using deterministic URLs:", e);
  }
}
"""

REWRITES = (
    (PRECONNECTS, ""),
    ("https://fonts.googleapis.com/css2?", "https://hoopsmatic.com/fonts/css2?"),
    ("https://flagcdn.com/", "https://hoopsmatic.com/img/flagcdn/"),
    ("https://jsierrahoopshype.github.io/nba-headshots/", "https://hoopsmatic.com/img/nba-headshots/"),
    (INDEX_CONSTS_OLD, INDEX_CONSTS_NEW),
    (INDEX_LOADER_OLD, INDEX_LOADER_NEW),
    (M_LOADER_OLD, M_LOADER_NEW),
)
# Anything still matching after the rewrite fails the run, so a new form the
# generator starts producing (a different query, //flagcdn.com, ...) is caught
# instead of quietly sending visitors to a third party again.
LEFTOVERS = ("fonts.googleapis.com", "fonts.gstatic.com", "flagcdn.com/",
             "github.io/nba-headshots", "api.github.com", "HEADSHOTS_TREE_API")


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
