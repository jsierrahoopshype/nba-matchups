#!/usr/bin/env python3
"""Write the list of available headshot files the pages read.

The pages used to ask GitHub's API for the whole nba-headshots file tree on
every visit (api.github.com/repos/.../git/trees/main?recursive=1), so every
visitor's browser contacted GitHub. Now the build does it once and commits the
answer next to the other data files, which the pages load from hoopsmatic.com:

    data/headshots/face-fill.json      index.html (playerId -> file name)
    data/headshots/face-fill-320.json  m/ pages   (playerId -> file name)

Same content the pages built from the API before: every .webp in
players/headshots/<variant>/, keyed by the player ID before the first "-".

The file list comes from a blob-less, depth-1 git clone of nba-headshots
(file names only, no images, no API rate limit). If that fails (no network,
GitHub down) the committed lists are left exactly as they are and the step
still passes, so a build never breaks or loses photos over it.

    python build/update_headshot_list.py [--from-dir CLONE]

--from-dir reads an existing nba-headshots checkout instead of cloning.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "headshots"
SOURCE = "https://github.com/jsierrahoopshype/nba-headshots.git"
VARIANTS = ("face-fill", "face-fill-320")
PREFIX = "players/headshots/"
# The names go straight into <img src>, so only plain "<id>-<slug>.webp" is kept.
NAME = re.compile(r"[0-9]+-[a-z0-9-]+\.webp")


def build_maps(paths):
    """{variant: {playerId: filename}} from repo-relative paths."""
    maps = {v: {} for v in VARIANTS}
    for path in paths:
        parts = path.split("/")
        if len(parts) != 4 or path[:len(PREFIX)] != PREFIX or parts[2] not in maps:
            continue
        name = parts[3]
        if not NAME.fullmatch(name):
            continue
        dash = name.find("-")
        maps[parts[2]][name[:dash]] = name
    return maps


def list_files(clone: Path):
    out = subprocess.run(
        ["git", "-C", str(clone), "ls-tree", "-r", "--name-only", "HEAD", "--"]
        + [PREFIX + v + "/" for v in VARIANTS],
        capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout.splitlines()


def clone_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "nba-headshots"
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                        "--depth", "1", SOURCE, str(dest)],
                       capture_output=True, text=True, timeout=300, check=True)
        return list_files(dest)


def dump(m) -> str:
    # One entry per line, sorted: small diffs when a photo is added.
    return "{\n" + ",\n".join("%s:%s" % (json.dumps(k), json.dumps(m[k]))
                              for k in sorted(m, key=lambda x: (len(x), x))) + "\n}\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-dir", help="an nba-headshots checkout to read instead of cloning")
    args = ap.parse_args()

    try:
        paths = list_files(Path(args.from_dir)) if args.from_dir else clone_and_list()
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (str(getattr(exc, "stderr", "") or exc).strip().splitlines() or ["?"])[-1]
        print("update_headshot_list: could not list nba-headshots (%s); "
              "keeping the committed lists" % detail)
        return 0

    maps = build_maps(paths)
    # A near-empty answer means something went wrong upstream, not that the
    # photos are gone: never replace a good list with it.
    if any(len(maps[v]) < 100 for v in VARIANTS):
        print("update_headshot_list: suspiciously few files (%s); keeping the committed lists"
              % ", ".join("%s=%d" % (v, len(maps[v])) for v in VARIANTS))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for v in VARIANTS:
        path = OUT_DIR / ("%s.json" % v)
        text = dump(maps[v])
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        print("update_headshot_list: %s %d file(s)%s"
              % (path.relative_to(REPO).as_posix(), len(maps[v]), "" if old != text else " (unchanged)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
