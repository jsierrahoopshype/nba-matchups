#!/usr/bin/env python3
"""Offline tests for player-page correctness after the 2026-11-05 run:

  * the page opens on a filter that shows something (50+, else 20+, else
    All), set by the generator and mirrored by the pre-rendered table;
  * a page whose default view already shows an opponent at 50+ is untouched;
  * a renamed player keeps the published name and URL (matched by
    playerId), so no duplicate page is created;
  * a new page needs an opponent in both views;
  * every page on disk gets a sitemap <url>, not only this run's new ones;
  * the committed data has no duplicate playerIds and every page is in the
    sitemap and the index.

    python build/test_player_pages.py
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import fetch_matchup_data as f            # noqa: E402
import generate_matchup_pages as g        # noqa: E402
import prerender_matchup_tables as pr     # noqa: E402

fails, passes = [], 0


def check(name, cond, detail=""):
    global passes
    if cond:
        passes += 1
    else:
        fails.append("%s %s" % (name, detail))


def opp(poss):
    return {"career": {"poss": poss}}


# ---- 1. the opening filter --------------------------------------------------
check("50 when an opponent reaches 50", g.default_min_poss({"asOff": [opp(51), opp(5)]}) == 50)
check("exactly 50 counts", g.default_min_poss({"asOff": [opp(50.0)]}) == 50)
check("20 when the best is 27.8 (Aday Mara)", g.default_min_poss({"asOff": [opp(27.8), opp(24.9)]}) == 20)
check("All when the best is under 20", g.default_min_poss({"asOff": [opp(12.1)]}) == 0)
check("All when nothing is listed", g.default_min_poss({"asOff": []}) == 0)

tpl = (REPO / "p" / "template.html").read_text(encoding="utf-8")
check("template default is 50", "  minPoss: 50," in tpl and 'class="pill on" data-minposs="50"' in tpl)
same = g.set_min_poss(tpl, 50, "t")
check("50 leaves the page byte-identical", same == tpl)
h20 = g.set_min_poss(tpl, 20, "t")
check("20: JS default", "  minPoss: 20," in h20 and "  minPoss: 50," not in h20)
check("20: pill on", 'class="pill on" data-minposs="20"' in h20
      and 'class="pill" data-minposs="50"' in h20 and h20.count('class="pill on" data-minposs') == 1)
h0 = g.set_min_poss(tpl, 0, "t")
check("0: pill All on", 'class="pill on" data-minposs="0"' in h0 and "  minPoss: 0," in h0)
check("prerender reads the page default", pr.page_min_poss(h20) == 20 and pr.page_min_poss(tpl) == 50
      and pr.page_min_poss(h0) == 0)
mara = {"asOff": [{"career": {"poss": 27.8, "pts_per_100": 10.8}},
                  {"career": {"poss": 24.9, "pts_per_100": 8.0}}]}
check("prerender at 50 shows none", len(pr.p_visible_opps(mara, 50)) == 0)
check("prerender at 20 shows both", len(pr.p_visible_opps(mara, 20)) == 2)

# Every committed player page opens on the filter its data calls for, and
# the baked table is not empty unless the player has no opponent at all.
wrong, empty = [], []
for page in sorted((REPO / "p").glob("*.html")):
    if page.stem == "template":
        continue
    data = json.loads((REPO / "data" / "p" / ("%s.json" % page.stem)).read_text(encoding="utf-8"))
    text = page.read_text(encoding="utf-8")
    if pr.page_min_poss(text) != g.default_min_poss(data):
        wrong.append(page.stem)
    # The sentence is in the page's JS once; a second copy is the baked table.
    if data["asOff"] and text.count("<div class='empty'>No matchups for this filter.</div>") > 1:
        empty.append(page.stem)
check("every page opens on its own filter", not wrong, repr(wrong[:5]))
check("no page with opponents opens empty", not empty, repr(empty[:5]))

# ---- 2. renamed players keep their page ---------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="hm-pages-test-"))
try:
    pdir = tmp / "p"
    pdir.mkdir()
    shutil.copy(REPO / "data" / "p" / "bobby-portis.json", pdir / "bobby-portis.json")
    players = {"1626171": {"name": "Bobby Portis Jr."}, "1": {"name": "Some One"}}
    check("rename pinned", f.pin_existing_names(players, pdir) == 1)
    check("published name kept", players["1626171"]["name"] == "Bobby Portis")
    check("slug unchanged", f.slugify(players["1626171"]["name"]) == "bobby-portis")
    check("others untouched", players["1"]["name"] == "Some One")
    check("existing_pages by id", f.existing_pages(pdir) == {"1626171": [("bobby-portis", "Bobby Portis")]})

    # add_new_player_pages never makes a second page for a known playerId,
    # even when the name the NBA now sends gives a different slug.
    players = {"1626171": {"name": "Bobby Portis Jr."}, "2": {"name": "Other Guy"}}
    cell = dict.fromkeys(f.RAW_KEYS, 0)

    def c(poss):
        x = dict(cell)
        x.update(poss=poss, games=3, pts=10, fga=8, fgm=4)
        return x
    S = f.CURRENT_SEASON
    pairs = {("1626171", "2"): {(S, "RS"): c(150.0)}, ("2", "1626171"): {(S, "RS"): c(140.0)}}
    new = f.add_new_player_pages(players, pairs, list(f.SEASONS), pdir, True)
    check("no duplicate for a renamed player", "bobby-portis-jr" not in new, repr(new))
    check("a real new player still gets one", new == ["other-guy"], repr(new))

    # ---- 3. both views need an opponent --------------------------------------
    check("meaningful: both sides", f.page_is_meaningful({"asOff": [1], "asDef": [1]}))
    check("not meaningful: no offense (Kevin Hervey)", not f.page_is_meaningful({"asOff": [], "asDef": [1, 2]}))
    check("not meaningful: no defense (Baba Miller)", not f.page_is_meaningful({"asOff": [1], "asDef": []}))
    players = {"3": {"name": "Only Offense"}, "4": {"name": "Big Defender"}}
    small = {("3", "4"): {(S, "RS"): c(120.0)}}             # 3 is never guarded by a listed player
    new = f.add_new_player_pages(players, small, list(f.SEASONS), pdir, True)
    check("one-sided player gets no page", "only-offense" not in new, repr(new))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- 4. the committed data is consistent -----------------------------------
pages = f.existing_pages(REPO / "data" / "p")
dups = {k: v for k, v in pages.items() if len(v) > 1}
check("no duplicate playerIds", not dups, repr(dups))
check("every page in the sitemap", f.pages_missing_from_sitemap() == [],
      repr(f.pages_missing_from_sitemap()[:5]))
index = {e["slug"] for e in json.loads((REPO / "data" / "player_index.json").read_text(encoding="utf-8"))}
on_disk = {p.stem for p in (REPO / "data" / "p").glob("*.json")}
check("index == pages", index == on_disk, repr(sorted(index ^ on_disk)[:5]))
for gone in ("bobby-portis-jr", "brandon-boston-jr", "nene", "yang-hansen", "rj-nembhard-jr",
             "kevin-hervey", "baba-miller"):
    check("%s removed" % gone, not (REPO / "p" / ("%s.html" % gone)).exists()
          and gone not in index)
xml = (REPO / "sitemap.xml").read_text(encoding="utf-8")
locs = re.findall(r"<loc>([^<]*)</loc>", xml)
check("sitemap only hoopsmatic.com", all(l.startswith("https://hoopsmatic.com/matchups/") for l in locs))
check("sitemap entries map to files", all((REPO / l[len("https://hoopsmatic.com/matchups/"):]).exists()
                                        for l in locs if l.endswith(".html")))
bp = json.loads((REPO / "data" / "p" / "bobby-portis.json").read_text(encoding="utf-8"))
check("bobby-portis refreshed", bp["ytdLabel"] == f.CURRENT_SEASON and bp["slug"] == "bobby-portis")
stale = [p.stem for p in (REPO / "data" / "p").glob("*.json")
         if '"ytdLabel": "%s"' % f.CURRENT_SEASON not in p.read_text(encoding="utf-8")[:2000]
         and '"ytdLabel":"%s"' % f.CURRENT_SEASON not in p.read_text(encoding="utf-8")[:2000]]
check("no stale player page", not stale, repr(stale[:5]))

print("player page tests: %d passed, %d failed" % (passes, len(fails)))
for msg in fails:
    print("  FAIL %s" % msg)
sys.exit(1 if fails else 0)
