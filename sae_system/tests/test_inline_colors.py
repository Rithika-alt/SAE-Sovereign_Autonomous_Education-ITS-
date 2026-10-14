"""Inline colours must actually show.

Bug: the global stylesheet had `.stApp * { color: ... !important }` (and the same for span/p/li).
A stylesheet !important beats an inline style, so every deliberately coloured element — the
Knowledge Graph legend dots, mastery labels, difficulty badges, the study timer — rendered plain
white. The rule now skips elements that set their own colour, which makes any inline colour that
is hard to read on the dark background suddenly visible, so those are pinned here too.
"""

import re
from pathlib import Path

import pytest

DASH = Path(__file__).resolve().parent.parent / "dashboard"
APP = (DASH / "app.py").read_text(encoding="utf-8")
CSS = APP[APP.index("<style>") + 7: APP.index("</style>")]
HIDDEN_PAGE_FILES = {"page_canvas.py", "page_activity.py", "page_friends.py", "page_system_evaluation.py",
                     "stress_relief_ui.py", "stress_manager.py"}
BG = (20, 20, 30)


def rules(css):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def forces_text_color(body):
    return re.search(r"(?<![-\w])color\s*:[^;]*!important", body) is not None


def test_no_global_rule_forces_text_colour_over_inline_colours():
    offenders = []
    for selector, body in rules(CSS):
        if not forces_text_color(body):
            continue
        for part in (s.strip() for s in selector.split(",")):
            # selectors that can reach OUR inline-styled markup (not Streamlit's own widget internals
            # such as button labels or radio labels, which never carry inline colours)
            reaches_our_markup = (
                part in (".stApp *", 'section[data-testid="stSidebar"] *')
                or re.fullmatch(r"\.(stApp|stMarkdown) (span|p|li)", part) is not None
            )
            if reaches_our_markup and ':not([style*="color"])' not in part:
                offenders.append(part)
    assert not offenders, f"these selectors override inline colours: {offenders}"


def test_the_default_text_colour_rule_still_exists_for_unstyled_elements():
    assert re.search(r'\.stApp \*:not\(\[style\*="color"\]\)\s*\{[^}]*color:\s*var\(--text-primary\)\s*!important', CSS)
    assert re.search(r'\.stApp span:not\(\[style\*="color"\]\)', CSS)


def test_the_sidebar_rule_also_respects_inline_colours():
    assert 'section[data-testid="stSidebar"] *:not([style*="color"])' in CSS


def test_headings_and_captions_keep_their_own_forced_colours():
    heading = next(b for s, b in rules(CSS) if ".stApp h1" in s)
    assert "color: var(--text-primary) !important" in heading


# ---- contrast of every literal inline colour on the pages students use

def _luminance(c):
    f = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _contrast(fg):
    a, b = _luminance(fg), _luminance(BG)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _parse(value):
    value = value.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{6})", value)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", value)
    if m:
        r, g, b = map(int, m.groups()[:3])
        a = float(m.group(4) or 1)
        return tuple(round(a * x + (1 - a) * y) for x, y in zip((r, g, b), BG))
    return None


def inline_colours():
    found = []
    for f in sorted(DASH.glob("*.py")):
        if f.name in HIDDEN_PAGE_FILES:
            continue
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"(?<![-\w])color:\s*([^;\"'}]+)", line):
                value = m.group(1).strip()
                if "{" in value or value.startswith("var(") or "!important" in value:
                    continue
                if (rgb := _parse(value)) is not None:
                    found.append((f"{f.name}:{ln}", value, _contrast(rgb)))
    return found


@pytest.mark.parametrize("where,value,contrast", inline_colours(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_inline_text_colour_is_readable_on_the_dark_background(where, value, contrast):
    assert contrast >= 3.0, f"{where}: color:{value} has contrast {contrast:.1f}:1 on the dark background"


def test_the_colours_that_were_effectively_invisible_are_gone():
    ti = (DASH / "test_interface.py").read_text(encoding="utf-8")
    assert "color:rgba(255,255,255,0.10)" not in ti and "color:rgba(56,189,248,0.18)" not in ti
    assert "color:rgba(255,255,255,0.10);margin-top:2px;\">Waiting" not in APP


def test_the_legend_dots_keep_three_distinct_colours():
    start = APP.index("Mastered (≥ 85%)")
    legend = APP[start - 120: APP.index("Not Started", start) + 40]
    assert {"#4ade80", "#fbbf24", "#8888a3"} <= set(re.findall(r"color:(#[0-9a-f]{6})", legend))
