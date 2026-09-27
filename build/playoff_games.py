#!/usr/bin/env python3
"""Playoff matchups, fetched one game at a time.

Imported by fetch_matchup_data.py; not run on its own.

WHY THIS EXISTS
---------------
leagueseasonmatchups does not serve playoffs. Probed from a residential
connection: the regular-season control returned 137,763 rows, while
SeasonType=Playoffs returned a valid but EMPTY table in every variant tried -
PerGame, blank ID params dropped, OffTeamID, DefTeamID, OffPlayerID and
DefPlayerID. "Post Season" and "Playoff" were rejected with HTTP 400, which
shows "Playoffs" is a recognised value with nothing behind it.

The committed data cannot stand in for it either. It stores playoffs only in
aggregate - byPhase.PO across all seasons, and bySeason with the two phases
mixed together - and no season x phase cell exists anywhere. Per-season
playoff numbers are recoverable exactly only for the 1,321 m/ pairs
(bySeason minus the fetched regular season), which is 5.9% of the opponent
rows that carry playoff data. So playoffs are rebuilt from per-game data:

  1. leaguegamelog, SeasonType=Playoffs, PlayerOrTeam=P
       -> the playoff game IDs for a season, and who appeared in each
  2. boxscorematchupsv3, one request per game
       -> that game's matchups
  3. aggregate each season's games into rows with the SAME shape as a
     leagueseasonmatchups row (SEASON_ID 4YYYY, OFF_/DEF_PLAYER_ID, GP,
     PARTIAL_POSS, PLAYER_PTS, MATCHUP_*), so the transform downstream is
     unchanged and treats them exactly like season-level rows.

The committed data then becomes the proof instead of the source: for every
completed season, fetched regular season + aggregated playoffs must equal the
committed bySeason cell, exactly.

Play-in games (IDs starting 005) are excluded. The committed data has only RS
and PO phases, and play-in is its own season type.

CACHING
-------
A finished game never changes, so each game response is cached permanently
and --refresh does not touch it. A completed season's game list is cached
permanently too; the latest season's list is re-requested every run (one
request), because it is the only one that can grow. An empty response is
never cached: a played playoff game always has matchups, so zero rows means
the request failed. A cached entry with zero rows is discarded and refetched.

NOT PROVEN - written without access to the API
----------------------------------------------
stats.nba.com is blocked from the environment this was written in. Until
--probe-boxscore and the verification have run on a residential connection:
  * both endpoints' parameter sets are unverified. The probe tries several
    boxscore parameter variants and records the one that returns rows.
  * the boxscorematchupsv3 response shape. Parsed as the nested V3 shape
    (boxScoreMatchups -> homeTeam/awayTeam -> players -> matchups ->
    statistics); a flat table with explicit personIdOff/personIdDef columns
    is accepted too.
  * ORIENTATION - whether the outer player in the nested shape is the
    offensive or the defensive one. Not guessed: the probe gives a hint from
    one game's points, and the verification aggregates both ways and keeps
    whichever reproduces the committed data exactly.
  * that the season endpoint counts GP whenever a pair has a row in a game,
    and that its PARTIAL_POSS is the per-game values summed, then rounded to
    one decimal. The strict gate would expose either assumption, and a
    failure that differs only in poss is labelled as rounding.
"""

import json
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GAMELOG_URL = "https://stats.nba.com/stats/leaguegamelog"
BOXSCORE_URL = "https://stats.nba.com/stats/boxscorematchupsv3"

PLAYOFF_GAME_PREFIX = "004"
PLAYIN_GAME_PREFIX = "005"

# boxscorematchupsv3 statistics keys -> the season endpoint's column names.
# Same quantities, same scale: counts are counts, partialPossessions is the
# per-game share of the season's PARTIAL_POSS. Mapped rather than renamed
# downstream so the aggregated rows are indistinguishable from season rows.
V3_TO_SEASON = {
    "partialPossessions":            "PARTIAL_POSS",
    "playerPoints":                  "PLAYER_PTS",
    "matchupAssists":                "MATCHUP_AST",
    "matchupTurnovers":              "MATCHUP_TOV",
    "matchupFieldGoalsMade":         "MATCHUP_FGM",
    "matchupFieldGoalsAttempted":    "MATCHUP_FGA",
    "matchupThreePointersMade":      "MATCHUP_FG3M",
    "matchupThreePointersAttempted": "MATCHUP_FG3A",
    "matchupFreeThrowsMade":         "MATCHUP_FTM",
    "matchupFreeThrowsAttempted":    "MATCHUP_FTA",
}

ORIENTATIONS = ("outer_is_offense", "outer_is_defense")
DEFAULT_ORIENTATION = "outer_is_offense"

# None is filled with the game ID.
BOXSCORE_PARAM_VARIANTS = [
    ("GameID + LeagueID", {"GameID": None, "LeagueID": "00"}),
    ("GameID only", {"GameID": None}),
    ("GameID + period/range params", {"GameID": None, "LeagueID": "00",
                                      "StartPeriod": "0", "EndPeriod": "0",
                                      "StartRange": "0", "EndRange": "0",
                                      "RangeType": "0"}),
]

STRATEGY_FILE = "po_games_strategy.json"
PROBE_SEASON = "2022-23"        # Denver won it, so Jokic has a full run of games
JOKIC_ID = "203999"


class EmptyGameData(RuntimeError):
    """The API answered, but with no rows. Never cached."""

    def __init__(self, label: str):
        super().__init__("%s: the API returned no rows" % label)
        self.label = label


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def list_path(cache: Path, season: str, subdir: str = "po_lists") -> Path:
    return cache / subdir / ("%s.json" % season)


def game_path(cache: Path, gid: str, subdir: str = "po_games") -> Path:
    return cache / subdir / ("%s.json" % gid)


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                 # noqa: BLE001
        return None


def _save(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _discard(path: Path, label: str) -> None:
    print("  %s: cached response has 0 rows - discarding and refetching" % label)
    try:
        path.unlink()
    except OSError:
        pass


def norm_game_id(gid) -> str:
    """leaguegamelog sends '0042200405'; a numeric 42200405 loses the zeros."""
    s = str(gid or "").strip()
    return s.zfill(10) if s.isdigit() else s


def table_rows(payload) -> list:
    """resultSets / resultSet -> list of dicts, first table with rows."""
    if not isinstance(payload, dict):
        return []
    sets = payload.get("resultSets") or payload.get("resultSet") or []
    if isinstance(sets, dict):
        sets = [sets]
    for rs in sets:
        if isinstance(rs, dict) and rs.get("rowSet"):
            headers = rs.get("headers") or []
            return [dict(zip(headers, row)) for row in rs["rowSet"]]
    return []


def _request_nonempty(url, params, label, args, http, counter):
    """Request until the response has rows; raise EmptyGameData otherwise."""
    for attempt in range(1, args.empty_retries + 1):
        payload = http(url, params, args.timeout, args.retries, args.retry_delay)
        time.sleep(args.delay)
        if counter(payload) > 0:
            return payload
        print("    %s: 0 rows - treating as a failed request (attempt %d/%d), not caching"
              % (label, attempt, args.empty_retries))
        if attempt < args.empty_retries:
            time.sleep(args.retry_delay * attempt)
    raise EmptyGameData(label)


def strategy(cache: Path) -> dict:
    data = _load(cache / STRATEGY_FILE) if (cache / STRATEGY_FILE).exists() else None
    return data if isinstance(data, dict) else {}


def save_strategy(cache: Path, **updates) -> dict:
    data = strategy(cache)
    data.update(updates)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / STRATEGY_FILE).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


# ---------------------------------------------------------------------------
# 1. the playoff game list for a season
# ---------------------------------------------------------------------------

def gamelog_params(season: str, season_type: str = "Playoffs") -> dict:
    return {"Counter": "0", "DateFrom": "", "DateTo": "", "Direction": "ASC",
            "LeagueID": "00", "PlayerOrTeam": "P", "Season": season,
            "SeasonType": season_type, "Sorter": "DATE"}


def fetch_game_list(season: str, is_latest: bool, cache: Path, args, http,
                    season_type: str = "Playoffs", subdir: str = "po_lists") -> list:
    """Player game-log rows for a season's playoffs.

    Cached for good once the season is not the latest one; the latest is
    re-requested each run because it is the only list that can still grow.
    """
    path = list_path(cache, season, subdir)
    label = "%s %s game list" % (season, "playoff" if season_type == "Playoffs" else season_type.lower())
    if path.exists() and not is_latest and not getattr(args, "refresh", False):
        payload = _load(path)
        if payload is not None and table_rows(payload):
            return table_rows(payload)
        _discard(path, label)
    print("  fetching %s" % label)
    payload = _request_nonempty(GAMELOG_URL, gamelog_params(season, season_type), label,
                                args, http, lambda p: len(table_rows(p)))
    _save(path, payload)
    return table_rows(payload)


def cached_game_list(season: str, cache: Path):
    path = list_path(cache, season)
    if not path.exists():
        return None
    payload = _load(path)
    return table_rows(payload) if payload is not None else None


REGULAR_SEASON_GAME_PREFIX = "002"


def games_in_list(rows: list, prefix: str = PLAYOFF_GAME_PREFIX) -> dict:
    """{game_id: {"date": ..., "players": {player_id, ...}}} for one game type
    (playoffs by default; 002 for the regular season)."""
    out = {}
    for r in rows:
        gid = norm_game_id(r.get("GAME_ID"))
        if not gid.startswith(prefix):
            continue
        g = out.setdefault(gid, {"date": r.get("GAME_DATE"), "players": set()})
        pid = str(r.get("PLAYER_ID") or "").strip()
        if pid:
            g["players"].add(pid)
    return out


def playin_count(rows: list) -> int:
    return len({norm_game_id(r.get("GAME_ID")) for r in rows
                if norm_game_id(r.get("GAME_ID")).startswith(PLAYIN_GAME_PREFIX)})


# ---------------------------------------------------------------------------
# 2. one game's matchups
# ---------------------------------------------------------------------------

def boxscore_params(gid: str, cache: Path) -> dict:
    variant = strategy(cache).get("boxscore_params") or {"GameID": None, "LeagueID": "00"}
    return {k: (gid if v is None else v) for k, v in variant.items()}


def _person_name(p: dict) -> str:
    name = ("%s %s" % (p.get("firstName") or "", p.get("familyName") or "")).strip()
    return name or (p.get("nameI") or "").strip()


def parse_game(payload) -> list:
    """Matchup records, orientation-agnostic.

    Each record: outer_id, outer_name, inner_id, inner_name, stats (V3 keys),
    explicit (True when the source names offence and defence itself, in which
    case outer = offence and the configured orientation is ignored).
    """
    recs = []
    if not isinstance(payload, dict):
        return recs

    root = payload.get("boxScoreMatchups")
    if isinstance(root, dict):
        for side in ("homeTeam", "awayTeam"):
            team = root.get(side) or {}
            for pl in team.get("players") or []:
                oid = str(pl.get("personId") or "").strip()
                for mu in pl.get("matchups") or []:
                    iid = str(mu.get("personId") or "").strip()
                    if not oid or not iid:
                        continue
                    recs.append({"outer_id": oid, "outer_name": _person_name(pl),
                                 "inner_id": iid, "inner_name": _person_name(mu),
                                 "stats": mu.get("statistics") or {},
                                 "explicit": False})
        return recs

    # Flat table, as some clients flatten V3 - offence and defence named.
    for row in table_rows(payload):
        off = row.get("personIdOff", row.get("PERSON_ID_OFF"))
        dfn = row.get("personIdDef", row.get("PERSON_ID_DEF"))
        if off in (None, "") or dfn in (None, ""):
            continue
        on = ("%s %s" % (row.get("firstNameOff") or "", row.get("familyNameOff") or "")).strip()
        dn = ("%s %s" % (row.get("firstNameDef") or "", row.get("familyNameDef") or "")).strip()
        recs.append({"outer_id": str(off), "outer_name": on,
                     "inner_id": str(dfn), "inner_name": dn,
                     "stats": {k: row.get(k) for k in V3_TO_SEASON},
                     "explicit": True})
    return recs


def fetch_game(gid: str, cache: Path, args, http, subdir: str = "po_games") -> dict:
    """One game's matchups, cached permanently once non-empty."""
    path = game_path(cache, gid, subdir)
    label = "game %s" % gid
    if path.exists():
        payload = _load(path)
        if payload is not None and parse_game(payload):
            return payload
        _discard(path, label)
    payload = _request_nonempty(BOXSCORE_URL, boxscore_params(gid, cache), label, args, http,
                                lambda p: len(parse_game(p)))
    _save(path, payload)
    return payload


# ---------------------------------------------------------------------------
# 3. aggregate games into season-level rows
# ---------------------------------------------------------------------------

def _dec(v) -> Decimal:
    if v in (None, ""):
        return Decimal(0)
    return Decimal(str(v))


def aggregate(games_by_season: dict, orientation: str) -> list:
    """{season: [(gid, payload), ...]} -> leagueseasonmatchups-shaped rows.

    GP is the number of games in which the pair has a row. PARTIAL_POSS is
    summed exactly (Decimal over the values as sent) and rounded to one
    decimal, half up, which is what a season-level total would show.
    """
    if orientation not in ORIENTATIONS:
        raise ValueError("unknown orientation %r" % orientation)
    rows = []
    for season in sorted(games_by_season):
        year = season.split("-")[0]
        acc = {}
        for gid, payload in games_by_season[season]:
            for rec in parse_game(payload):
                if rec["explicit"] or orientation == "outer_is_offense":
                    off, on, dfn, dn = (rec["outer_id"], rec["outer_name"],
                                        rec["inner_id"], rec["inner_name"])
                else:
                    off, on, dfn, dn = (rec["inner_id"], rec["inner_name"],
                                        rec["outer_id"], rec["outer_name"])
                a = acc.get((off, dfn))
                if a is None:
                    a = acc[(off, dfn)] = {"on": on, "dn": dn, "games": set(),
                                           "sums": {k: Decimal(0) for k in V3_TO_SEASON}}
                a["games"].add(gid)
                for k in V3_TO_SEASON:
                    a["sums"][k] += _dec(rec["stats"].get(k))
        for (off, dfn), a in acc.items():
            row = {"SEASON_ID": "4" + year, "_SEASON": season,
                   "OFF_PLAYER_ID": off, "OFF_PLAYER_NAME": a["on"],
                   "DEF_PLAYER_ID": dfn, "DEF_PLAYER_NAME": a["dn"],
                   "GP": len(a["games"])}
            for k, col in V3_TO_SEASON.items():
                v = a["sums"][k]
                if col == "PARTIAL_POSS":
                    row[col] = float(v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                else:
                    row[col] = int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# probe: one known playoff game
# ---------------------------------------------------------------------------

def _decimals(v) -> int:
    s = str(v)
    return len(s.split(".", 1)[1]) if "." in s else 0


def orientation_hint(recs: list, log_rows: list, gid: str):
    """Which reading of the nested shape makes points add up.

    If the outer player is the scorer, summing playerPoints over each outer
    player's matchups lands near that player's own points in the game log.
    If the outer player is the defender, the same holds grouped by the inner
    player instead. Returns (orientation, err_if_outer_off, err_if_outer_def).
    """
    pts = {}
    for r in log_rows:
        if norm_game_id(r.get("GAME_ID")) == gid and r.get("PTS") is not None:
            pts[str(r.get("PLAYER_ID"))] = float(r["PTS"])
    by_outer, by_inner = {}, {}
    for rec in recs:
        p = float(_dec(rec["stats"].get("playerPoints")))
        by_outer[rec["outer_id"]] = by_outer.get(rec["outer_id"], 0) + p
        by_inner[rec["inner_id"]] = by_inner.get(rec["inner_id"], 0) + p

    def err(sums):
        diffs = [abs(sums[k] - pts[k]) for k in sums if k in pts]
        return (sum(diffs) / len(diffs)) if diffs else None

    e_off, e_def = err(by_outer), err(by_inner)
    if e_off is None or e_def is None:
        return None, e_off, e_def
    return ("outer_is_offense" if e_off <= e_def else "outer_is_defense"), e_off, e_def


def probe(args, http) -> int:
    """Fetch ONE known playoff game and check it carries what we need."""
    cache = Path(args.cache_dir)
    season = args.probe_po_season
    print("=" * 70)
    print(" PROBE  per-game playoff matchups   season %s" % season)
    print("=" * 70)

    # ---- the game list ---------------------------------------------------
    try:
        log_rows = fetch_game_list(season, False, cache, args, http)
    except Exception as exc:                          # noqa: BLE001
        print("  game list FAILED: %s" % exc)
        print("  (leaguegamelog, SeasonType=Playoffs, PlayerOrTeam=P)")
        return 1
    games = games_in_list(log_rows)
    cols = sorted(log_rows[0]) if log_rows else []
    print("  game list        %d player-game rows, %d playoff games, %d play-in games excluded"
          % (len(log_rows), len(games), playin_count(log_rows)))
    print("                   columns: %s" % ", ".join(cols[:14]) + (" ..." if len(cols) > 14 else ""))
    need_cols = [c for c in ("GAME_ID", "PLAYER_ID") if c not in cols]
    if need_cols:
        print("  ! game list is missing %s" % ", ".join(need_cols))
        return 1
    jokic_games = sorted(g for g, v in games.items() if JOKIC_ID in v["players"])
    gid = jokic_games[0] if jokic_games else (sorted(games)[0] if games else None)
    if not gid:
        print("  ! no playoff game IDs in the list")
        return 1
    print("  probe game       %s  (%s)" % (gid, "Jokic played" if jokic_games else "first listed"))
    print()

    # ---- the game, trying parameter variants -----------------------------
    winner = None
    for label, variant in BOXSCORE_PARAM_VARIANTS:
        params = {k: (gid if v is None else v) for k, v in variant.items()}
        try:
            payload = http(BOXSCORE_URL, params, args.timeout, args.retries, args.retry_delay)
            n = len(parse_game(payload))
            print("  %-34s %6d matchup rows%s" % (label, n, "   <-- WORKS" if n and not winner else ""))
            if n and winner is None:
                winner = (label, variant, payload)
        except Exception as exc:                      # noqa: BLE001
            print("  %-34s  ERROR %s" % (label, exc))
        time.sleep(args.delay)
    if not winner:
        print("-" * 70)
        print(" No parameter variant returned matchup rows. Send this output to Claude.")
        return 1

    label, variant, payload = winner
    recs = parse_game(payload)
    shape = "nested V3 (outer/inner)" if isinstance(payload.get("boxScoreMatchups"), dict) \
        else "flat table (offence/defence named)"
    seen = set()
    for rec in recs:
        seen.update(k for k, v in rec["stats"].items() if v is not None)
    missing = [k for k in V3_TO_SEASON if k not in seen]
    poss_decimals = max((_decimals(r["stats"].get("partialPossessions"))
                         for r in recs if r["stats"].get("partialPossessions") is not None),
                        default=0)
    print()
    print("  shape            %s" % shape)
    print("  matchup rows     %d, outer players %d"
          % (len(recs), len({r["outer_id"] for r in recs})))
    print("  fields needed    %s" % ("all present" if not missing else "MISSING: " + ", ".join(missing)))
    for k, col in V3_TO_SEASON.items():
        print("      %-30s -> %-14s %s" % (k, col, "ok" if k in seen else "MISSING"))
    print("  partialPossessions decimals seen: %d" % poss_decimals)
    if poss_decimals <= 1:
        print("      ! one decimal per game: summing then rounding may land 0.1 off the")
        print("        season figure. The verify labels poss-only differences as rounding.")
    sample = next((r for r in recs if r["outer_id"] == JOKIC_ID or r["inner_id"] == JOKIC_ID),
                  recs[0])
    print("  sample           %s  <->  %s" % (sample["outer_name"], sample["inner_name"]))
    for k in V3_TO_SEASON:
        print("      %-30s %r" % (k, sample["stats"].get(k)))

    hint, e_off, e_def = orientation_hint(recs, log_rows, gid)
    if shape.startswith("flat"):
        hint, why = "outer_is_offense", "source names offence and defence explicitly"
    elif hint:
        why = "points error %.1f if outer=offence vs %.1f if outer=defence" % (e_off, e_def)
    else:
        why = "no game-log points to compare against"
    print("  orientation hint %s  (%s)" % (hint or "undetermined", why))
    print("                   The verification confirms it against the committed data.")

    print("-" * 70)
    if missing:
        print(" FAIL - required fields missing. Send this output to Claude.")
        return 1
    # Only a passing probe is recorded, so a failed one is retried next run.
    # The probe game is a finished game with rows: cache it like any other.
    save_strategy(cache, boxscore_params=variant, boxscore_params_label=label,
                  orientation_hint=hint)
    _save(game_path(cache, gid), payload)
    print(" OK - the per-game endpoint carries everything needed.")
    print("      Saved the working parameters to %s" % (cache / STRATEGY_FILE))
    return 0
