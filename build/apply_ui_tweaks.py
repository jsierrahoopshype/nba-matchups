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

index.html gets its own legend text, because its featured-player mini table
colours only FG%, 3P% and PTS/100 with its own pair of functions: relative to
the opponents listed, falling back to fixed ranges only when the range is
degenerate. No TOV column and no direction flip, so neither legend above
describes it. That legend is injected into the JS template string that builds
the table rather than into the static HTML, so it exists only when the table
does (#featuredBlock is filled by JS and stays empty if the fetch fails). The
"Most frequent matchups" section is deliberately left alone: nothing in it is
colour-coded.

Idempotent: every edit is guarded independently (LEGEND_MARKER for the legend,
the presence of the footer block for the footer), so re-running on an
already-patched tree is a no-op. Use --dry-run to count without writing.

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

# index.html has its own .foot rule (margin-top differs from m/ and p/).
INDEX_CSS_ANCHOR = (
    ".foot{text-align:center;font-size:.72rem;color:var(--text-secondary);margin-top:3rem;\n"
)

# The featured-player mini table is built in a JS template literal, so the
# legend is appended inside that string: no table rendered, no legend.
INDEX_TABLE_ANCHOR = "      </table>`;\n"

INDEX_BODY = (
    "Color scale: green means the featured player performed better against that opponent, red "
    "worse. FG%, 3P% and PTS/100 are shaded relative to the other opponents listed, falling back "
    "to fixed league-wide ranges (FG% 35-55%, 3P% 20-45%, PTS/100 0-130) when every value is "
    "identical."
)

INDEX_TABLE_REPLACEMENT = (
    "      </table>\n"
    '      <div class="heat-legend" %s>\n'
    '        <span class="scale"><span>worse</span><span class="bar"></span>'
    "<span>better</span></span>\n"
    "        %s\n"
    "      </div>`;\n" % (LEGEND_MARKER, INDEX_BODY)
)


def rewrite(text: str, legend: str | None) -> tuple[str, str | None]:
    """Return (new_text, error). new_text == text means nothing to do.

    legend is the m/ or p/ legend block, or None for index.html, which is
    patched in its own way (see INDEX_TABLE_REPLACEMENT).
    """
    new = text

    # --- footer credit -------------------------------------------------
    # Guarded on its own so a tree where only the footer was stripped can
    # still pick up the legend on a later run.
    n_foot = new.count(FOOTER_BLOCK)
    if n_foot > 1:
        return text, "multiple footer blocks"
    if n_foot == 1:
        if legend is None:
            # Drop the blank line that separated the footer from the section
            # above it too, so index.html does not end on a stray gap.
            new = new.replace("\n" + FOOTER_BLOCK, "", 1)
        else:
            new = new.replace(FOOTER_BLOCK, legend, 1)

    # --- legend CSS rule -------------------------------------------------
    # Guarded on the CSS rule itself, NOT on LEGEND_MARKER: on m/ and p/ the
    # footer replacement above has already put the marker into `new`, so a
    # marker-based guard here silently skips the CSS on a freshly generated
    # page - legend markup, no gradient swatch. (index.html takes the same
    # path; only its anchor differs, since its .foot rule has a different
    # margin-top.)
    css_anchor = INDEX_CSS_ANCHOR if legend is None else CSS_ANCHOR
    if LEGEND_CSS not in new:
        if new.count(css_anchor) != 1:
            return text, "css anchor not found exactly once"
        new = new.replace(css_anchor, LEGEND_CSS + css_anchor, 1)

    # --- legend markup ----------------------------------------------------
    # On m/ and p/ the markup replaced the footer above. index.html puts it
    # inside the JS template literal that builds the featured-player table.
    if legend is None and LEGEND_MARKER not in new:
        if new.count(INDEX_TABLE_ANCHOR) != 1:
            return text, "index table anchor not found exactly once"
        new = new.replace(INDEX_TABLE_ANCHOR, INDEX_TABLE_REPLACEMENT, 1)

    if LEGEND_CSS in new and new.count(LEGEND_CSS) != 1:
        return text, "duplicate .heat-legend css rule"

    return new, None


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
        text = path.read_text(encoding="utf-8")
        new, err = rewrite(text, legend)
        if err:
            errors.append("%s: %s" % (path.relative_to(REPO), err))
            continue
        if new == text:
            skipped += 1
            continue
        changed += 1
        if not args.dry_run:
            path.write_text(new, encoding="utf-8")

    verb = "would change" if args.dry_run else "changed"
    print("%s: %d, skipped (already done): %d, errors: %d"
          % (verb, changed, skipped, len(errors)))
    for e in errors:
        print("  ! %s" % e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
