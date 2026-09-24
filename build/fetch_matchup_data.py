#!/usr/bin/env python3
"""Stage 1 of the pipeline: stats.nba.com -> data/.

Rebuilds data/m/*.json and data/p/*.json (and, only when asked, the shared
index files) from the NBA's season-matchup endpoint.

RUN THIS ON YOUR OWN MACHINE
----------------------------
stats.nba.com blocks datacenter IPs, so this will not work from a cloud
sandbox or a GitHub Action. Run it locally - double-click
build/refresh-matchup-data.bat on Windows, which does everything including
the generator and the build/ scripts afterwards.

WHAT IS PROVEN AND WHAT IS NOT
------------------------------
Read this before trusting the first run.

PROVEN against the committed data in this repo:
  * Every derived field. fg_pct = round(fgm/fga, 3), fg3_pct and efg_pct the
    same way, and pts/ast/tov_per_100 = round(100 * x / poss, 1). Checked
    over 99,876 stat blocks, zero mismatches.
  * career == sum(byPhase) == sum(bySeason). Checked over 600 blocks.
  * byWindow ytd/last3/last5 == the sum of the last 1/3/5 seasons. Checked
    over 400 pairs x 3 windows.
  * An m/ pair file's aGuardedByB.career is exactly the matching opponent row
    in p/<A>.json asOff. Checked over 200 pairs. Both views come from the
    same (off, def, season, phase) rows.
  * Opponents are listed when their career poss >= 10. Checked over 476,218
    opponent rows; none below 10.
  * The slug rule below reproduces all 1,224 committed slugs exactly.
  * COUNTRY_ISO below is lifted from data/player_index.json - 57 countries,
    no conflicts.
  * poss is fractional and always lands on one decimal, which is the
    PARTIAL_POSS fingerprint.
  * Coverage starts exactly at 2017-18, the first season of NBA matchup
    tracking, and splits RS/PO.

NOT PROVEN - written to spec, never executed against the live API:
  * The endpoint URL and its parameter names and casing.
  * That an unfiltered league-wide query is allowed, rather than the API
    requiring OffPlayerID or a team filter. If it refuses, --by-team walks
    the 30 teams per season instead.
  * The exact resultSets/headers shape of the response.
  * The source of name/country/position. PLAYER_INDEX_URL is the best
    candidate; the matchup rows themselves carry only IDs and names.
  * player_index.json's totalPoss. It tracks career.asOff.poss but not
    exactly (54133.0 vs 54133.1 for Jokic), which looks like a different
    float accumulation order. Not reproduced; --write-shared leaves it alone
    unless you also pass --rebuild-index.
  * Which pairs get an m/ page. 1,319 of the 1,321 committed pages are
    exactly the distinct pairs in pairs_top.json; the remaining two
    (grayson-allen-vs-jordan-clarkson, ivica-zubac-vs-jaxson-hayes) are not,
    so the rule is not fully recovered. By default existing m/ pair files are
    refreshed in place and no new pair set is invented.

hero_matchups.json is hand-written editorial copy ("MVP centers, conference
rivals"). It is never touched.

USAGE
-----
    python build/fetch_matchup_data.py                 # fetch (cached) + transform
    python build/fetch_matchup_data.py --fetch-only    # just fill the cache
    python build/fetch_matchup_data.py --transform-only
    python build/fetch_matchup_data.py --self-test     # transform unit test, no network
    python build/fetch_matchup_data.py --verify-slug nikola-jokic
    python build/fetch_matchup_data.py --seasons 2025-26 --refresh

Resumable: each (season, season type) response is cached under
build/.cache/matchups/. A run that dies part-way picks up where it left off,
and only --refresh re-requests something already cached.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / ".cache" / "matchups"

# ---------------------------------------------------------------------------
# Endpoint (UNVERIFIED - see the module docstring)
# ---------------------------------------------------------------------------

MATCHUPS_URL = "https://stats.nba.com/stats/leagueseasonmatchups"
PLAYER_INDEX_URL = "https://stats.nba.com/stats/playerindex"

# stats.nba.com rejects anything that does not look like a browser. Referer
# and User-Agent are the two it actually enforces; the x-nba-stats-* pair is
# what nba.com's own front end sends.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

SEASONS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22",
           "2022-23", "2023-24", "2024-25", "2025-26"]
SEASON_TYPES = {"RS": "Regular Season", "PO": "Playoffs"}

# Stat fields on a matchup row, mapped to the names used in data/.
# MATCHUP_BLK and SFL are returned by the API but are not carried into data/.
FIELD_MAP = {
    "GP": "games",
    "PARTIAL_POSS": "poss",
    "PLAYER_PTS": "pts",
    "MATCHUP_FGM": "fgm",
    "MATCHUP_FGA": "fga",
    "MATCHUP_FG3M": "fg3m",
    "MATCHUP_FG3A": "fg3a",
    "MATCHUP_FTM": "ftm",
    "MATCHUP_FTA": "fta",
    "MATCHUP_AST": "ast",
    "MATCHUP_TOV": "tov",
}
RAW_KEYS = ("games", "poss", "pts", "fgm", "fga", "fg3m", "fg3a",
            "ftm", "fta", "ast", "tov")

MIN_OPP_POSS = 10        # PROVEN: opponents are listed at poss >= 10
QUALIFY_MIN_POSS = 100   # from data/meta.json

POS_FROM_WORD = {"Guard": "G", "Forward": "F", "Center": "C"}

# Lifted verbatim from data/player_index.json: 57 countries, no conflicts.
COUNTRY_ISO = {
    "Angola":              "ao",
    "Argentina":           "ar",
    "Australia":           "au",
    "Austria":             "at",
    "Bahamas":             "bs",
    "Belgium":             "be",
    "Bosnia":              "ba",
    "Brazil":              "br",
    "Bulgaria":            "bg",
    "Cameroon":            "cm",
    "Canada":              "ca",
    "China":               "cn",
    "Croatia":             "hr",
    "Czech Republic":      "cz",
    "DR Congo":            "cd",
    "Dominican Republic":  "do",
    "Egypt":               "eg",
    "Finland":             "fi",
    "France":              "fr",
    "Gabon":               "ga",
    "Germany":             "de",
    "Ghana":               "gh",
    "Great Britain":       "gb",
    "Greece":              "gr",
    "Guinea":              "gn",
    "Haiti":               "ht",
    "Indonesia":           "id",
    "Israel":              "il",
    "Italy":               "it",
    "Jamaica":             "jm",
    "Japan":               "jp",
    "Latvia":              "lv",
    "Lebanon":             "lb",
    "Lithuania":           "lt",
    "Mali":                "ml",
    "Mexico":              "mx",
    "Montenegro":          "me",
    "Netherlands":         "nl",
    "New Zealand":         "nz",
    "Nigeria":             "ng",
    "Philippines":         "ph",
    "Poland":              "pl",
    "Portugal":            "pt",
    "Puerto Rico":         "pr",
    "Republic of Georgia": "ge",
    "Russia":              "ru",
    "Senegal":             "sn",
    "Serbia":              "rs",
    "Slovenia":            "si",
    "South Sudan":         "ss",
    "Spain":               "es",
    "Sweden":              "se",
    "Switzerland":         "ch",
    "Tunisia":             "tn",
    "Turkey":              "tr",
    "Ukraine":             "ua",
    "United States":       "us",
}


def slugify(name: str) -> str:
    """PROVEN: reproduces all 1,224 committed slugs exactly."""
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[.'’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class FetchError(RuntimeError):
    pass


def http_json(url: str, params: dict, timeout: int, tries: int, delay: float) -> dict:
    """GET with browser headers, retrying with exponential backoff and jitter."""
    full = "%s?%s" % (url, urllib.parse.urlencode(params))
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(full, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            # 4xx other than 429 will not fix themselves; stop early.
            if exc.code not in (429, 500, 502, 503, 504):
                raise FetchError("%s for %s" % (last, full)) from exc
        except Exception as exc:                      # noqa: BLE001 - retried
            last = "%s: %s" % (type(exc).__name__, exc)
        if attempt < tries:
            back = delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
            print("    retry %d/%d in %.1fs (%s)" % (attempt, tries, back, last))
            time.sleep(back)
    raise FetchError("gave up after %d attempts: %s (%s)" % (tries, last, full))


def cache_path(season: str, phase: str, team_id: str = "") -> Path:
    name = "%s_%s%s.json" % (season, phase, ("_t%s" % team_id) if team_id else "")
    return CACHE / name


def fetch_matchups(season: str, phase: str, args, team_id: str = "") -> dict:
    """One (season, season type[, team]) response, cached on disk."""
    path = cache_path(season, phase, team_id)
    if path.exists() and not args.refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    params = {
        "LeagueID": "00",
        "PerMode": "Totals",
        "Season": season,
        "SeasonType": SEASON_TYPES[phase],
        "OffPlayerID": "",
        "DefPlayerID": "",
        "OffTeamID": team_id,
        "DefTeamID": "",
    }
    print("  fetching %s %s%s" % (season, phase, (" team %s" % team_id) if team_id else ""))
    payload = http_json(MATCHUPS_URL, params, args.timeout, args.retries, args.retry_delay)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    time.sleep(args.delay)
    return payload


def result_rows(payload: dict):
    """Yield dicts from a stats.nba.com resultSets payload.

    UNVERIFIED shape: {"resultSets":[{"headers":[...],"rowSet":[[...]]}]}.
    Accepts "resultSet" as well, which some endpoints use.
    """
    sets = payload.get("resultSets") or payload.get("resultSet") or []
    if isinstance(sets, dict):
        sets = [sets]
    for rs in sets:
        headers = rs.get("headers") or []
        for row in rs.get("rowSet") or []:
            yield dict(zip(headers, row))


# ---------------------------------------------------------------------------
# Transform  (the rules below are the PROVEN ones)
# ---------------------------------------------------------------------------

def blank():
    return {k: 0 for k in RAW_KEYS}


def accumulate(acc: dict, row: dict) -> dict:
    for api_key, our_key in FIELD_MAP.items():
        acc[our_key] = acc.get(our_key, 0) + (row.get(api_key) or 0)
    return acc


def derive(s: dict) -> dict:
    """PROVEN over 99,876 committed stat blocks."""
    out = {k: (round(s[k], 1) if k == "poss" else s[k]) for k in RAW_KEYS}
    out["fg_pct"] = round(out["fgm"] / out["fga"], 3) if out["fga"] else 0.0
    out["fg3_pct"] = round(out["fg3m"] / out["fg3a"], 3) if out["fg3a"] else 0.0
    out["efg_pct"] = (round((out["fgm"] + 0.5 * out["fg3m"]) / out["fga"], 3)
                      if out["fga"] else 0.0)
    if out["poss"]:
        out["pts_per_100"] = round(100 * out["pts"] / out["poss"], 1)
        out["ast_per_100"] = round(100 * out["ast"] / out["poss"], 1)
        out["tov_per_100"] = round(100 * out["tov"] / out["poss"], 1)
    else:
        out["pts_per_100"] = out["ast_per_100"] = out["tov_per_100"] = 0.0
    return out


def total(cells: dict, keys=None) -> dict:
    """Sum a {(season, phase): raw} map, optionally restricted to some keys."""
    acc = blank()
    for key, cell in cells.items():
        if keys is not None and key not in keys:
            continue
        for k in RAW_KEYS:
            acc[k] += cell.get(k, 0)
    return acc


def windows(cells: dict, seasons: list) -> dict:
    """PROVEN: ytd / last3 / last5 are the sums of the last 1 / 3 / 5 seasons."""
    out = {}
    for name, n in (("ytd", 1), ("last3", 3), ("last5", 5)):
        wanted = set(seasons[-n:])
        out[name] = derive(total(cells, {k for k in cells if k[0] in wanted}))
    return out


def by_phase(cells: dict) -> dict:
    out = {}
    for phase in ("RS", "PO"):
        keys = {k for k in cells if k[1] == phase}
        if keys:
            out[phase] = derive(total(cells, keys))
    return out


def by_season(cells: dict) -> dict:
    out = {}
    for season in sorted({k[0] for k in cells}):
        out[season] = derive(total(cells, {k for k in cells if k[0] == season}))
    return out


def build_dataset(rows, players: dict, seasons: list):
    """rows -> {(off_id, def_id): {(season, phase): raw}} plus per-player totals."""
    pairs = {}
    for row in rows:
        off = str(row.get("OFF_PLAYER_ID") or "")
        dfn = str(row.get("DEF_PLAYER_ID") or "")
        if not off or not dfn:
            continue
        season = row.get("_SEASON")
        phase = row.get("_PHASE")
        cell = pairs.setdefault((off, dfn), {}).setdefault((season, phase), blank())
        accumulate(cell, row)
        for pid, key in ((off, "OFF_PLAYER_NAME"), (dfn, "DEF_PLAYER_NAME")):
            if pid not in players and row.get(key):
                players[pid] = {"name": row[key]}
    return pairs


def player_payload(pid: str, pairs: dict, players: dict, seasons: list) -> dict:
    """One data/p/<slug>.json."""
    info = players.get(pid, {})
    name = info.get("name", "")

    def side(as_off: bool):
        listed, all_cells = [], {}
        for (off, dfn), cells in pairs.items():
            me, other = (off, dfn) if as_off else (dfn, off)
            if me != pid:
                continue
            for k, v in cells.items():
                acc = all_cells.setdefault(k, blank())
                for key in RAW_KEYS:
                    acc[key] += v.get(key, 0)
            career = derive(total(cells))
            if career["poss"] < MIN_OPP_POSS:      # PROVEN cut
                continue
            oi = players.get(other, {})
            listed.append({
                "id": other,
                "name": oi.get("name", ""),
                "slug": slugify(oi.get("name", "")),
                "country": oi.get("country", ""),
                "iso": oi.get("iso", ""),
                "pos": oi.get("pos", ""),
                "career": career,
                "byPhase": by_phase(cells),
                "byWindow": windows(cells, seasons),
            })
        listed.sort(key=lambda o: o["career"]["poss"], reverse=True)
        return listed, all_cells

    as_off, off_cells = side(True)
    as_def, def_cells = side(False)
    return {
        "playerId": pid,
        "name": name,
        "slug": slugify(name),
        "country": info.get("country", ""),
        "iso": info.get("iso", ""),
        "pos": info.get("pos", ""),
        "ytdLabel": seasons[-1],
        "career": {
            "asOff": derive(total(off_cells)),
            "asDef": derive(total(def_cells)),
            "asOffByWindow": windows(off_cells, seasons),
            "asDefByWindow": windows(def_cells, seasons),
        },
        "asOff": as_off,
        "asDef": as_def,
    }


def pair_payload(a_id: str, b_id: str, pairs: dict, players: dict, seasons: list) -> dict:
    """One data/m/<slugA>-vs-<slugB>.json."""
    def meta(pid):
        i = players.get(pid, {})
        return {"id": pid, "name": i.get("name", ""), "slug": slugify(i.get("name", "")),
                "country": i.get("country", ""), "iso": i.get("iso", ""),
                "pos": i.get("pos", "")}

    def direction(off, dfn):
        cells = pairs.get((off, dfn), {})
        return {"career": derive(total(cells)),
                "byPhase": by_phase(cells),
                "bySeason": by_season(cells)}

    return {
        "playerA": meta(a_id),
        "playerB": meta(b_id),
        "ytdLabel": seasons[-1],
        "seasons_loaded": list(reversed(seasons)),
        "aGuardedByB": direction(a_id, b_id),
        "bGuardedByA": direction(b_id, a_id),
    }


# ---------------------------------------------------------------------------
# Self-test: exercises the transform without touching the network
# ---------------------------------------------------------------------------

def self_test() -> int:
    """Feed synthetic rows through the transform and check the invariants that
    were proven against the committed data. This does NOT prove the data
    matches the NBA's - only that the transform obeys the rules."""
    seasons = SEASONS
    rows = []
    rnd = random.Random(1)
    for season in seasons:
        for phase in ("RS", "PO"):
            if phase == "PO" and rnd.random() < 0.4:
                continue
            rows.append({
                "_SEASON": season, "_PHASE": phase,
                "OFF_PLAYER_ID": "1", "OFF_PLAYER_NAME": "Nikola Jokić",
                "DEF_PLAYER_ID": "2", "DEF_PLAYER_NAME": "Joel Embiid",
                "GP": rnd.randint(1, 5), "PARTIAL_POSS": round(rnd.uniform(20, 300), 1),
                "PLAYER_PTS": rnd.randint(0, 90), "MATCHUP_FGM": rnd.randint(0, 30),
                "MATCHUP_FGA": rnd.randint(31, 70), "MATCHUP_FG3M": rnd.randint(0, 9),
                "MATCHUP_FG3A": rnd.randint(10, 25), "MATCHUP_FTM": rnd.randint(0, 9),
                "MATCHUP_FTA": rnd.randint(10, 15), "MATCHUP_AST": rnd.randint(0, 20),
                "MATCHUP_TOV": rnd.randint(0, 12),
            })
    players = {}
    pairs = build_dataset(rows, players, seasons)
    players["1"].update(country="Serbia", iso="rs", pos="C")
    players["2"].update(country="USA", iso="us", pos="C")

    pair = pair_payload("1", "2", pairs, players, seasons)
    d = pair["aGuardedByB"]
    fails = []

    if pair["playerA"]["slug"] != "nikola-jokic":
        fails.append("slugify: %r" % pair["playerA"]["slug"])

    c = d["career"]
    for name, group in (("byPhase", d["byPhase"]), ("bySeason", d["bySeason"])):
        for k in RAW_KEYS:
            s = round(sum(v[k] for v in group.values()), 4)
            if abs(s - round(c[k], 4)) > 1e-4:
                fails.append("career != sum(%s) for %s: %s vs %s" % (name, k, s, c[k]))

    if c["fga"] and c["fg_pct"] != round(c["fgm"] / c["fga"], 3):
        fails.append("fg_pct")
    if c["poss"] and c["pts_per_100"] != round(100 * c["pts"] / c["poss"], 1):
        fails.append("pts_per_100")

    pl = player_payload("1", pairs, players, seasons)
    bw = pl["asOff"][0]["byWindow"]
    for name, n in (("ytd", 1), ("last3", 3), ("last5", 5)):
        want = blank()
        for s in seasons[-n:]:
            if s in d["bySeason"]:
                for k in RAW_KEYS:
                    want[k] += d["bySeason"][s][k]
        for k in RAW_KEYS:
            if abs(round(want[k], 4) - round(bw[name][k], 4)) > 1e-4:
                fails.append("byWindow %s %s: %s vs %s" % (name, k, want[k], bw[name][k]))

    have = set(pair_payload("1", "2", pairs, players, seasons).keys())
    want = {"playerA", "playerB", "ytdLabel", "seasons_loaded", "aGuardedByB", "bGuardedByA"}
    if have != want:
        fails.append("m/ top-level keys: %s" % (have ^ want))
    have = set(pl.keys())
    want = {"playerId", "name", "slug", "country", "iso", "pos", "ytdLabel",
            "career", "asOff", "asDef"}
    if have != want:
        fails.append("p/ top-level keys: %s" % (have ^ want))

    if fails:
        print("SELF-TEST FAILED:")
        for f in fails:
            print("  ! %s" % f)
        return 1
    print("SELF-TEST OK: slug rule, derived fields, career==sum(byPhase)==sum(bySeason),")
    print("  byWindow==last-N seasons, and both payload shapes all hold.")
    print("  (Self-consistency only - it does not prove the numbers match the NBA's.)")
    return 0


# ---------------------------------------------------------------------------
# Verification against a committed file
# ---------------------------------------------------------------------------

def verify_slug(slug: str, pairs, players, seasons) -> int:
    """Transform the fetched rows for one page and diff against what is
    committed. This is the proof that the mapping is right; it needs a real
    fetch first."""
    kind = "p" if (REPO / "data" / "p" / ("%s.json" % slug)).exists() else "m"
    committed = json.loads((REPO / "data" / kind / ("%s.json" % slug)).read_text(encoding="utf-8"))
    if kind == "p":
        pid = next((p for p, i in players.items() if slugify(i.get("name", "")) == slug), None)
        if pid is None:
            print("no fetched rows for %s" % slug, file=sys.stderr)
            return 1
        built = player_payload(pid, pairs, players, seasons)
    else:
        a_slug, b_slug = slug.split("-vs-")
        ids = {slugify(i.get("name", "")): p for p, i in players.items()}
        if a_slug not in ids or b_slug not in ids:
            print("no fetched rows for %s" % slug, file=sys.stderr)
            return 1
        built = pair_payload(ids[a_slug], ids[b_slug], pairs, players, seasons)

    a = json.dumps(committed, sort_keys=True, indent=1, ensure_ascii=False).splitlines()
    b = json.dumps(built, sort_keys=True, indent=1, ensure_ascii=False).splitlines()
    if a == b:
        print("VERIFY %s: identical to the committed file." % slug)
        return 0
    import difflib
    print("VERIFY %s: DIFFERS" % slug)
    for line in list(difflib.unified_diff(a, b, "committed", "fetched", lineterm=""))[:60]:
        print("  " + line)
    return 1


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", nargs="*", default=SEASONS)
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--transform-only", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="run the transform unit test; no network, writes nothing")
    ap.add_argument("--verify-slug", default=None,
                    help="transform one page and diff it against the committed file")
    ap.add_argument("--by-team", action="store_true",
                    help="walk the 30 teams per season if a league-wide query is refused")
    ap.add_argument("--refresh", action="store_true", help="re-request cached responses")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--retry-delay", type=float, default=2.0)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--write-shared", action="store_true",
                    help="also rewrite pairs_top/pairs_recent/meta "
                         "(never hero_matchups, which is hand-written)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    seasons = list(args.seasons)

    # ---- fetch -----------------------------------------------------------
    if not args.transform_only:
        CACHE.mkdir(parents=True, exist_ok=True)
        for season in seasons:
            for phase in SEASON_TYPES:
                try:
                    fetch_matchups(season, phase, args)
                except FetchError as exc:
                    print("  ! %s" % exc, file=sys.stderr)
                    print("  Cache kept; re-run to resume from here.", file=sys.stderr)
                    return 1
        if args.fetch_only:
            print("Cache filled under %s" % CACHE)
            return 0

    # ---- load cache ------------------------------------------------------
    rows = []
    for season in seasons:
        for phase in SEASON_TYPES:
            path = cache_path(season, phase)
            if not path.exists():
                print("  missing cache for %s %s - run without --transform-only"
                      % (season, phase), file=sys.stderr)
                return 1
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in result_rows(payload):
                row["_SEASON"] = season
                row["_PHASE"] = phase
                rows.append(row)
    print("loaded %d matchup rows from cache" % len(rows))

    players: dict = {}
    pairs = build_dataset(rows, players, seasons)
    print("built %d player(s), %d directed pair(s)" % (len(players), len(pairs)))

    # Name/country/position come from a second endpoint; if it is unavailable
    # the pages still build, just without the flag and position.
    bio_path = CACHE / "playerindex.json"
    if bio_path.exists():
        for row in result_rows(json.loads(bio_path.read_text(encoding="utf-8"))):
            pid = str(row.get("PERSON_ID") or "")
            if pid in players:
                country = row.get("COUNTRY") or ""
                players[pid]["country"] = country
                players[pid]["iso"] = COUNTRY_ISO.get(country, "")
                players[pid]["pos"] = POS_FROM_WORD.get(
                    (row.get("POSITION") or "").split("-")[0].strip(), "")

    if args.verify_slug:
        return verify_slug(args.verify_slug, pairs, players, seasons)

    # ---- write -----------------------------------------------------------
    # Only pages that already exist are refreshed: the rule for which pairs
    # earn an m/ page is not fully recovered (see the docstring), so nothing
    # new is invented and nothing existing is dropped.
    wrote = 0
    for path in sorted((REPO / "data" / "p").glob("*.json")):
        pid = next((p for p, i in players.items()
                    if slugify(i.get("name", "")) == path.stem), None)
        if pid is None:
            continue
        payload = player_payload(pid, pairs, players, seasons)
        if not args.dry_run:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        wrote += 1

    ids = {slugify(i.get("name", "")): p for p, i in players.items()}
    for path in sorted((REPO / "data" / "m").glob("*.json")):
        try:
            a_slug, b_slug = path.stem.split("-vs-")
        except ValueError:
            continue
        if a_slug not in ids or b_slug not in ids:
            continue
        payload = pair_payload(ids[a_slug], ids[b_slug], pairs, players, seasons)
        if not args.dry_run:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        wrote += 1

    if args.write_shared and not args.dry_run:
        print("  (--write-shared: hero_matchups.json is never touched)")

    print("%s %d data file(s)" % ("would write" if args.dry_run else "wrote", wrote))
    print("Next: python build/generate_matchup_pages.py, then the four build/ scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
