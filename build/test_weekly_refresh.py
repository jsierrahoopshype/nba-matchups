#!/usr/bin/env python3
"""Offline tests for the weekly refresh: date-based seasons, the cache rules
that make it incremental, the empty-season tolerance, and the write step that
adds pages for newly qualifying players (player_index.json, sitemap.xml,
meta.json). No network, and nothing in the repo is written: every file the
write step touches is copied into a temp folder first.

    python build/test_weekly_refresh.py
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_matchup_data as f  # noqa: E402
import playoff_games as pg      # noqa: E402

REAL = HERE.parent
fails = []
passes = 0


def check(name, cond, detail=""):
    global passes
    if cond:
        passes += 1
    else:
        fails.append("%s %s" % (name, detail))


# ---- 1. seasons come from the date -----------------------------------------
D = datetime.date.fromisoformat
check("first season", f.seasons_through(D("2026-11-05"))[0] == "2017-18")
check("Nov 2026 ends at 2026-27", f.seasons_through(D("2026-11-05"))[-1] == "2026-27")
check("Sep 30 2026 ends at 2025-26", f.seasons_through(D("2026-09-30"))[-1] == "2025-26")
check("Oct 1 2027 adds 2027-28", f.seasons_through(D("2027-10-01"))[-1] == "2027-28")
check("no gaps", len(f.seasons_through(D("2027-10-01"))) == 11)
check("century label", f.season_label(2099) == "2099-00")
check("module list is today's", f.SEASONS == f.seasons_through())
check("CURRENT_SEASON is the last", f.CURRENT_SEASON == f.SEASONS[-1])

# ---- 2. incremental cache rules ---------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="hm-weekly-test-"))
try:
    args = types.SimpleNamespace(current_max_age_hours=12, refresh=False)
    cur = tmp / "cur.json"
    cur.write_text("{}")
    check("current season fresh", not f.current_cache_stale(cur, f.CURRENT_SEASON, args))
    old = time.time() - 13 * 3600
    os.utime(cur, (old, old))
    check("current season stale after 12h", f.current_cache_stale(cur, f.CURRENT_SEASON, args))

    past = tmp / "past.json"
    past.write_text("{}")
    check("finished season fetched after it ended is frozen",
          not f.current_cache_stale(past, "2024-25", args))
    mid_finals = datetime.datetime(2026, 6, 10, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(past, (mid_finals, mid_finals))
    check("2025-26 cached mid-Finals is fetched once more",
          f.current_cache_stale(past, "2025-26", args))
    check("...but a 2024-25 copy from that day is final",
          not f.current_cache_stale(past, "2024-25", args))

    # ---- 3. empty playoff list for the season in progress ------------------
    def empty_http(url, params, timeout, tries, delay):
        return {"resultSets": [{"name": "LeagueGameLog", "headers": ["GAME_ID"], "rowSet": []}]}
    pargs = types.SimpleNamespace(empty_retries=1, timeout=1, retries=1, retry_delay=0,
                                  delay=0, refresh=False)
    pcache = tmp / "pcache"
    got = pg.fetch_game_list(f.CURRENT_SEASON, True, pcache, pargs, empty_http, allow_empty=True)
    check("empty current playoff list is []", got == [])
    check("...and is cached as an empty list, not missing",
          pg.cached_game_list(f.CURRENT_SEASON, pcache) == [])
    try:
        pg.fetch_game_list("2023-24", False, pcache, pargs, empty_http)
        check("empty finished playoff list still fails", False)
    except pg.EmptyGameData:
        check("empty finished playoff list still fails", True)

    # ---- 4. a season with no regular-season rows yet is left out -----------
    mcache = tmp / "mcache"
    seasons = list(f.SEASONS)
    check("unstarted season dropped (no cache)",
          f.drop_unstarted_season(seasons, mcache) == seasons[:-1])
    path = f.cache_path(mcache, f.CURRENT_SEASON, "RS")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"resultSets": [{"headers": ["A"], "rowSet": [[1]]}]}))
    check("started season kept", f.drop_unstarted_season(seasons, mcache) == seasons)

    # ---- 5. the write step, against a temp copy of the real files ----------
    repo = tmp / "repo"
    (repo / "data" / "p").mkdir(parents=True)
    for name in ("player_index.json", "meta.json"):
        shutil.copy(REAL / "data" / name, repo / "data" / name)
    shutil.copy(REAL / "sitemap.xml", repo / "sitemap.xml")
    index = json.loads((REAL / "data" / "player_index.json").read_text(encoding="utf-8"))
    for e in index:
        shutil.copy(REAL / "data" / "p" / ("%s.json" % e["slug"]),
                    repo / "data" / "p" / ("%s.json" % e["slug"]))
    f.REPO = repo

    # Players as the fetch would return them: everyone already indexed, plus
    # one rookie who clears 100 possessions and one who does not.
    players = {e["playerId"]: {"name": e["name"], "country": e["country"],
                               "iso": e["iso"], "pos": e["pos"]} for e in index}
    players["9000001"] = {"name": "Aaron Testrookie", "country": "Spain", "iso": "es", "pos": "G"}
    players["9000002"] = {"name": "Zed Benchrookie", "country": "France", "iso": "fr", "pos": "F"}
    vet = index[0]["playerId"]
    cell = dict.fromkeys(f.RAW_KEYS, 0)

    def c(poss, games=10, pts=40, fga=30, fgm=12):
        x = dict(cell)
        x.update(poss=poss, games=games, pts=pts, fga=fga, fgm=fgm)
        return x
    S = f.CURRENT_SEASON
    pairs = {
        ("9000001", vet): {(S, "RS"): c(80.4)},
        (vet, "9000001"): {(S, "RS"): c(61.2)},
        ("9000001", index[1]["playerId"]): {(S, "RS"): c(40.1)},   # asOff 120.5
        ("9000002", vet): {(S, "RS"): c(55.0)},                    # 55: no page
    }

    before_index = (repo / "data" / "player_index.json").read_bytes()
    # The index rewrite is a no-op when no page changed.
    n = f.update_player_index(players, {}, list(f.SEASONS), repo / "data" / "p")
    check("index unchanged when no page changed",
          (repo / "data" / "player_index.json").read_bytes() == before_index,
          "(totalPoss rule or tie order not reproduced)")
    check("index count", n == len(index))

    new = f.add_new_player_pages(players, pairs, list(f.SEASONS), repo / "data" / "p", False)
    check("rookie over 100 gets a page", new == ["aaron-testrookie"], repr(new))
    page = json.loads((repo / "data" / "p" / "aaron-testrookie.json").read_text(encoding="utf-8"))
    check("rookie page ytdLabel", page["ytdLabel"] == S)
    check("rookie page shape", set(page) == {"playerId", "name", "slug", "country", "iso", "pos",
                                             "ytdLabel", "career", "asOff", "asDef"})
    check("rookie page asOff poss", abs(page["career"]["asOff"]["poss"] - 120.5) < 1e-6)
    check("rookie under 100 gets none",
          not (repo / "data" / "p" / "zed-benchrookie.json").exists())
    again = f.add_new_player_pages(players, pairs, list(f.SEASONS), repo / "data" / "p", False)
    check("second run adds nothing", again == [])

    n = f.update_player_index(players, pairs, list(f.SEASONS), repo / "data" / "p")
    idx2 = json.loads((repo / "data" / "player_index.json").read_text(encoding="utf-8"))
    entry = next((e for e in idx2 if e["slug"] == "aaron-testrookie"), None)
    check("rookie in index", entry is not None and entry["totalPoss"] == 120.0, repr(entry))
    check("index keys", entry is not None and list(entry) ==
          ["slug", "name", "playerId", "country", "iso", "pos", "totalPoss"])
    check("index sorted", [e["totalPoss"] for e in idx2] ==
          sorted((e["totalPoss"] for e in idx2), reverse=True))
    check("index count +1", n == len(index) + 1)

    before_xml = (repo / "sitemap.xml").read_text(encoding="utf-8")
    added = f.add_sitemap_urls(["p/aaron-testrookie.html"])
    xml = (repo / "sitemap.xml").read_text(encoding="utf-8")
    loc = "<loc>https://hoopsmatic.com/matchups/p/aaron-testrookie.html</loc>"
    check("sitemap url added", added == 1 and xml.count(loc) == 1)
    check("sitemap never github.io", "github.io" not in xml)
    check("sitemap keeps every old url", xml.count("<url>") == before_xml.count("<url>") + 1)
    import re
    p_locs = re.findall(r"<loc>(https://hoopsmatic.com/matchups/p/[^<]*)</loc>", xml)
    old_p = re.findall(r"<loc>(https://hoopsmatic.com/matchups/p/[^<]*)</loc>", before_xml)
    if old_p == sorted(old_p):
        check("sitemap alphabetical", p_locs == sorted(p_locs))
    check("sitemap priority like other p/", "%s\n    <changefreq>weekly</changefreq>\n"
          "    <priority>0.7</priority>" % loc in xml)
    check("sitemap re-add is a no-op", f.add_sitemap_urls(["p/aaron-testrookie.html"]) == 0)
    check("sitemap still closes", xml.rstrip().endswith("</urlset>"))
    removed = xml.replace("  <url>\n    %s\n    <changefreq>weekly</changefreq>\n"
                          "    <priority>0.7</priority>\n  </url>\n" % loc, "")
    check("sitemap otherwise byte-identical", removed == before_xml)

    f.update_meta(list(f.SEASONS), n, len(list((repo / "data" / "p").glob("*.json"))))
    meta = json.loads((repo / "data" / "meta.json").read_text(encoding="utf-8"))
    check("meta ytd", meta["ytd_label"] == f.CURRENT_SEASON)
    check("meta seasons newest first", meta["seasons_loaded"] == list(reversed(f.SEASONS)))
    check("meta counts", meta["qualifying_players"] == len(index) + 1
          and meta["pages_written"] == len(index) + 1)
    check("meta keeps other keys", meta["h2h_pairs_written"] == 1319
          and "archive_rows_seen" in meta)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("weekly refresh tests: %d passed, %d failed" % (passes, len(fails)))
for msg in fails:
    print("  FAIL %s" % msg)
sys.exit(1 if fails else 0)
