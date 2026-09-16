#!/usr/bin/env python3
"""Apply two UI tweaks to the generated matchup pages.

1. Remove the `<div class="foot">HoopsMatic</div>` credit block. The `.foot`
   CSS rule stays in place (nothing else uses it today, but removing it would
   be a style change, not a content change).

2. Add a compact heat-color legend where that footer used to be, i.e. directly
   below the last stat table on the page, plus the small `.heat-legend` CSS
   rule it needs.

The legend text differs between m/ and p/ because the pages colour different
things:

  m/  summary card  -> absHeatStyle(), fixed league-wide ranges
      season rows   -> heatStyle(), relative to the other seasons in the table
                       (falls back to absHeatStyle when only one season exists)

  p/  summary card  -> local ah(), same fixed ranges, direction flipped in the
                       "as defender" view
      opponent rows -> heatStyle(), relative to the other opponents shown,
                       with goodHigh flipped in the "as defender" view

index.html is handled for the footer only. Its featured-player mini table
colours FG%, 3P% and PTS/100 with its own pair of functions (relative to the
opponents listed, falling back to fixed ranges when the range is degenerate)
and has no TOV column and no direction flip, so neither legend above describes
it. Adding one there is a separate decision.

Idempotent: files already carrying the LEGEND_MARKER are skipped, so re-running
on an already-patched tree is a no-op. Use --dry-run to count without writing.

    python build/apply_ui_tweaks.py [--dry-run]

Run it after every regeneration of m/ and/or p/, alongside
build/fix_matchup_paths.py. It does not touch any ROOT / ${ROOT} path logic.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

LEGEND_MARKER = 'data-legend="heat"'

FOOTER_BLOCK = '  <div class="foot">\n    HoopsMatic\n  </div>\n'

# Anchor for the CSS insertion: the first line of the existing .foot rule,
# identical in every generated page under m/ and p/.
CSS_ANCHOR = ".foot{text-align:center;font-size:.72rem;color:var(--text-secondary);margin-top:1.6rem;\n"

LEGEND_CSS = """.heat-legend{margin-top:1.2rem;text-align:center;font-size:.72rem;
  color:var(--text-secondary);font-family:'JetBrains Mono',monospace;line-height:1.7}
.heat-legend .scale{display:inline-flex;align-items:center;gap:.35rem;
  vertical-align:middle;margin-right:.45rem}
.heat-legend .bar{display:inline-block;width:96px;height:8px;border-radius:4px;
  background:linear-gradient(90deg,hsl(0,70%,82%),hsl(60,70%,82%),hsl(120,70%,82%))}

"""

# Shared opening of the legend markup (swatch + "worse"/"better" labels).
def legend_html(body: str) -> str:
    return (
        '  <div class="heat-legend" %s>\n'
        '    <span class="scale"><span>worse</span><span class="bar"></span>'
        "<span>better</span></span>\n"
        "    %s\n"
        "  </div>\n" % (LEGEND_MARKER, body)
    )


M_BODY = (
    "Color scale, from the offensive player's point of view: red is worse, green is better. "
    "Summary cards are shaded against fixed league-wide ranges "
    "(FG% 35-55%, 3P% 20-45%, eFG% 40-62%, PTS/100 0-130, AST/100 0-12, TOV/100 0-15). "
    "Season rows are shaded relative to the other seasons in that table, or against the same "
    "fixed ranges when only one season is listed. TOV/100 is reversed: fewer is better."
)

P_BODY = (
    "Color scale, from the point of view of the player on this page: red is worse, green is "
    "better, so in the defender view a lower opponent number is green. The summary card is "
    "shaded against fixed league-wide ranges "
    "(FG% 35-55%, 3P% 20-45%, eFG% 40-62%, PTS/100 0-130, AST/100 0-12, TOV/100 0-15). "
    "Opponent rows are shaded relative to the other opponents shown in that table. TOV/100 is "
    "reversed: fewer is better on offense, more is better on defense."
)

LEGEND_M = legend_html(M_BODY)
LEGEND_P = legend_html(P_BODY)


def patch(path: Path, legend: str | None) -> str:
    """Return one of: skipped, changed, error:<reason>.

    legend=None means footer removal only (index.html).
    """
    text = path.read_text(encoding="utf-8")

    if LEGEND_MARKER in text:
        return "skipped"

    if FOOTER_BLOCK not in text:
        # Already stripped on an earlier run (index.html gets no marker), or
        # the page never had the block.
        return "skipped"

    if text.count(FOOTER_BLOCK) != 1:
        return "error:multiple footer blocks"

    if legend is None:
        # Also drop the blank line that separated the footer from the section
        # above it, so index.html does not end on a stray gap.
        new = text.replace("\n" + FOOTER_BLOCK, "")
    else:
        if CSS_ANCHOR not in text:
            return "error:css anchor not found"
        if text.count(CSS_ANCHOR) != 1:
            return "error:multiple css anchors"
        new = text.replace(CSS_ANCHOR, LEGEND_CSS + CSS_ANCHOR, 1)
        new = new.replace(FOOTER_BLOCK, legend)

    if new == text:
        return "skipped"

    path.write_text(new, encoding="utf-8")
    return "changed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    targets: list[tuple[Path, str | None]] = []
    for sub, legend in (("m", LEGEND_M), ("p", LEGEND_P)):
        for f in sorted((REPO / sub).glob("*.html")):
            targets.append((f, legend))
    index = REPO / "index.html"
    if index.exists():
        targets.append((index, None))

    changed = skipped = 0
    errors: list[str] = []

    for path, legend in targets:
        if args.dry_run:
            text = path.read_text(encoding="utf-8")
            if LEGEND_MARKER in text or FOOTER_BLOCK not in text:
                skipped += 1
            elif legend is not None and text.count(CSS_ANCHOR) != 1:
                errors.append("%s: css anchor not found" % path.relative_to(REPO))
            else:
                changed += 1
            continue

        result = patch(path, legend)
        if result == "changed":
            changed += 1
        elif result == "skipped":
            skipped += 1
        else:
            errors.append("%s: %s" % (path.relative_to(REPO), result.split(":", 1)[1]))

    verb = "would change" if args.dry_run else "changed"
    print("%s: %d, skipped (already done): %d, errors: %d"
          % (verb, changed, skipped, len(errors)))
    for e in errors:
        print("  ! %s" % e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
