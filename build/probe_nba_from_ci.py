"""One-off reachability probe: can a GitHub Actions runner reach stats.nba.com?
Three small requests with the fetcher's own headers; prints status, size, time.
Exit 0 always (the log is the result)."""
import importlib.util, json, sys, time, urllib.parse, urllib.request
from pathlib import Path
spec = importlib.util.spec_from_file_location("f", Path(__file__).with_name("fetch_matchup_data.py"))
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
tests = [
    ("playerindex 2026-27", f.PLAYER_INDEX_URL, {"LeagueID": "00", "Season": "2026-27", "Historical": "0"}),
    ("leagueseasonmatchups 2026-27 RS, one team", f.MATCHUPS_URL, dict(f.matchup_params("2026-27", "RS", Path("/tmp"), team_id="1610612747"))),
    ("leaguegamelog 2026-27 RS", "https://stats.nba.com/stats/leaguegamelog", {"LeagueID": "00", "Season": "2026-27", "SeasonType": "Regular Season", "PlayerOrTeam": "T", "Counter": "0", "Direction": "ASC", "Sorter": "DATE"}),
]
for name, url, params in tests:
    u = url + "?" + urllib.parse.urlencode(params)
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=f.HEADERS), timeout=45) as r:
            body = r.read(); dt = time.time() - t
            rows = ""
            try:
                j = json.loads(body); rs = j.get("resultSets") or [j.get("resultSet")]; rows = " rows=" + str(len(rs[0]["rowSet"]))
            except Exception: pass
            print(f"PROBE {name}: HTTP {r.status} {len(body)}B {dt:.1f}s{rows}")
    except Exception as e:
        print(f"PROBE {name}: FAILED after {time.time()-t:.1f}s: {type(e).__name__}: {e}")
    time.sleep(3)
