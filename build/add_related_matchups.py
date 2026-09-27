#!/usr/bin/env python3
"""Add a pre-rendered "More matchups" block to the bottom of every matchup
page (m/*.html) and player page (p/*.html), so visitors keep clicking through.

The block is plain static HTML - crawlable <a href> links, no client-side
rendering - wrapped in

    <section class="related-matchups" data-prerendered="related"> ... </section>

and placed inside .container, directly after the heat legend. Its CSS lives
in a <style> inside the section, so nothing outside the section changes.

What it links to (only m/ pages that exist in the repo, never the page itself,
never the same page twice):

  m/<A>-vs-<B>.html   up to 4 of A's other matchups and up to 4 of B's, each
                      ranked by the pair's total possessions (both directions,
                      career, from data/m/*.json). If that is fewer than 4
                      matchup links, topped up to 4 (see below, with the
                      "most frequent opponents" of both A and B, skipping
                      pairs involving A or B). Then both players' p/ pages.
  p/<X>.html          up to 8 of X's matchups ranked the same way, skipping any
                      already linked higher on the page (the pre-rendered
                      opponent table). If fewer than 8 remain, topped up to 8.

Top-up, in order, skipping anything already on the page:
  1. the other matchups of the player's 3 most frequent opponents - by
     possessions against the player, both directions, career, from
     data/p/<player>.json - pooled and ranked by possessions, skipping any
     pair that involves the player;
  2. then data/pairs_top.json, in its order.

Ties are broken by name (the other player's, or the card label's), then by
page slug, so rebuilds never reshuffle the links.

LINK PATHS: hrefs are baked for the canonical host, exactly like the opponent
links prerender_matchup_tables.py bakes: "/matchups/m/<slug>.html" on
hoopsmatic.com, where the Worker serves the site under /matchups/ (and injects
<base href="/matchups/">, which a root-relative href does not depend on). A
four-line script inside the section re-points them at the site's own root on
any other host (GitHub Pages serves it under /nba-matchups/), using the same
formula as the page's ROOT; on hoopsmatic.com it does nothing. The page's own
ROOT logic is not touched. Pass --root to bake a different prefix.

Idempotent: an existing section is replaced, never duplicated, so a second run
changes nothing. m/template.html and p/template.html are skipped (they are the
generator's blank templates, not pages). Use --dry-run to count without
writing, --check to exit 1 if any page would change.

    python build/add_related_matchups.py [--dry-run] [--check] [--only SLUG ...]

Run it after every regeneration of m/ and/or p/, as step 5: after
apply_ui_tweaks.py (the section is anchored on the heat legend) and after
prerender_matchup_tables.py (a p/ page's "already linked" set is read from the
opponent links that script bakes).
"""

import argparse
import html
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DEFAULT_ROOT = "/matchups/"          # same as prerender_matchup_tables.py
M_LINKS = 4                           # per player, on m/ pages; also the m/ top-up floor
P_LINKS = 8                           # on p/ pages
FREQUENT = 3                          # most frequent opponents used for the top-up
SKIP = {"template"}

OPEN_TAG = '<section class="related-matchups" data-prerendered="related">'
# The section, as this script writes it: two-space indent, one trailing newline.
EXISTING = re.compile(r"  " + re.escape(OPEN_TAG) + r".*?</section>\n", re.S)

# The heat legend added by apply_ui_tweaks.py is the last block in .container;
# the section goes right after it.
LEGEND = re.compile(r'  <div class="heat-legend" data-legend="heat">\n.*?\n  </div>\n', re.S)

CSS = """<style>
.related-matchups{margin-top:1.8rem}
.related-matchups h2{font-family:'JetBrains Mono',monospace;font-size:.72rem;
  text-transform:uppercase;letter-spacing:.06em;color:var(--text-secondary);
  font-weight:600;margin:0 0 .7rem}
.related-matchups .rm-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:.5rem;list-style:none;margin:0;padding:0}
.related-matchups .rm-card{display:flex;align-items:center;justify-content:space-between;
  gap:.75rem;min-height:44px;padding:.6rem .9rem;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;color:var(--text);
  text-decoration:none;transition:.15s}
.related-matchups .rm-card:hover,.related-matchups .rm-card:focus-visible{
  border-color:var(--accent);color:var(--accent)}
.related-matchups .rm-name{font-weight:600;font-size:.9rem;min-width:0;overflow-wrap:anywhere}
.related-matchups .rm-poss{font-family:'JetBrains Mono',monospace;font-size:.72rem;
  color:var(--text-secondary);white-space:nowrap}
@media(max-width:760px){.related-matchups .rm-grid{grid-template-columns:1fr}}
</style>"""

# Re-point the baked links on hosts other than the canonical one. Same formula
# as the page's ROOT; a no-op on hoopsmatic.com.
JS = """<script>
(function(){var r=location.pathname.replace(/\\/(m|p)\\/[^/]*$/,"/"),b=%s;if(r===b)return;
document.querySelectorAll('.related-matchups a[href^="'+b+'"]').forEach(function(a){
a.setAttribute("href",r+a.getAttribute("href").slice(b.length));});})();
</script>"""


def fmt_poss(v: Decimal) -> str:
    """1972.0 -> "1,972", 337.2 -> "337.2" (as the pages' toLocaleString shows it)."""
    s = "{:,.1f}".format(v)
    return s[:-2] if s.endswith(".0") else s


def load_pairs():
    """{pair_slug: {"a": slug, "b": slug, "an": name, "bn": name, "poss": Decimal}}
    for every m/ page that exists and has data."""
    pairs = {}
    for path in sorted((REPO / "data" / "m").glob("*.json")):
        slug = path.stem
        if not (REPO / "m" / ("%s.html" % slug)).exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        poss = sum((Decimal(str(((d.get(k) or {}).get("career") or {}).get("poss") or 0))
                    for k in ("aGuardedByB", "bGuardedByA")), Decimal(0))
        pairs[slug] = {"a": d["playerA"]["slug"], "b": d["playerB"]["slug"],
                       "an": d["playerA"]["name"], "bn": d["playerB"]["name"], "poss": poss}
    return pairs


def by_player(pairs):
    """{player_slug: [pair_slug, ...]} ranked by total possessions, then by the
    other player's name, then by slug."""
    out = {}
    for slug, p in pairs.items():
        for me, other_name in ((p["a"], p["bn"]), (p["b"], p["an"])):
            out.setdefault(me, []).append((-p["poss"], other_name.lower(), slug))
    return {k: [s for _, _, s in sorted(v)] for k, v in out.items()}


def frequent_opponents():
    """{player_slug: [opponent_slug, ...]} ranked by possessions against the
    player (asOff + asDef, career), then by the opponent's name and slug."""
    out = {}
    for path in (REPO / "data" / "p").glob("*.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        tot, name = {}, {}
        for side in ("asOff", "asDef"):
            for o in d.get(side) or []:
                slug = o.get("slug")
                if not slug:
                    continue
                tot[slug] = tot.get(slug, Decimal(0)) + Decimal(
                    str((o.get("career") or {}).get("poss") or 0))
                name[slug] = o.get("name") or slug
        out[path.stem] = [k for _, _, k in sorted((-v, name[k].lower(), k)
                                                  for k, v in tot.items())]
    return out


def topup(players, need, taken, pairs, ranked, opponents, top):
    """Up to `need` more m/ slugs: the pooled matchups of each player's
    FREQUENT most frequent opponents (ranked by possessions, then label),
    skipping pairs that involve any of `players`; then pairs_top.json."""
    out = []
    if need <= 0:
        return out
    pool = set()
    for player in players:
        for opp in opponents.get(player, [])[:FREQUENT]:
            pool.update(ranked.get(opp, []))
    first = sorted((s for s in pool
                    if pairs[s]["a"] not in players and pairs[s]["b"] not in players),
                   key=lambda s: (-pairs[s]["poss"],
                                  ("%s vs %s" % (pairs[s]["an"], pairs[s]["bn"])).lower(), s))
    for s in first + list(top):
        if len(out) == need:
            break
        if s not in taken:
            taken.add(s)
            out.append(s)
    return out


def player_names():
    names = {}
    for path in (REPO / "data" / "p").glob("*.json"):
        names[path.stem] = json.loads(path.read_text(encoding="utf-8")).get("name") or path.stem
    return names


def top_pairs_order(pairs):
    """m/ page slugs in data/pairs_top.json order, each once."""
    path = REPO / "data" / "pairs_top.json"
    if not path.exists():
        return []
    seen, out = set(), []
    for e in json.loads(path.read_text(encoding="utf-8")):
        a, b = (e.get("off") or {}).get("slug"), (e.get("def") or {}).get("slug")
        for slug in ("%s-vs-%s" % (a, b), "%s-vs-%s" % (b, a)):
            if slug in pairs and slug not in seen:
                seen.add(slug)
                out.append(slug)
                break
    return out


def linked_m_slugs(text):
    """m/ pages already linked on the page (outside this script's section)."""
    out = set()
    for href in re.findall(r'href="([^"]+)"', text):
        m = re.search(r'(?:^|/)m/([a-z0-9-]+)\.html$', href)
        if m:
            out.add(m.group(1))
    return out


def card(href, name, right):
    return ('      <li><a class="rm-card" href="%s"><span class="rm-name">%s</span>'
            '<span class="rm-poss">%s</span></a></li>\n'
            % (html.escape(href), html.escape(name), html.escape(right)))


def render(items, root):
    """items: [("m", slug, label, right) | ("p", slug, label, right)]"""
    lis = "".join(card("%s%s/%s.html" % (root, kind, slug), label, right)
                  for kind, slug, label, right in items)
    return ("  %s\n%s\n    <h2>More matchups</h2>\n    <ul class=\"rm-grid\">\n%s    </ul>\n"
            "%s\n  </section>\n" % (OPEN_TAG, CSS, lis, JS % json.dumps(root)))


def m_card(pairs, slug):
    p = pairs[slug]
    return ("m", slug, "%s vs %s" % (p["an"], p["bn"]), "%s poss" % fmt_poss(p["poss"]))


def pick_for_m(slug, pairs, ranked, names, opponents, top):
    p = pairs[slug]
    chosen, seen = [], {slug}
    for player in (p["a"], p["b"]):
        n = 0
        for s in ranked.get(player, []):
            if n == M_LINKS:
                break
            if s in seen:
                continue
            seen.add(s)
            chosen.append(m_card(pairs, s))
            n += 1
    players = (p["a"], p["b"])
    chosen += [m_card(pairs, s)
               for s in topup(players, M_LINKS - len(chosen), seen, pairs, ranked, opponents, top)]
    for player in (p["a"], p["b"]):
        if (REPO / "p" / ("%s.html" % player)).exists():
            chosen.append(("p", player, names.get(player, player), "all matchups"))
    return chosen


def pick_for_p(slug, text, pairs, ranked, opponents, top):
    linked = linked_m_slugs(text)
    own = [s for s in ranked.get(slug, []) if s not in linked][:P_LINKS]
    taken = linked | set(own)
    own += topup((slug,), P_LINKS - len(own), taken, pairs, ranked, opponents, top)
    return [m_card(pairs, s) for s in own]


def apply(text, section):
    """Strip any existing section, then insert the new one after the legend.
    An empty section is not written at all."""
    base = EXISTING.sub("", text, count=1)
    m = LEGEND.search(base)
    if m is not None and not section:
        return base
    if m is None:
        return None
    return base[:m.end()] + section + base[m.end():]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if any page would change")
    ap.add_argument("--only", nargs="*", default=None, help="page slugs to process")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="site root baked into the links")
    args = ap.parse_args()

    pairs = load_pairs()
    ranked = by_player(pairs)
    names = player_names()
    top = top_pairs_order(pairs)
    opponents = frequent_opponents()

    changed = unchanged = 0
    errors, stats = [], {"m": [], "p": []}
    for kind in ("m", "p"):
        for path in sorted((REPO / kind).glob("*.html")):
            if path.stem in SKIP or (args.only is not None and path.stem not in args.only):
                continue
            text = path.read_bytes().decode("utf-8")      # bytes: line endings untouched
            if kind == "m":
                if path.stem not in pairs:
                    errors.append("%s: no data/m/%s.json" % (path.relative_to(REPO), path.stem))
                    continue
                items = pick_for_m(path.stem, pairs, ranked, names, opponents, top)
            else:
                items = pick_for_p(path.stem, EXISTING.sub("", text, count=1), pairs, ranked,
                                   opponents, top)
            new = apply(text, render(items, args.root) if items else "")
            if new is None:
                errors.append("%s: heat legend not found - run apply_ui_tweaks.py first"
                              % path.relative_to(REPO))
                continue
            stats[kind].append(len(items))
            if new == text:
                unchanged += 1
                continue
            changed += 1
            if not (args.dry_run or args.check):
                path.write_bytes(new.encode("utf-8"))

    verb = "would update" if (args.dry_run or args.check) else "updated"
    print("add_related_matchups: %s %d page(s), %d already current" % (verb, changed, unchanged))
    for kind in ("m", "p"):
        n = stats[kind]
        if n:
            print("  %s/: %d pages, %.2f links per page on average, %d with fewer than 4"
                  % (kind, len(n), sum(n) / len(n), sum(1 for x in n if x < 4)))
    for e in errors:
        print("  ! " + e, file=sys.stderr)
    if errors:
        return 1
    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
