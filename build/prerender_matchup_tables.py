#!/usr/bin/env python3
"""Bake the default-view stat tables into the HTML of m/ and p/ pages.

The pages render everything client-side from data/m/<slug>.json and
data/p/<slug>.json. Google executes JS but crawls JS-dependent pages slowly
and unreliably, which is why most of this section sits at "Discovered -
currently not indexed". This writes the default view straight into the HTML
so the content is in the source.

PROGRESSIVE ENHANCEMENT, NOT REPLACEMENT
----------------------------------------
No JavaScript is modified, removed or disabled. The baked markup goes into
the SAME containers the JS writes to:

    m/  ->  #content                    (renderDirections)
    p/  ->  #career, #oppContainer      (renderCareer, renderOpponents)

On load the JS fetches its JSON exactly as before and overwrites those
containers with its own output. Because the baked markup is byte-identical
to what the JS produces for the default state, the swap is invisible; and if
the baked markup were ever wrong, the live page would simply correct itself.
That self-correcting property is the safety model - do not break it by
making the JS conditional on the baked content.

WHAT IS BAKED
-------------
Only the default state, i.e. what the page shows on load:

    m/  phase "all"
    p/  dir "asOff", window "all", phase "all", sortKey "pts_per_100",
        sortAsc false, minPoss 50, empty query

The Regular season / Playoffs / As defender / Range / Min sample toggles and
the opponent search stay JS-only: they are behind a click, so a crawler never
sees them anyway.

Headshots are NOT baked. The player cards (#cardA / #cardB on m/) resolve
their image URLs through a GitHub tree API lookup at runtime, so image
handling is left entirely to the JS.

index.html is not touched: its featured player rotates on every load, so a
baked table there would go stale.

The templates (m/template.html, p/template.html) have no slug and therefore
no data, so they are skipped.

FIDELITY
--------
The helpers below are ports of the page's own functions - pctFmt, numFmt,
absHeatStyle, heatStyle, the ah() summary helper, the row builders - kept
line-for-line alongside the originals, including the exact whitespace of the
template literals. JS number formatting is reproduced rather than
approximated:

  * js_to_fixed    - ECMA-262 Number.prototype.toFixed: round-half-away-from-
                     zero on the EXACT binary value of the double, not on its
                     shortest decimal form. Python's format() rounds half to
                     even, which disagrees on ties.
  * js_to_locale   - Intl.NumberFormat en-US default: up to 3 fraction digits,
                     half-expand, trailing zeros stripped, comma grouping.
                     (See the locale note at the bottom of this docstring.)
  * js_math_round  - Math.round is floor(x + 0.5), not round-half-even.

The output was verified byte-for-byte against the pages' own JavaScript,
executed in Node against a DOM shim, for every page in m/ and p/.

LINK PATHS: the only ROOT-dependent markup inside a baked container is the
opponent link on p/ pages (m/ containers have no links at all). ROOT is
derived from location.pathname at runtime, so a baked href can only be right
for one host. It is baked for the canonical one, "/matchups/" on
hoopsmatic.com - the same host fix_canonical_urls.py points every canonical
and og:url at. On GitHub Pages the JS recomputes ROOT and rewrites the hrefs
on load, exactly as it does today. Pass --root to bake a different prefix.

LOCALE NOTE: toLocaleString() follows the *visitor's* locale, so a visitor in
a comma-decimal locale sees "1.234,5" where this bakes the en-US "1,234.5".
The JS overwrites the baked markup on load either way, so what the visitor
ends up reading is always correct; only the crawler-visible source is fixed,
and en-US is what Googlebot requests.

Idempotent: containers already carrying data-prerendered="1" are skipped.
Use --dry-run to count without writing.

    python build/prerender_matchup_tables.py [--dry-run] [--only SLUG ...]

Run it after every regeneration of m/ and/or p/, after fix_matchup_paths.py
and apply_ui_tweaks.py. It does not touch the ROOT / ${ROOT} path logic, the
heat legends, the canonical/OG URLs, or any <script> block.
"""

import argparse
import json
import math
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MARKER = 'data-prerendered="1"'

DASH = '<span class="dash">—</span>'


# --------------------------------------------------------------------------
# JS-exact primitives
# --------------------------------------------------------------------------

def js_to_fixed(x: float, digits: int) -> str:
    """Number.prototype.toFixed (ECMA-262 21.1.3.3).

    The spec picks the integer n minimising |n / 10**f - x|, breaking ties
    towards the larger n, having first taken the absolute value. That is
    round-half-away-from-zero over the exact binary value of the double.
    Decimal(float) is exact, so quantising it with ROUND_HALF_UP matches.
    """
    if x != x or x in (float("inf"), float("-inf")):
        return "NaN" if x != x else ("Infinity" if x > 0 else "-Infinity")
    neg = x < 0
    d = Decimal(abs(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    s = format(d, "f")
    return ("-" + s) if (neg and d != 0) else s


def js_to_locale(x) -> str:
    """Number.prototype.toLocaleString() with the en-US default options.

    Intl.NumberFormat defaults: minimumFractionDigits 0, maximumFractionDigits
    3, roundingMode "halfExpand", grouping on.
    """
    neg = x < 0
    d = Decimal(abs(float(x))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    s = format(d, "f")
    whole, _, frac = s.partition(".")
    frac = frac.rstrip("0")
    whole = "{:,}".format(int(whole))
    out = whole + ("." + frac if frac else "")
    return ("-" + out) if (neg and out.strip("0.,") != "") else out


def js_math_round(x: float) -> int:
    """Math.round: floor(x + 0.5), so .5 always goes towards +Infinity."""
    return math.floor(x + 0.5)


def esc(s) -> str:
    """The page's esc(): a text node's innerHTML serialisation.

    Sets textContent and reads innerHTML back, which escapes &, non-breaking
    space, < and > - and notably NOT quotes.
    """
    return (str(s if s else "")
            .replace("&", "&amp;")
            .replace(" ", "&nbsp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def pct_fmt(v):
    if v is None:
        return DASH
    return "%s%%" % js_to_fixed(v * 100, 1)


def num_fmt(v, dp=0):
    if v is None:
        return DASH
    return js_to_fixed(v, dp) if dp else js_to_locale(v)


def dec1(v):
    return DASH if v is None else js_to_fixed(v, 1)


def clamp01(t):
    return max(0.0, min(1.0, t))


def hsl_style(t) -> str:
    hue = js_math_round(120 * clamp01(t))
    return ' style="background-color:hsl(%d,70%%,82%%)"' % hue


# Fixed league-wide bands, shared by m/'s absHeatStyle and p/'s ah().
def _abs_t(value, kind):
    if kind == "fgPct":
        return (value - 0.35) / (0.55 - 0.35)
    if kind == "fg3Pct":
        return (value - 0.20) / (0.45 - 0.20)
    if kind == "efg":
        return (value - 0.40) / (0.62 - 0.40)
    if kind == "ptsPer100":
        return (value - 0) / (130 - 0)
    if kind == "astPer100":
        return (value - 0) / (12 - 0)
    if kind == "tovPer100":
        return 1 - ((value - 0) / (15 - 0))
    if kind == "tov":
        return 1 - (value / 10)
    return None


def abs_heat_style(value, kind) -> str:
    """m/'s absHeatStyle()."""
    if value is None:
        return ""
    t = _abs_t(value, kind)
    if t is None:
        return ""
    return hsl_style(t)


def heat_style(value, vmin, vmax, good_high) -> str:
    """The heatStyle() shared by m/ and p/: relative to a column's range."""
    if value is None or vmax == vmin:
        return ""
    t = (value - vmin) / (vmax - vmin)
    if not good_high:
        t = 1 - t
    return hsl_style(t)


def _ratios(s):
    """The per-stat derivations both summary builders do from raw totals."""
    fg_pct = s["fgm"] / s["fga"] if s["fga"] > 0 else None
    fg3_pct = s["fg3m"] / s["fg3a"] if s["fg3a"] > 0 else None
    efg = ((s["fgm"] + 0.5 * s["fg3m"]) / s["fga"]) if s["fga"] > 0 else None
    pts100 = (100 * s["pts"] / s["poss"]) if s["poss"] > 0 else None
    ast100 = (100 * s["ast"] / s["poss"]) if s["poss"] > 0 else None
    tov100 = (100 * s["tov"] / s["poss"]) if s["poss"] > 0 else None
    return fg_pct, fg3_pct, efg, pts100, ast100, tov100


# --------------------------------------------------------------------------
# m/ : renderSummary + renderSeasonsTable + renderDirections, phase "all"
# --------------------------------------------------------------------------

def m_render_summary(dir_data, defender_name):
    s = dir_data.get("career")
    if not s or (s.get("poss") or 0) == 0:
        return ('<div class="empty">No matchup data when guarded by %s in this phase.</div>'
                % esc(defender_name))
    fg_pct, fg3_pct, efg, pts100, ast100, tov100 = _ratios(s)
    cells = [
        ("GAMES", js_to_locale(s["games"]), None),
        ("POSS", js_to_fixed(s["poss"], 1), None),
        ("PTS", js_to_locale(s["pts"]), None),
        ("FGA", js_to_locale(s["fga"]), None),
        ("FG%", pct_fmt(fg_pct), abs_heat_style(fg_pct, "fgPct")),
        ("3P%", pct_fmt(fg3_pct), abs_heat_style(fg3_pct, "fg3Pct")),
        ("eFG%", pct_fmt(efg), abs_heat_style(efg, "efg")),
        ("PTS/100", dec1(pts100), abs_heat_style(pts100, "ptsPer100")),
        ("AST/100", dec1(ast100), abs_heat_style(ast100, "astPer100")),
        ("TOV/100", dec1(tov100), abs_heat_style(tov100, "tovPer100")),
    ]
    body = "".join(
        '<div class="cell"%s><span class="lbl">%s</span><span class="val">%s</span></div>'
        % (style or "", lbl, val) for lbl, val, style in cells)
    return '<div class="summary">%s</div>' % body


M_SEASON_KEYS = ("fgPct", "fg3Pct", "efg", "ptsPer100", "astPer100", "tovPer100")

# Verbatim from renderSeasonsTable's template literal, up to ${rows}.
M_SEASONS_TABLE_HEAD = (
    '<div class="table-wrap"><table class="seasons">\n'
    '    <thead><tr>\n'
    '      <th class="left">Season</th><th>GP</th><th>POSS</th>\n'
    '      <th>FGA</th><th>3PA</th>\n'
    '      <th>FG%</th><th>3P%</th><th>eFG%</th>\n'
    '      <th>PTS/100</th><th>AST/100</th><th>TOV/100</th>\n'
    '    </tr></thead>\n'
    '    <tbody>'
)


def m_render_seasons_table(dir_data):
    seasons = dir_data.get("bySeason") or {}
    ordered = sorted(seasons.items(), key=lambda kv: kv[0])
    if not ordered:
        return ""

    enriched = []
    for season, s in ordered:
        fg_pct, fg3_pct, efg, pts100, ast100, tov100 = _ratios(s)
        enriched.append({
            "season": season, "s": s, "fgPct": fg_pct, "fg3Pct": fg3_pct,
            "efg": efg, "ptsPer100": pts100, "astPer100": ast100,
            "tovPer100": tov100,
        })

    ranges = {}
    for key in M_SEASON_KEYS:
        vals = [e[key] for e in enriched if e[key] is not None]
        ranges[key] = [min(vals), max(vals)] if vals else None

    use_absolute = len(ordered) < 2

    def style_for(value, kind, good_high):
        if use_absolute:
            return abs_heat_style(value, kind)
        rng = ranges[kind]
        if not rng:
            return ""
        return heat_style(value, rng[0], rng[1], good_high)

    rows = []
    for e in enriched:
        s = e["s"]
        rows.append(
            '<tr>\n'
            '      <td class="season">%s</td>\n'
            '      <td>%s</td>\n'
            '      <td>%s</td>\n'
            '      <td>%s</td>\n'
            '      <td>%s</td>\n'
            '      <td%s>%s</td>\n'
            '      <td%s>%s</td>\n'
            '      <td%s>%s</td>\n'
            '      <td%s>%s</td>\n'
            '      <td%s>%s</td>\n'
            '      <td%s>%s</td>\n'
            '    </tr>' % (
                esc(e["season"]), s["games"], js_to_fixed(s["poss"], 1),
                s["fga"], s["fg3a"],
                style_for(e["fgPct"], "fgPct", True), pct_fmt(e["fgPct"]),
                style_for(e["fg3Pct"], "fg3Pct", True), pct_fmt(e["fg3Pct"]),
                style_for(e["efg"], "efg", True), pct_fmt(e["efg"]),
                style_for(e["ptsPer100"], "ptsPer100", True), dec1(e["ptsPer100"]),
                style_for(e["astPer100"], "astPer100", True), dec1(e["astPer100"]),
                style_for(e["tovPer100"], "tovPer100", False), dec1(e["tovPer100"]),
            ))

    return (M_SEASONS_TABLE_HEAD
            + "".join(rows)
            + "</tbody>\n  </table></div>")


def m_render_directions(data):
    a, b = data["playerA"], data["playerB"]
    return (
        '\n'
        '    <div class="dir-section">\n'
        '      <h2>%s on offense · guarded by %s</h2>\n'
        '      %s\n'
        '      %s\n'
        '    </div>\n'
        '    <div class="dir-section">\n'
        '      <h2>%s on offense · guarded by %s</h2>\n'
        '      %s\n'
        '      %s\n'
        '    </div>' % (
            esc(a["name"]), esc(b["name"]),
            m_render_summary(data["aGuardedByB"], b["name"]),
            m_render_seasons_table(data["aGuardedByB"]),
            esc(b["name"]), esc(a["name"]),
            m_render_summary(data["bGuardedByA"], a["name"]),
            m_render_seasons_table(data["bGuardedByA"]),
        ))


# --------------------------------------------------------------------------
# p/ : renderCareer + renderOpponents, default state
# --------------------------------------------------------------------------

P_MIN_POSS = 50
P_SORT_KEY = "pts_per_100"

# The ROOT the JS computes on the canonical host (hoopsmatic.com/matchups/).
DEFAULT_ROOT = "/matchups/"

# cols from renderOpponents, with goodHigh resolved for dir "asOff".
P_COLS = [
    {"k": "name", "t": "Opponent", "left": True, "noHeat": True},
    {"k": "pts_per_100", "t": "PTS/100", "goodHigh": True, "fmt": "dec1"},
    {"k": "efg_pct", "t": "eFG%", "goodHigh": True, "fmt": "pct"},
    {"k": "fg_pct", "t": "FG%", "goodHigh": True, "fmt": "pct"},
    {"k": "fg3_pct", "t": "3P%", "goodHigh": True, "fmt": "pct"},
    {"k": "poss", "t": "POSS", "goodHigh": True, "fmt": "poss"},
    {"k": "games", "t": "G", "goodHigh": True, "fmt": "int"},
    {"k": "fga", "t": "FGA", "goodHigh": True, "fmt": "int"},
    {"k": "fg3a", "t": "3PA", "goodHigh": True, "fmt": "int"},
    {"k": "ast_per_100", "t": "AST/100", "goodHigh": True, "fmt": "dec1"},
    {"k": "tov_per_100", "t": "TOV/100", "goodHigh": False, "fmt": "dec1"},
]


def flag_img(iso, country, cls="opp-flag"):
    if not iso:
        return ""
    return ('<img class="%s" src="https://flagcdn.com/h20/%s.png" '
            'srcset="https://flagcdn.com/h40/%s.png 2x" alt="%s" title="%s" '
            'loading="lazy">' % (cls, iso, iso, esc(country), esc(country)))


def p_visible_opps(data):
    """visibleOpps() for the default state: dir asOff, window/phase all."""
    out = []
    for o in data.get("asOff") or []:
        stats = o.get("career")
        if stats is None:
            continue
        poss = stats.get("poss") or 0
        if poss <= 0 or poss < P_MIN_POSS:
            continue
        out.append({"o": o, "s": stats})
    # sort((a, b) => vb - va) with a stable sort, values defaulting to -1.
    out.sort(key=lambda e: (e["s"].get(P_SORT_KEY) if e["s"].get(P_SORT_KEY) is not None else -1),
             reverse=True)
    return out


P_SUM_KEYS = ("games", "poss", "pts", "fgm", "fga", "fg3m", "fg3a", "ast", "tov")


def p_render_career(opps):
    """renderCareer() for dir asOff. #career has no wrapper element."""
    opp_count = len(opps)
    total = {k: 0 for k in P_SUM_KEYS}
    for e in opps:                       # same iteration order as the JS, so
        for k in P_SUM_KEYS:             # float addition rounds identically
            total[k] += (e["s"].get(k) or 0)

    _, _, efg, pts100, ast100, tov100 = _ratios(total)

    def ah(value, kind):
        if value is None:
            return ""
        t = _abs_t(value, kind)
        if t is None:
            return ""
        return hsl_style(t)              # dir "asOff": no flip

    cells = [
        ("OPP", js_to_locale(opp_count), None),
        ("POSS", num_fmt(total["poss"], 0), None),
        ("PTS/100", dec1(pts100), ah(pts100, "ptsPer100")),
        ("eFG%", pct_fmt(efg), ah(efg, "efg")),
        ("AST/100", dec1(ast100), ah(ast100, "astPer100")),
        ("TOV/100", dec1(tov100), ah(tov100, "tovPer100")),
    ]
    return "".join(
        '<div class="cell"%s><span class="lbl">%s</span><span class="val">%s</span></div>'
        % (style or "", lbl, val) for lbl, val, style in cells)


def p_render_opponents(data, h2h_pairs, root=DEFAULT_ROOT):
    opps = p_visible_opps(data)
    if not opps:
        return "<div class='empty'>No matchups for this filter.</div>", p_render_career(opps)

    ranges = {}
    for col in P_COLS:
        if col.get("noHeat"):
            continue
        vals = [e["s"].get(col["k"]) for e in opps if e["s"].get(col["k"]) is not None]
        if vals:
            ranges[col["k"]] = [min(vals), max(vals)]

    # `${left} ${sorted} ${asc}` - sortAsc is false by default, so `asc` is
    # always empty here and the trailing space is part of the markup.
    head = "".join(
        '<th class="%s %s %s" data-k="%s">%s</th>' % (
            "left" if col.get("left") else "",
            "sorted" if col["k"] == P_SORT_KEY else "",
            "",
            col["k"], col["t"])
        for col in P_COLS)

    rows = []
    for e in opps:
        o, s = e["o"], e["s"]
        cells = []
        for col in P_COLS:
            if col.get("noHeat"):
                a, b = sorted([data["slug"], o["slug"]])
                pair_key = "%s-vs-%s" % (a, b)
                link_href = ("%sm/%s.html" % (root, pair_key) if pair_key in h2h_pairs
                             else "%sp/%s.html" % (root, esc(o["slug"])))
                opp_link = '<a href="%s">%s</a>' % (esc(link_href), esc(o["name"]))
                cells.append('<td class="opp"><span class="opp-name">%s%s</span></td>'
                             % (flag_img(o.get("iso"), o.get("country")), opp_link))
                continue
            v = s.get(col["k"])
            if col["fmt"] == "pct":
                display = pct_fmt(v)
            elif col["fmt"] in ("dec1", "poss"):
                display = dec1(v)
            else:
                display = DASH if v is None else js_to_locale(v)
            rng = ranges.get(col["k"])
            style = heat_style(v, rng[0], rng[1], col["goodHigh"]) if (rng and v is not None) else ""
            cells.append("<td%s>%s</td>" % (style, display))
        rows.append("<tr>%s</tr>" % "".join(cells))

    html = ('\n'
            '    <div class="table-wrap">\n'
            '      <table class="opps">\n'
            '        <thead><tr>%s</tr></thead>\n'
            '        <tbody>%s</tbody>\n'
            '      </table>\n'
            '    </div>' % (head, "".join(rows)))
    return html, p_render_career(opps)


def load_h2h_pairs():
    """The Set the page builds from data/pairs_top.json."""
    path = REPO / "data" / "pairs_top.json"
    if not path.exists():
        return set()
    pairs = json.loads(path.read_text(encoding="utf-8"))
    out = set()
    for p in pairs:
        a = (p.get("off") or {}).get("slug")
        b = (p.get("def") or {}).get("slug")
        if a and b:
            lo, hi = sorted([a, b])
            out.add("%s-vs-%s" % (lo, hi))
    return out


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------

# The static containers, exactly as fix_matchup_paths.py / apply_ui_tweaks.py
# leave them.
M_CONTAINER = '<div id="content"><div class="empty">Loading...</div></div>'
P_CAREER = '<div class="career-summary" id="career"></div>'
P_OPPS = ('<div id="oppContainer">\n'
          '    <div class="empty">Loading...</div>\n'
          '  </div>')


def fill(tag_id: str, inner: str, cls: str = "") -> str:
    """Rebuild a container div with the baked content and the idempotency marker."""
    cls_attr = ' class="%s"' % cls if cls else ""
    return '<div%s id="%s" %s>%s</div>' % (cls_attr, tag_id, MARKER, inner)


def rewrite_m(text: str, data) -> tuple[str, str | None]:
    if MARKER in text:
        return text, None
    if text.count(M_CONTAINER) != 1:
        return text, "#content container not found exactly once"
    inner = m_render_directions(data)
    return text.replace(M_CONTAINER, fill("content", inner), 1), None


def rewrite_p(text: str, data, h2h_pairs, root=DEFAULT_ROOT) -> tuple[str, str | None]:
    if MARKER in text:
        return text, None
    if text.count(P_CAREER) != 1:
        return text, "#career container not found exactly once"
    if text.count(P_OPPS) != 1:
        return text, "#oppContainer container not found exactly once"
    opps_html, career_html = p_render_opponents(data, h2h_pairs, root)
    new = text.replace(P_CAREER, fill("career", career_html, "career-summary"), 1)
    new = new.replace(P_OPPS, fill("oppContainer", opps_html), 1)
    return new, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    ap.add_argument("--only", nargs="*", default=None,
                    help="limit to these page paths (e.g. m/foo.html)")
    ap.add_argument("--root", default=DEFAULT_ROOT,
                    help="site root to bake into p/ opponent links "
                         "(default: %s, the canonical host's path)" % DEFAULT_ROOT)
    args = ap.parse_args()

    h2h_pairs = load_h2h_pairs()

    pages = []
    for sub in ("m", "p"):
        for f in sorted((REPO / sub).glob("*.html")):
            if f.name == "template.html":
                continue
            pages.append(f)
    if args.only:
        wanted = {str(REPO / x) for x in args.only}
        pages = [p for p in pages if str(p) in wanted]

    changed = skipped = 0
    errors: list[str] = []

    for page in pages:
        rel = page.relative_to(REPO)
        slug = page.stem
        data_path = REPO / "data" / rel.parts[0] / ("%s.json" % slug)
        if not data_path.exists():
            errors.append("%s: no data file at %s" % (rel, data_path.relative_to(REPO)))
            continue
        text = page.read_text(encoding="utf-8")
        if MARKER in text:
            skipped += 1
            continue
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
            if rel.parts[0] == "m":
                new, err = rewrite_m(text, data)
            else:
                new, err = rewrite_p(text, data, h2h_pairs, args.root)
        except Exception as exc:                      # noqa: BLE001 - reported
            errors.append("%s: %s: %s" % (rel, type(exc).__name__, exc))
            continue
        if err:
            errors.append("%s: %s" % (rel, err))
            continue
        if new == text:
            skipped += 1
            continue
        changed += 1
        if not args.dry_run:
            page.write_text(new, encoding="utf-8")

    verb = "would change" if args.dry_run else "changed"
    print("%s: %d, skipped (already prerendered): %d, errors: %d"
          % (verb, changed, skipped, len(errors)))
    for e in errors[:20]:
        print("  ! %s" % e, file=sys.stderr)
    if len(errors) > 20:
        print("  ... and %d more" % (len(errors) - 20), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
