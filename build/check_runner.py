#!/usr/bin/env python3
"""One check round: run the read-only verify, and if it does not pass, the
read-only investigation of why. Everything printed goes to the console and to
build/last-check.txt, which run-matchup-check.bat opens in Notepad.

    python build/check_runner.py [--log build/last-check.txt]

run-matchup-check.bat (on main) downloads this file from the fetcher-dev
branch along with the rest of build/, so what a round runs can change without
another merge. The .bat stays small and fixed; the steps live here.

Read-only on the repository: verify-matchup-fetch.bat and
fetch_matchup_data.py --verify-slug never write under data/, m/ or p/. The
only files written are the log, the %TEMP% cache and the verification marker
under %LOCALAPPDATA%.
"""
import argparse
import datetime
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

BUILD = Path(__file__).resolve().parent
REPO = BUILD.parent
SLUG = "nikola-jokic"


def verify_cache() -> Path:
    # Same folder verify-matchup-fetch.bat uses, so the investigation reads
    # what verify just fetched instead of downloading it again.
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp") / "hoopsmatic-verify-cache"


class Tee:
    def __init__(self, log_path: Path, preamble: str):
        self.f = open(log_path, "w", encoding="utf-8-sig", newline="\r\n")
        if preamble:
            self.f.write(preamble.rstrip("\n") + "\n")
            self.f.flush()

    def line(self, text=""):
        try:
            print(text, flush=True)
        except UnicodeEncodeError:                  # a console that can't show "ć"
            print(text.encode("ascii", "replace").decode("ascii"), flush=True)
        self.f.write(text + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def run_step(tee: Tee, title: str, cmd: list) -> int:
    tee.line("")
    tee.line("#" * 78)
    tee.line("# %s" % title)
    tee.line("# %s" % " ".join(cmd))
    tee.line("#" * 78)
    env = dict(os.environ, HOOPSMATIC_NONINTERACTIVE="1", PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        tee.line("! could not start: %s" % exc)
        return 99
    for raw in proc.stdout:
        tee.line(raw.decode("utf-8", "replace").rstrip("\r\n"))
    rc = proc.wait()
    tee.line("# exit code %d after %.0f s" % (rc, time.time() - t0))
    return rc


def file_table() -> list:
    """Short hashes of the build files that ran, so the log says which versions."""
    out = []
    for p in sorted(BUILD.glob("*.py")) + sorted(BUILD.glob("*.bat")):
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        out.append("  %-34s %s  %7d bytes" % (p.name, h, p.stat().st_size))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(BUILD / "last-check.txt"))
    ap.add_argument("--no-investigate", action="store_true")
    args = ap.parse_args()

    log = Path(args.log)
    preamble = ""
    if log.exists():
        # The .bat writes its download report to the log first; keep it.
        preamble = log.read_bytes().decode("utf-8-sig", "replace").replace("\r\n", "\n")
    tee = Tee(log, preamble)
    started = datetime.datetime.now()
    tee.line("")
    tee.line("=" * 78)
    tee.line(" CHECK RUNNER   %s" % started.strftime("%Y-%m-%d %H:%M:%S"))
    tee.line(" repo      %s" % REPO)
    tee.line(" python    %s" % sys.version.split()[0])
    tee.line(" cache     %s" % verify_cache())
    tee.line(" build files that will run:")
    for row in file_table():
        tee.line(row)
    tee.line("=" * 78)

    if os.name == "nt":
        verify_cmd = ["cmd", "/d", "/c", str(BUILD / "verify-matchup-fetch.bat")]
    else:                                           # for testing off Windows
        verify_cmd = [os.environ.get("HOOPSMATIC_VERIFY_CMD", "false")]
    rc_verify = run_step(tee, "STEP 1  verify-matchup-fetch.bat", verify_cmd)

    rc_inv = None
    if rc_verify == 1 and not args.no_investigate:
        # Verify ran and found differences: find out why. Exit 2 means there
        # was nothing to compare, so there is nothing to investigate either.
        rc_inv = run_step(tee, "STEP 2  investigation of the differing cells", [
            sys.executable, str(BUILD / "fetch_matchup_data.py"),
            "--verify-slug", SLUG, "--cache-dir", str(verify_cache()), "--investigate"])
    elif rc_verify == 1:
        tee.line("\n(investigation skipped: --no-investigate)")
    else:
        tee.line("\n(no investigation: verify exit code %d)" % rc_verify)

    tee.line("")
    tee.line("=" * 78)
    tee.line(" SUMMARY")
    tee.line("   verify         exit %d  %s" % (rc_verify, {0: "PASS", 1: "FAIL (mismatches)",
                                                        2: "COULD NOT CHECK"}.get(rc_verify, "ERROR")))
    if rc_inv is not None:
        tee.line("   investigation  exit %d" % rc_inv)
    tee.line("   finished       %s  (%.0f min)" % (
        datetime.datetime.now().strftime("%H:%M:%S"),
        (datetime.datetime.now() - started).total_seconds() / 60))
    tee.line("   Paste this whole file to Claude.")
    tee.line("=" * 78)
    tee.close()
    return rc_verify


if __name__ == "__main__":
    raise SystemExit(main())
