"""
Motion-graphics renderer.

Builds a 1080x1920 vertical video out of typographic scenes and pipes raw
frames straight into ffmpeg (no intermediate PNGs). No stock footage, no
third-party clips, so there is nothing here that can be copyright-claimed.

Scene timings are normally derived from the voiceover (see pipeline.py), so the
visuals land on the words rather than drifting out of sync.

    scenes = [HookScene("Is the *Model Y* still worth it in Dubai?"), ...]
    render(scenes, "voice.mp3", "out.mp4")
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import theme as T


# ============================================================== utilities ==

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def ease_out_cubic(p: float) -> float:
    return 1.0 - pow(1.0 - p, 3)


def ease_out_expo(p: float) -> float:
    return 1.0 if p >= 1 else 1.0 - pow(2, -9 * p)


def lerp(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def fade(colour, alpha: float, base=T.BG):
    """Blend `colour` toward `base`. Cheaper than real alpha compositing and
    visually identical when everything sits on a flat background."""
    a = clamp(alpha)
    return tuple(int(round(lerp(base[i], colour[i], a))) for i in range(3))


def anim(t: float, index: int = 0, rise: float = 44.0, dur: float = T.INTRO):
    """Standard entrance: fade up while sliding into place.
    Returns (alpha, y_offset)."""
    p = clamp((t - index * T.STAGGER) / dur)
    e = ease_out_cubic(p)
    return e, (1.0 - e) * rise


_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, int(size))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, int(size))
    return _font_cache[key]


def text_w(d: ImageDraw.ImageDraw, s: str, f) -> float:
    return d.textlength(s, font=f)


def money(value: float, currency: str = T.CURRENCY) -> str:
    return f"{currency} {int(round(value)):,}"


# ------------------------------------------------------------ rich text ---
# A word wrapped in *asterisks* is drawn in the accent colour. Used to make one
# phrase in a hook pop without hand-positioning anything.

@dataclass
class Word:
    text: str
    accent: bool


def parse_rich(s: str) -> list[Word]:
    """`*` toggles accent. A word inherits the state active at its first
    character, so trailing punctuation stays attached: *resale hit*? works."""
    out: list[Word] = []
    cur, accent_now, cur_accent = "", False, False
    for ch in s:
        if ch == "*":
            accent_now = not accent_now
            continue
        if ch.isspace():
            if cur:
                out.append(Word(cur, cur_accent))
                cur = ""
            continue
        if not cur:
            cur_accent = accent_now
        cur += ch
    if cur:
        out.append(Word(cur, cur_accent))
    return out


def centred_top(h: float, top: float = T.SAFE_TOP,
                bottom: float = T.SAFE_BOTTOM) -> float:
    """Vertical origin that centres a block of height `h` in the safe area.
    Shorts are watched one thumb-flick at a time — content floating at the top
    of a tall empty frame reads as unfinished."""
    return top + max(0.0, (bottom - top - h) / 2.0)


def wrap_rich(d, words: list[Word], f, max_w: float) -> list[list[Word]]:
    lines: list[list[Word]] = [[]]
    space = text_w(d, " ", f)
    cur = 0.0
    for w in words:
        ww = text_w(d, w.text, f)
        if lines[-1] and cur + space + ww > max_w:
            lines.append([w])
            cur = ww
        else:
            cur += (space if lines[-1] else 0) + ww
            lines[-1].append(w)
    return lines


def fit_rich(d, text: str, path: str, max_w: float, max_h: float,
             start: int, min_size: int = 34, line_ratio: float = 1.08):
    """Shrink the font until the wrapped block fits the given box."""
    words = parse_rich(text)
    size = start
    while size > min_size:
        f = font(path, size)
        lines = wrap_rich(d, words, f, max_w)
        lh = size * line_ratio
        if len(lines) * lh <= max_h:
            return f, lines, lh
        size -= 3
    f = font(path, min_size)
    return f, wrap_rich(d, words, f, max_w), min_size * line_ratio


def draw_rich(d, lines: list[list[Word]], f, x: float, y: float, lh: float,
              alpha: float, base=T.BG, colour=T.TEXT, accent=T.ACCENT,
              stagger_lines: float = 0.0, t: float = 0.0):
    """Draw wrapped rich text. If stagger_lines > 0 each line fades in slightly
    after the one above it, which reads as the sentence 'arriving'."""
    space = text_w(d, " ", f)
    for li, line in enumerate(lines):
        if stagger_lines:
            a, dy = anim(t, index=li, rise=28.0)
            a *= alpha
        else:
            a, dy = alpha, 0.0
        cx = x
        for w in line:
            d.text((cx, y + li * lh + dy), w.text, font=f,
                   fill=fade(accent if w.accent else colour, a, base))
            cx += text_w(d, w.text, f) + space


# ================================================================= scenes ==

class Scene:
    duration: float = 3.0

    def background(self, img: Image.Image, t: float) -> None:
        """Pixels behind the type. Most scenes draw on the flat theme colour
        and leave this alone; a photo scene paints the frame here so that the
        wordmark, progress bar and captions all land on top of it."""
        return None

    def render(self, d: ImageDraw.ImageDraw, t: float) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class HookScene(Scene):
    """Opening frame. One question, one accented phrase. This is the single
    highest-leverage element in the whole video."""
    text: str
    kicker: str | None = None
    duration: float = 3.0

    def render(self, d, t):
        box_w = T.SAFE_RIGHT - T.SAFE_LEFT
        kicker_h = 130 if self.kicker else 0

        f, lines, lh = fit_rich(d, self.text, T.F_BLACK, box_w,
                                T.SAFE_BOTTOM - T.SAFE_TOP - kicker_h - 60,
                                start=118, min_size=54)
        y = centred_top(kicker_h + len(lines) * lh)

        if self.kicker:
            a, dy = anim(t, 0, rise=24)
            d.text((T.SAFE_LEFT, y + dy), self.kicker.upper(),
                   font=font(T.F_SEMI, 40), fill=fade(T.ACCENT, a))
            rule = ease_out_expo(clamp((t - 0.1) / 0.5)) * 120
            if rule > 1:
                d.rounded_rectangle(
                    [T.SAFE_LEFT, y + 62 + dy, T.SAFE_LEFT + rule, y + 68 + dy],
                    radius=3, fill=fade(T.ACCENT, a))
            y += kicker_h

        draw_rich(d, lines, f, T.SAFE_LEFT, y, lh, 1.0,
                  stagger_lines=T.STAGGER, t=t - 0.12)


def num(v: float, like: float | None = None) -> str:
    """Format a figure without lying about it.

    int(round()) turned AED 3.80 into "AED 4" on screen. `like` is the final
    value, so a counting animation keeps the same number of decimals all the
    way up instead of flickering between 3 and 3.80.
    """
    ref = v if like is None else like
    dp = 0 if abs(ref - round(ref)) < 1e-9 else 2
    return f"{v:,.{dp}f}"


@dataclass
class StatScene(Scene):
    """One number, counted up. Use for a price, a depreciation figure, a range."""
    label: str
    value: float
    prefix: str = T.CURRENCY
    suffix: str = ""
    footnote: str | None = None
    duration: float = 3.0

    def render(self, d, t):
        # Size the number off its final value so the type doesn't jump while
        # it counts up.
        final = f"{self.prefix} {num(self.value)}".strip() \
            if self.prefix else num(self.value)
        if self.suffix:
            final += self.suffix
        size = 190
        while text_w(d, final, font(T.F_BLACK, size)) > (T.SAFE_RIGHT - T.SAFE_LEFT) \
                and size > 90:
            size -= 6

        foot = None
        if self.footnote:
            foot = fit_rich(d, self.footnote, T.F_MEDIUM,
                            T.SAFE_RIGHT_LOW - T.SAFE_LEFT, 300,
                            start=48, min_size=34, line_ratio=1.32)

        total = 62 + 28 + size * 1.05 + (40 + len(foot[1]) * foot[2] if foot else 0)
        y = centred_top(total)

        a, dy = anim(t, 0, rise=28)
        d.text((T.SAFE_LEFT, y + dy), self.label.upper(), font=font(T.F_SEMI, 46),
               fill=fade(T.MUTED, a))

        p = ease_out_expo(clamp((t - 0.15) / 0.9))
        shown = f"{self.prefix} {num(self.value * p, self.value)}".strip() \
            if self.prefix else num(self.value * p, self.value)
        if self.suffix:
            shown += self.suffix
        a2, dy2 = anim(t, 1, rise=40)
        d.text((T.SAFE_LEFT, y + 90 + dy2), shown, font=font(T.F_BLACK, size),
               fill=fade(T.TEXT, a2))

        if foot:
            f3, lines, lh = foot
            a3, dy3 = anim(t, 2, rise=24)
            draw_rich(d, lines, f3, T.SAFE_LEFT,
                      y + 90 + size * 1.05 + 40 + dy3, lh, a3, colour=T.TEXT_DIM)


@dataclass
class CompareRow:
    name: str
    value: float
    note: str | None = None


@dataclass
class CompareScene(Scene):
    """Animated horizontal bars. The core visual for 'X vs Y' content."""
    title: str
    rows: list[CompareRow]
    prefix: str = T.CURRENCY
    suffix: str = ""
    lower_is_better: bool = True
    duration: float = 4.5

    def render(self, d, t):
        ft, tlines, tlh = fit_rich(d, self.title, T.F_BOLD,
                                   T.SAFE_RIGHT - T.SAFE_LEFT, 240,
                                   start=70, min_size=44, line_ratio=1.12)
        if not self.rows:
            return

        heights = [212 if r.note else 154 for r in self.rows]
        y = centred_top(len(tlines) * tlh + 64 + sum(heights))

        a, dy = anim(t, 0, rise=26)
        draw_rich(d, tlines, ft, T.SAFE_LEFT, y + dy, tlh, a)
        y += len(tlines) * tlh + 64

        best = min(r.value for r in self.rows) if self.lower_is_better \
            else max(r.value for r in self.rows)
        vmax = max(r.value for r in self.rows) or 1.0
        bar_w = T.SAFE_RIGHT_LOW - T.SAFE_LEFT

        for i, r in enumerate(self.rows):
            ra, rdy = anim(t, i + 1, rise=30)
            top = y + rdy
            winner = r.value == best
            # Only the answer gets colour. Everything else recedes — otherwise
            # a rainbow of bars makes the viewer hunt for the point.
            col = T.ACCENT if winner else T.NEUTRAL_BAR

            grow = ease_out_cubic(clamp((t - 0.25 - i * 0.12) / 0.85))
            vtxt = f"{self.prefix} {num(r.value * grow, r.value)}".strip() \
                if self.prefix else num(r.value * grow, r.value)
            final = f"{self.prefix} {num(r.value)}".strip() \
                if self.prefix else num(r.value)
            if self.suffix:
                vtxt += self.suffix
                final += self.suffix

            # Fit the label in what the value leaves behind. Row names used to
            # be drawn at a fixed 50px, which was fine for "Nissan Patrol" and
            # collides with the figure for "Car up to AED 50,000". Measured
            # against the *final* value, so nothing reflows mid-animation.
            vf = font(T.F_BOLD, 50)
            room = (T.SAFE_RIGHT_LOW - text_w(d, final, vf) - 56) - T.SAFE_LEFT
            nsize = 50
            while text_w(d, r.name, font(T.F_SEMI, nsize)) > room and nsize > 34:
                nsize -= 2
            d.text((T.SAFE_LEFT, top + (50 - nsize) * 0.5), r.name,
                   font=font(T.F_SEMI, nsize),
                   fill=fade(T.TEXT if winner else T.TEXT_DIM, ra))

            d.text((T.SAFE_RIGHT_LOW, top), vtxt, font=vf,
                   anchor="ra", fill=fade(T.ACCENT if winner else T.TEXT_DIM, ra))

            by = top + 82
            d.rounded_rectangle([T.SAFE_LEFT, by, T.SAFE_LEFT + bar_w, by + 26],
                                radius=13, fill=fade(T.SURFACE, ra))
            w = bar_w * (r.value / vmax) * grow
            if w > 4:
                d.rounded_rectangle([T.SAFE_LEFT, by, T.SAFE_LEFT + w, by + 26],
                                    radius=13, fill=fade(col, ra))

            if r.note:
                d.text((T.SAFE_LEFT, by + 46), r.note, font=font(T.F_MEDIUM, 38),
                       fill=fade(T.MUTED, ra))
            y += heights[i]


class PhotoScene(Scene):
    """A photograph you took, with the channel's type over it.

    Two things make this look like a channel rather than a slideshow. The
    frame never sits still — a slow push in gives a still image the motion the
    feed expects — and the caption always has a scrim under it, because white
    type over an unpredictable photo is legible right up until the one frame
    where it isn't.

    Not a dataclass: the image is loaded and pre-scaled once at construction,
    since resizing a 12-megapixel JPEG nine hundred times is the difference
    between a render that takes twenty seconds and one that takes ten minutes.
    """

    ZOOM = 1.10          # start scale; eases back to 1.0 across the scene

    def __init__(self, path: str, caption: str = "", kicker: str = "",
                 duration: float = 2.4, zoom_in: bool = True):
        self.caption, self.kicker = caption, kicker
        self.duration, self.zoom_in = duration, zoom_in

        img = Image.open(path)
        # Phones store the sensor frame and a rotation tag rather than rotated
        # pixels. Skip this and every portrait photo lands on its side — and
        # because a bare `except Exception` swallowed the NameError from a
        # missing import the first time, it did so silently.
        img = ImageOps.exif_transpose(img) or img
        img = img.convert("RGB")

        # Cover the canvas at maximum zoom, cropping the overflow rather than
        # letterboxing — a black bar down a vertical video reads as a mistake.
        tw, th = int(T.W * self.ZOOM), int(T.H * self.ZOOM)
        scale = max(tw / img.width, th / img.height)
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
        left, top = (img.width - tw) // 2, (img.height - th) // 2
        self.src = img.crop((left, top, left + tw, top + th))

        self._scrim = self._make_scrim()

    @staticmethod
    def _make_scrim() -> Image.Image:
        """Bottom-up darkening, so caption type is always readable."""
        h = int(T.H * 0.42)
        grad = Image.new("L", (1, h))
        for y in range(h):
            grad.putpixel((0, y), int(232 * (y / (h - 1)) ** 1.7))
        alpha = grad.resize((T.W, h))
        layer = Image.new("RGB", (T.W, h), T.BG)
        return Image.merge("RGBA", (*layer.split(), alpha))

    def background(self, img: Image.Image, t: float) -> None:
        p = clamp(t / max(self.duration, 0.01))
        e = ease_out_cubic(p) if self.zoom_in else 1.0 - ease_out_cubic(p)
        # Ease from ZOOM back to 1.0: a push that decelerates reads as
        # deliberate, where a linear one reads as a stock transition.
        z = T.W + (self.src.width - T.W) * (1.0 - e)
        w = int(round(z))
        h = int(round(w * T.H / T.W))
        left = (self.src.width - w) // 2
        top = (self.src.height - h) // 2
        frame = self.src.crop((left, top, left + w, top + h))
        if (w, h) != (T.W, T.H):
            frame = frame.resize((T.W, T.H), Image.BILINEAR)
        img.paste(frame, (0, 0))
        if self.caption or self.kicker:
            img.paste(self._scrim, (0, T.H - self._scrim.height),
                      self._scrim)

    def render(self, d, t):
        if not (self.caption or self.kicker):
            return
        a, dy = anim(t, 0, rise=22, dur=0.5)
        y = T.SAFE_BOTTOM - 60

        if self.caption:
            f, lines, lh = fit_rich(d, self.caption, T.F_BOLD,
                                    T.SAFE_RIGHT - T.SAFE_LEFT, 260,
                                    start=64, min_size=40, line_ratio=1.16)
            y -= len(lines) * lh
            draw_rich(d, lines, f, T.SAFE_LEFT, y + dy, lh, a)

        if self.kicker:
            d.text((T.SAFE_LEFT, y - 58 + dy), self.kicker.upper(),
                   font=font(T.F_SEMI, 36), fill=fade(T.ACCENT, a))


class ClipScene(PhotoScene):
    """A few seconds of video you shot, cropped to the vertical frame.

    Stills carry information; motion is what stops a thumb. One clip of a door
    opening does more for retention than three more photographs of the same car
    parked, so the two belong in the same edit.

    Frames are extracted once with ffmpeg into a temporary directory and read
    back one at a time. Decoding on the fly would mean holding a decoder open
    across the whole render, and holding the decoded segment in memory would
    cost about half a gigabyte for three seconds — a folder of JPEGs costs
    thirty megabytes and reads in a few milliseconds a frame.
    """

    def __init__(self, path: str, start: float = 0.0, duration: float = 3.0,
                 caption: str = "", kicker: str = "", fps: int = T.FPS):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found on PATH — sudo apt install ffmpeg")

        self.caption, self.kicker = caption, kicker
        self.duration, self.fps = duration, fps
        self._tmp = tempfile.TemporaryDirectory(prefix="autoedits_clip_")
        out = Path(self._tmp.name)

        # ffmpeg honours the rotation tag on phone video by default, so a clip
        # shot in portrait arrives portrait. Cover the frame and crop the
        # overflow, matching how PhotoScene treats a still.
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(path),
               "-vf", (f"scale={T.W}:{T.H}:force_original_aspect_ratio=increase,"
                       f"crop={T.W}:{T.H}"),
               "-r", str(fps), "-q:v", "3", str(out / "%05d.jpg")]
        r = subprocess.run(cmd, capture_output=True)
        self.frames = sorted(out.glob("*.jpg"))
        if not self.frames:
            raise RuntimeError(
                f"No frames extracted from {path} at {start}s\n"
                f"{r.stderr.decode('utf-8', 'replace').strip()[:300]}")

        # A clip shorter than asked for shortens the scene rather than freezing
        # on its last frame, which reads as a stall.
        self.duration = min(duration, len(self.frames) / fps)
        self._scrim = self._make_scrim()
        self._cache: tuple[int, Image.Image] | None = None

    def background(self, img: Image.Image, t: float) -> None:
        i = min(int(t * self.fps), len(self.frames) - 1)
        if self._cache is None or self._cache[0] != i:
            self._cache = (i, Image.open(self.frames[i]).convert("RGB"))
        img.paste(self._cache[1], (0, 0))
        if self.caption or self.kicker:
            img.paste(self._scrim, (0, T.H - self._scrim.height), self._scrim)


@dataclass
class BulletScene(Scene):
    """Title plus up to four staggered points. Good for 'what to check'."""
    title: str
    bullets: list[str]
    duration: float = 4.5

    def render(self, d, t):
        ft, tlines, tlh = fit_rich(d, self.title, T.F_BOLD,
                                   T.SAFE_RIGHT - T.SAFE_LEFT, 260,
                                   start=76, min_size=48, line_ratio=1.12)
        laid = [fit_rich(d, b, T.F_MEDIUM, T.SAFE_RIGHT_LOW - T.SAFE_LEFT - 70,
                         220, start=52, min_size=36, line_ratio=1.26)
                for b in self.bullets[:4]]
        total = len(tlines) * tlh + 74 + sum(len(l) * lh + 46 for _, l, lh in laid)
        y = centred_top(total)

        a, dy = anim(t, 0, rise=26)
        draw_rich(d, tlines, ft, T.SAFE_LEFT, y + dy, tlh, a)
        y += len(tlines) * tlh + 74

        for i, (fb, blines, blh) in enumerate(laid):
            ba, bdy = anim(t, i + 1, rise=34)
            d.rounded_rectangle(
                [T.SAFE_LEFT, y + bdy + 12,
                 T.SAFE_LEFT + 12, y + bdy + 12 + blh * len(blines) - 14],
                radius=6, fill=fade(T.ACCENT, ba))
            draw_rich(d, blines, fb, T.SAFE_LEFT + 46, y + bdy, blh, ba,
                      colour=T.TEXT_DIM)
            y += len(blines) * blh + 46


@dataclass
class VerdictScene(Scene):
    """The take. This is the scene that earns a like or a comment — it has to
    say something a reasonable person could disagree with."""
    text: str
    kicker: str = "The verdict"
    duration: float = 4.0

    def render(self, d, t):
        pad = 56
        box_l, box_r = T.SAFE_LEFT - 8, T.SAFE_RIGHT

        f, lines, lh = fit_rich(d, self.text, T.F_BOLD,
                                box_r - box_l - pad * 2,
                                T.SAFE_BOTTOM - T.SAFE_TOP - 280, start=86,
                                min_size=48, line_ratio=1.15)
        h = len(lines) * lh + pad * 2 + 90
        y = centred_top(h)

        grow = ease_out_expo(clamp(t / 0.45))
        a, _ = anim(t, 0, rise=0)
        d.rounded_rectangle([box_l, y, box_l + (box_r - box_l) * grow, y + h],
                            radius=32, fill=fade(T.SURFACE, a))
        d.rounded_rectangle([box_l, y, box_l + 10, y + h],
                            radius=5, fill=fade(T.ACCENT, a * grow))

        if grow > 0.75:
            d.text((box_l + pad, y + pad - 6), self.kicker.upper(),
                   font=font(T.F_SEMI, 40), fill=fade(T.ACCENT, a, T.SURFACE))
            draw_rich(d, lines, f, box_l + pad, y + pad + 66, lh, 1.0,
                      base=T.SURFACE, stagger_lines=T.STAGGER, t=t - 0.35)


@dataclass
class QuestionScene(Scene):
    """Closing question.

    The subscribe line that used to sit under the question is gone: the writer
    composes its own closing line now, and a hardcoded "Subscribe - UAE car
    answers, weekly" underneath it read as boilerplate stapled to a better
    sentence.

    Worth knowing what that trades away. The line existed because the
    analytics were unambiguous - people watch to the end (95%, 126%, even 304%
    on one) and leave without subscribing, because nobody asked them. The
    written ask now survives only in the video DESCRIPTION, through
    script.describe() and photo_short. If subscribers stay flat, this frame is
    the first place to look."""
    text: str
    duration: float = 3.0

    def render(self, d, t):
        f, lines, lh = fit_rich(d, self.text, T.F_BLACK,
                                T.SAFE_RIGHT - T.SAFE_LEFT, 620,
                                start=96, min_size=52)
        # No trailing CTA line, so the block no longer reserves room for one.
        y = centred_top(90 + len(lines) * lh)

        a, dy = anim(t, 0, rise=30)
        d.text((T.SAFE_LEFT, y + dy), "YOUR TURN", font=font(T.F_SEMI, 44),
               fill=fade(T.ACCENT, a))
        draw_rich(d, lines, f, T.SAFE_LEFT, y + 90, lh, 1.0,
                  stagger_lines=T.STAGGER, t=t - 0.1)


# ============================================================== compositor ==

def _chrome(d: ImageDraw.ImageDraw, progress: float) -> None:
    """Persistent furniture: progress line and wordmark.

    The wordmark is amber rather than the old slate grey. Grey read as an
    artefact of the template; amber reads as a signature, and it is the one
    colour already doing that job everywhere else in the frame. The thin dark
    stroke is not decoration — it is what keeps the type legible when a photo
    scene puts a white car or a bright sky directly behind it.
    """
    if T.SHOW_PROGRESS_BAR:
        d.rectangle([0, 0, T.W, 7], fill=T.SURFACE)
        d.rectangle([0, 0, T.W * clamp(progress), 7], fill=T.ACCENT)
    d.text((T.SAFE_LEFT, T.SAFE_TOP - 96), T.WORDMARK, font=font(T.F_SEMI, 32),
           fill=T.ACCENT, stroke_width=2, stroke_fill=T.BG)


def build_frames(scenes: Sequence[Scene], fps: int = T.FPS):
    """Yield raw RGB bytes for every frame of the video."""
    total = sum(s.duration for s in scenes)
    n = int(round(total * fps))
    img = Image.new("RGB", (T.W, T.H), T.BG)
    d = ImageDraw.Draw(img)

    idx, elapsed = 0, 0.0
    for i in range(n):
        t = i / fps
        while idx < len(scenes) - 1 and t >= elapsed + scenes[idx].duration:
            elapsed += scenes[idx].duration
            idx += 1

        d.rectangle([0, 0, T.W, T.H], fill=T.BG)
        scenes[idx].background(img, t - elapsed)
        _chrome(d, t / total if total else 0)
        scenes[idx].render(d, t - elapsed)
        yield img.tobytes()


def check_audio(path: str) -> float:
    """Fail early and clearly on a missing or unreadable voice track.

    Otherwise ffmpeg exits the moment it can't open the input, and the first
    frame we write lands on a closed pipe — surfacing as BrokenPipeError, which
    says nothing about the actual cause.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"Voice track missing: {path}")
    if p.stat().st_size < 1024:
        raise RuntimeError(f"Voice track is empty ({p.stat().st_size} bytes): {path}")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
        capture_output=True, text=True)
    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(
            f"Voice track is unreadable: {path}\n{probe.stderr.strip()[:300]}")
    return float(probe.stdout.strip())


def render(scenes: Sequence[Scene], audio_path: str | None, out_path: str,
           fps: int = T.FPS, crf: int = 19) -> str:
    """Render scenes to an H.264 MP4, muxing in the voiceover if given."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH — sudo apt install ffmpeg")

    if audio_path:
        check_audio(audio_path)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{T.W}x{T.H}", "-r", str(fps), "-i", "-"]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [out_path]

    # stderr is captured so a failure reports what ffmpeg actually said.
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    broken = False
    try:
        for frame in build_frames(scenes, fps):
            proc.stdin.write(frame)
    except BrokenPipeError:
        broken = True          # ffmpeg quit early; its stderr has the reason
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        code = proc.wait()
        err = (proc.stderr.read().decode("utf-8", "replace").strip()
               if proc.stderr else "")

    if code != 0 or broken:
        raise RuntimeError(
            f"ffmpeg exited {code} while encoding {out_path}\n"
            f"{err or '(no stderr — try running without -loglevel error)'}")
    return out_path


def thumbnail(scenes: Sequence[Scene], out_path: str, at: float = 1.2) -> str:
    """Grab a still for the Shorts poster / any long-form thumbnail."""
    img = Image.new("RGB", (T.W, T.H), T.BG)
    d = ImageDraw.Draw(img)
    scenes[0].background(img, at)
    _chrome(d, 0.0)
    scenes[0].render(d, at)
    img.save(out_path, quality=95)
    return out_path
