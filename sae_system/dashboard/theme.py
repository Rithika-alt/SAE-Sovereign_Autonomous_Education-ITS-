"""Shared dark-theme palette constants — same values as the CSS custom
properties injected once in dashboard/app.py's global <style> block.

Every page that builds its own inline-styled HTML (rather than using the
shared .sae-card/.metric-card CSS classes) should import from here instead
of hardcoding hex values, so the whole app can be re-themed from one place.
"""

BG_VOID = "#0a0a0f"
BG_SURFACE = "rgba(255,255,255,0.045)"
BG_SURFACE_HI = "rgba(255,255,255,0.08)"
BORDER_GLASS = "rgba(255,255,255,0.10)"
BORDER_GLASS_HI = "rgba(255,255,255,0.20)"

TEXT_PRIMARY = "#f2f2f8"
TEXT_SECONDARY = "#a3a3bd"
TEXT_MUTED = "#6f6f8c"

ACCENT_1 = "#7c6ef5"   # purple
ACCENT_2 = "#38bdf8"   # cyan/blue
GRADIENT_1 = "linear-gradient(135deg,#7c6ef5 0%,#38bdf8 100%)"
GLOW_1 = "rgba(124,110,245,0.45)"

# Status colors, brightened for legibility on a dark background.
STATUS_GREEN = "#4ade80"
STATUS_AMBER = "#fbbf24"
STATUS_RED = "#f87171"
STATUS_BLUE = "#7c6ef5"
STATUS_GRAY = "#8888a3"
