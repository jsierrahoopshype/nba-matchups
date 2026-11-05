#!/usr/bin/env python3
"""Offline tests for the Windows build fixes:

  * run_build_steps.py runs exactly the GitHub Action's steps, in its order;
  * every page writer writes LF, whatever the OS (the Windows failure was
    text-mode writes producing CRLF, which add_related_matchups.py, reading
    bytes, could not match: "heat legend not found" on every page);
  * add_related_matchups.py, prerender_page_titles.py and
    update_sitemap_lastmod.py accept a CRLF page (a Git-for-Windows
    autocrlf checkout), write it back as the committed LF bytes, and do not
    move its sitemap date;
  * an NBA server error is a retriable FetchError(server=True); a 4xx is not;
  * fix_matchup_paths.py compiles with no SyntaxWarning.

One committed page is converted to CRLF for a moment and put back byte for
byte afterwards, whatever happens. No network.

    python build/test_build_fixes.py
"""

import io
import re
import subprocess
import sys
import urllib.error
import warnings
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import fetch_matchup_data as f  # noqa: E402
import run_build_steps as rbs   # noqa: E402

fails, passes = [], 0


def check(name, cond, detail=""):
    global passes
    if cond:
        passes += 1
    else:
        fails.append("%s %s" % (name, detail))


def run(*cmd):
    return subprocess.run([sys.executable] + list(cmd), cwd=str(REPO),
                          capture_output=True, text=True, encoding="utf-8")


# ---- 1. same steps, same order as the Action --------------------------------
steps = rbs.workflow_steps()
check("workflow steps", steps == [
    "fix_matchup_paths.py", "apply_ui_tweaks.py", "fix_canonical_urls.py",
    "prerender_matchup_tables.py", "add_related_matchups.py",
    "prerender_page_titles.py", "update_sitemap_lastmod.py"], repr(steps))
check("tweaks before related", steps.index("apply_ui_tweaks.py") < steps.index("add_related_matchups.py"))
check("lastmod last", steps[-1] == "update_sitemap_lastmod.py")
out = run("build/run_build_steps.py", "--list", "--generate").stdout.split()
check("--generate puts the generator first", "1." in out and out[out.index("1.") + 1] == "generate_matchup_pages.py")
check("every page has the legend now", rbs.pages_missing_legend() == [])
bats = (HERE / "weekly-refresh.bat").read_text(encoding="ascii")
check("weekly uses the runner", 'run_build_steps.py" --generate' in bats)
check("weekly has no own step list", "for %%S in" not in bats)

# ---- 2. every page writer passes newline="\n" ---------------------------------
for name in ("generate_matchup_pages", "apply_ui_tweaks", "fix_canonical_urls",
             "prerender_matchup_tables", "fetch_matchup_data", "playoff_games"):
    src = (HERE / ("%s.py" % name)).read_text(encoding="utf-8")
    calls = re.findall(r"write_text\((?:[^()]|\([^()]*(?:\([^()]*\)[^()]*)*\))*\)", src)
    check("%s: all write_text LF" % name, calls and all('newline="\\n"' in c for c in calls),
          repr([c for c in calls if 'newline="\\n"' not in c][:2]))

# ---- 3. a CRLF page goes through the byte-reading steps unharmed ------------
for bat in ("weekly-refresh", "refresh-matchup-data", "verify-matchup-fetch",
            "install-weekly-refresh", "diagnose-matchup-fetch", "run-matchup-check"):
    txt = (HERE / ("%s.bat" % bat)).read_bytes()
    check("%s.bat UTF-8 settings" % bat, b"chcp 65001" in txt and b'PYTHONUTF8=1' in txt
          and b"PYTHONIOENCODING=utf-8" in txt)
    check("%s.bat CRLF + ASCII" % bat, b"\r\n" in txt and b"\n" not in txt.replace(b"\r\n", b"")
          and all(c < 128 for c in txt))

slug = "nikola-jokic"
page = REPO / "p" / ("%s.html" % slug)
sitemap = REPO / "sitemap.xml"
store = HERE / "sitemap-hashes.json"
saved = {p: p.read_bytes() for p in (page, sitemap, store)}
try:
    lf = saved[page]
    check("committed page is LF", b"\r" not in lf)
    page.write_bytes(lf.replace(b"\n", b"\r\n"))
    r = run("build/update_sitemap_lastmod.py", "--check")
    check("CRLF page keeps its sitemap date", r.returncode == 0, r.stdout[-200:])
    r = run("build/add_related_matchups.py", "--only", slug)
    check("add_related accepts CRLF", r.returncode == 0 and "legend not found" not in r.stdout + r.stderr,
          (r.stdout + r.stderr)[-300:])
    page.write_bytes(lf.replace(b"\n", b"\r\n"))
    r = run("build/prerender_page_titles.py")
    check("titles accept CRLF", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    check("CRLF page written back as the committed LF bytes", page.read_bytes() == lf)
finally:
    for p, b in saved.items():
        p.write_bytes(b)

# ---- 4. NBA server errors are retriable, 4xx are not ------------------------
def fake_urlopen(code):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
    return _open


with mock.patch("urllib.request.urlopen", fake_urlopen(503)), mock.patch("time.sleep"):
    try:
        f.http_json("https://stats.nba.com/x", {}, 1, 2, 0)
        check("503 raises", False)
    except f.FetchError as exc:
        check("503 is a server error", exc.server is True)
with mock.patch("urllib.request.urlopen", fake_urlopen(400)), mock.patch("time.sleep"):
    try:
        f.http_json("https://stats.nba.com/x", {}, 1, 2, 0)
        check("400 raises", False)
    except f.FetchError as exc:
        check("400 is not a server error", exc.server is False)

import types  # noqa: E402
import tempfile  # noqa: E402
rs = f._RSGames(Path(tempfile.mkdtemp()), types.SimpleNamespace(), ["2024-25"])
rs.lists["2024-25"] = {"0022400001": {"date": "2024-11-01", "players": {"1", "2"}}}
with mock.patch.object(f.pg, "fetch_game",
                       side_effect=f.FetchError("gave up: HTTP 503", server=True)):
    check("server error -> no payloads", rs.payloads("2024-25", ("1", "2")) is None)
    check("...flagged as server error", rs.last_server_error is True)
    check("...kept out of the hard errors", rs.errors == [] and len(rs.server_errors) == 1)
with mock.patch.object(f.pg, "fetch_game", side_effect=f.FetchError("HTTP 404", server=False)):
    rs.payloads("2024-25", ("1", "2"))
    check("4xx stays a hard error", rs.last_server_error is False and len(rs.errors) == 1)
check("status text", f.NOT_TESTED_SERVER == "NOT TESTED (NBA server error, retried)")

# ---- 5. no SyntaxWarning ----------------------------------------------------
with warnings.catch_warnings():
    warnings.simplefilter("error")
    for py in sorted(HERE.glob("*.py")):
        try:
            compile(py.read_text(encoding="utf-8"), str(py), "exec")
        except SyntaxWarning as exc:
            check("no SyntaxWarning in %s" % py.name, False, str(exc))

print("build fix tests: %d passed, %d failed" % (passes, len(fails)))
for msg in fails:
    print("  FAIL %s" % msg)
sys.exit(1 if fails else 0)
