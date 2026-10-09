"""
Visual identity for the channel. Change values here to rebrand every video at once.

Everything downstream reads from this file, so a colour or font change here
propagates to all future renders without touching renderer code.
"""

from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_DIR = ASSETS / "fonts"

# ---------------------------------------------------------------- canvas ----
W, H = 1080, 1920
FPS = 30

# YouTube Shorts overlays chrome on top of your video. These bounds keep text
# clear of the channel name, description, and the like/comment/share rail.
#   - bottom ~420px: title, channel handle, sound attribution
#   - right ~150px:  action buttons (only matters below y≈900)
SAFE_LEFT = 80
SAFE_RIGHT = 1000
SAFE_TOP = 230
SAFE_BOTTOM = 1460

# Narrower column for anything sitting low enough to collide with the buttons.
SAFE_RIGHT_LOW = 900

# ---------------------------------------------------------------- colour ----
BG = (10, 13, 18)              # near-black, faintly blue
SURFACE = (21, 26, 34)         # raised cards
SURFACE_HI = (30, 37, 48)      # hover / emphasis
TEXT = (255, 255, 255)
TEXT_DIM = (196, 205, 218)
MUTED = (126, 136, 153)

ACCENT = (245, 165, 36)        # amber — primary highlight, "the answer"
ACCENT_DARK = (168, 110, 18)
COOL = (63, 169, 245)          # blue — the comparison counterpart
GOOD = (46, 204, 113)
BAD = (231, 76, 60)

# Comparison bars: the winner takes ACCENT, everything else recedes to this.
# Colouring every bar differently makes the viewer hunt for the point.
NEUTRAL_BAR = (66, 77, 95)
SERIES = [ACCENT, COOL, (156, 136, 255), (255, 118, 117)]

# ----------------------------------------------------------------- fonts ----
# Inter Display for headlines (tighter, made for large sizes), Inter for body.
F_BLACK = str(FONT_DIR / "InterDisplay-Black.otf")
F_BOLD = str(FONT_DIR / "InterDisplay-Bold.otf")
F_SEMI = str(FONT_DIR / "Inter-SemiBold.otf")
F_MEDIUM = str(FONT_DIR / "Inter-Medium.otf")
F_REGULAR = str(FONT_DIR / "Inter-Regular.otf")

# ---------------------------------------------------------------- motion ----
INTRO = 0.38          # seconds for elements to animate in at the top of a scene
STAGGER = 0.07        # delay between successive elements
SHOW_PROGRESS_BAR = True   # thin accent line at the very top: "how much is left"

# --------------------------------------------------------------- content ----
CURRENCY = "AED"
WORDMARK = "THE AUTO EDITS"

# The last line every viewer reads. It used to say "Answer in the comments" —
# which asked for a comment, and got zero across 199 videos. Ninety days of
# analytics said 39 of 41 videos with real views converted nobody, while one
# video converted at 19 per thousand: the channel can convert 50x its own
# average, so the bottleneck is not the videos. It is that nobody is asked.
#
# Change this to whatever the channel actually promises. A reason beats a plea:
# "Subscribe" alone is noise, "UAE car rules, explained" is a reason to stay.
END_CTA = "Subscribe \u2014 UAE car answers, weekly"
