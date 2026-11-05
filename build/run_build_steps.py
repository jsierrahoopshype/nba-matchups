#!/usr/bin/env python3
"""Run the build/ fix scripts in exactly the order the GitHub Action runs them.

The step list is read from .github/workflows/apply-build-fixes.yml at run time
(every `python build/<script>.py` line, top to bottom), so the PC refresh and
the Action can never drift apart: change the workflow and this follows.

    python build/run_build_steps.py               # the 7 workflow steps
    python build/run_build_steps.py --generate    # generator first, then the 7
    python build/run_build_steps.py --list        # print the steps, run nothing

Stops at the first step that exits non-zero and returns its code. After
apply_ui_tweaks.py it also checks that every m/ and p/ page carries the heat
legend, which add_related_matchups.py anchors on, so a page the tweaks did not
finish is named there instead of surfacing two steps later.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "apply-build-fixes.yml"
GENERATOR = "generate_matchup_pages.py"
STEP = re.compile(r"^\s*python build/([A-Za-z0-9_]+\.py)\s*$")
LEGEND = 'class="heat-legend"'


def workflow_steps(path: Path = WORKFLOW) -> list:
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = STEP.match(line)
        if m:
            steps.append(m.group(1))
    if not steps:
        raise SystemExit("no `python build/...` steps found in %s" % path)
    return steps


def pages_missing_legend() -> list:
    out = []
    for kind in ("m", "p"):
        for page in sorted((REPO / kind).glob("*.html")):
            if page.stem == "template":
                continue
            if LEGEND not in page.read_bytes().decode("utf-8", "replace"):
                out.append("%s/%s" % (kind, page.name))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate", action="store_true",
                    help="run %s first (a full regeneration)" % GENERATOR)
    ap.add_argument("--list", action="store_true", help="print the steps and exit")
    args = ap.parse_args()

    steps = ([GENERATOR] if args.generate else []) + workflow_steps()
    if args.list:
        for i, s in enumerate(steps, 1):
            print("%d. %s" % (i, s))
        return 0

    for i, script in enumerate(steps, 1):
        print("== step %d/%d: %s" % (i, len(steps), script), flush=True)
        rc = subprocess.call([sys.executable, str(REPO / "build" / script)], cwd=str(REPO))
        if rc != 0:
            print("!! %s failed (exit %d); later steps not run" % (script, rc), flush=True)
            return rc or 1
        if script == "apply_ui_tweaks.py":
            missing = pages_missing_legend()
            if missing:
                print("!! after apply_ui_tweaks.py, %d page(s) have no heat legend, e.g. %s"
                      % (len(missing), ", ".join(missing[:5])), flush=True)
                return 1
    print("all %d step(s) passed" % len(steps), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
