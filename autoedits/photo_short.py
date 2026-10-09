"""
Build vertical Shorts out of photographs and clips you shot yourself.

    python -m autoedits.photo_short data/meets/jan_meet.txt --draft
    python -m autoedits.photo_short --all --draft      # every manifest at once

With --draft the finished Short is added to the review queue, so it turns up in
`streamlit run review_app.py` next to everything else and ships through the
same Approve → Upload path. Nothing is ever published from here.

The manifest is plain text. Header lines set the metadata, then one media file
per line with an optional caption after a pipe:

    # title:       What Turns Up To A Dubai Car Meet
    # description: Shot in January...
    # tags:        dubai, car meet, jdm
    # kicker:      Dubai · January
    # question:    Which one are you taking home?
    # seconds:     2.4
    ~/Downloads/Car_Pictures/20260117_152023.jpg | What turns up to a *Dubai car meet*?
    ~/Downloads/Car_Pictures/20260117_153549.jpg |
    ~/Downloads/Car_Pictures/20250419_180823.mp4 @1.2+3.0 | *Doors up*

A video line takes `@start+duration` in seconds. Everything is yours, so
nothing here can be claimed by Content ID — which is the whole reason this
route exists alongside the data shorts.

Two rules worth keeping. Caption only what you can actually name: a wrong model
on a car channel costs more than a silent frame. And leave most frames
uncaptioned — type on every shot reads as a slideshow, type on a third of them
reads as an edit.

There is no voiceover and no music. Add music in YouTube Studio from the Audio
Library, with attribution set to "not required".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import db, render as R
from .config import ROOT, WORK

MEETS = ROOT / "data" / "meets"
T_WIDTH = R.T.W                # a vertical frame is 1080 wide
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}

DEFAULTS = {"title": "", "description": "", "tags": "",
            "kicker": "", "question": "", "seconds": "2.4"}

# "path.mp4 @1.2+3.0"  ->  start 1.2s, run 3.0s
_CLIP = re.compile(r"^(?P<path>.*?)\s*@\s*(?P<start>[\d.]+)"
                   r"(?:\s*\+\s*(?P<dur>[\d.]+))?$")


def warn_if_soft(p: Path) -> None:
    """Say so at build time when a picture will be upscaled into the frame.

    A photo that reached you through WhatsApp arrives around 960 pixels on its
    short edge — the app re-encodes it on the way. The original on the phone,
    or in Google Photos, is usually four times that. It is the same photograph
    and the same photographer; only the delivery route threw the pixels away.
    Better to hear it here than to notice it at full screen on YouTube.
    """
    if p.suffix.lower() in VIDEO_SUFFIXES:
        return
    try:
        from PIL import Image, ImageOps
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im) or im
            short = min(im.size)
    except Exception:                                 # noqa: BLE001
        return
    if short < 800:
        print(f"  {p.name}: {short}px short edge — too soft for a full frame, "
              f"find the original")
    elif short < T_WIDTH:
        print(f"  {p.name}: {short}px short edge — will be upscaled slightly")


def parse(path: Path) -> tuple[dict, list[dict]]:
    meta = dict(DEFAULTS)
    shots: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            key, _, val = line[1:].partition(":")
            if key.strip().lower() in meta:
                meta[key.strip().lower()] = val.strip()
            continue

        media, _, caption = line.partition("|")
        media, caption = media.strip(), caption.strip()

        start, dur = 0.0, None
        if (m := _CLIP.match(media)):
            media = m.group("path")
            start = float(m.group("start"))
            dur = float(m.group("dur")) if m.group("dur") else None

        p = Path(media).expanduser()
        if not p.exists():
            print(f"  skipped, not found: {p}")
            continue
        warn_if_soft(p)
        shots.append({"path": p, "caption": caption, "start": start,
                      "clip_dur": dur,
                      "is_clip": p.suffix.lower() in VIDEO_SUFFIXES})
    return meta, shots


def scenes_for(meta: dict, shots: list[dict]) -> list[R.Scene]:
    base = float(meta["seconds"])
    scenes: list[R.Scene] = []
    for i, sh in enumerate(shots):
        # A captioned frame needs longer than a silent one; alternating the
        # push direction stops a dozen stills feeling like one long drift.
        seconds = base + (0.2 if sh["caption"] else -0.3)
        kicker = meta["kicker"] if sh["caption"] else ""
        if sh["is_clip"]:
            scenes.append(R.ClipScene(
                str(sh["path"]), start=sh["start"],
                duration=sh["clip_dur"] or (base + 0.6),
                caption=sh["caption"], kicker=kicker))
        else:
            scenes.append(R.PhotoScene(
                str(sh["path"]), caption=sh["caption"], kicker=kicker,
                duration=seconds, zoom_in=(i % 2 == 0)))

    if meta["question"]:
        q = R.QuestionScene(meta["question"])
        q.duration = 3.0
        scenes.append(q)
    return scenes


def build(manifest: Path, draft: bool = False) -> Path | None:
    meta, shots = parse(manifest)
    if not shots:
        print(f"  nothing usable in {manifest.name}")
        return None

    scenes = scenes_for(meta, shots)
    total = sum(s.duration for s in scenes)
    if total > 59:
        print(f"  {total:.0f}s — over a minute stops being a Short. "
              f"Drop a line or two from {manifest.name}.")

    out = WORK / manifest.stem / f"{manifest.stem}.mp4"
    poster = out.with_suffix(".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    R.render(scenes, None, str(out))
    R.thumbnail(scenes, str(poster), at=1.6)

    title = meta["title"] or manifest.stem.replace("_", " ").title()
    tags = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    print(f"  {len(scenes)} scenes, {total:.0f}s → {out.name}")

    if draft:
        db.init()
        # This build just overwrote the .mp4 that any earlier row points at,
        # so those rows now describe footage that no longer exists.
        if (gone := db.supersede(str(out))):
            print(f"  retired {gone} earlier copy of this short from the queue")
        # No sourced figures in a photo short — the record is which of your own
        # files went in, so the review screen can show you what it was cut from.
        record = [{"type": "clip" if sh["is_clip"] else "photo",
                   "source": str(sh["path"]),
                   "label": sh["caption"]}
                  for sh in shots]
        # The manifest description is the prose; the ask is appended here so
        # photo shorts and data shorts close the same way.
        desc = (meta["description"].strip() + "\n\n" + R.T.END_CTA).strip()
        vid = db.add_video(None, title, desc, tags,
                           record, str(out), str(poster))
        print(f"  draft #{vid} queued for review")
    return out



# ------------------------------------------------------- event scaffolding --

LIBRARY = Path("~/Pictures/Car_Pictures").expanduser()
MIN_EDGE = 1080          # a vertical Short is 1080 wide; below this it upscales
MIN_SHARP = 40.0         # variance of the Laplacian; the traffic shots scored 6
MAX_UPSCALE = 2.5        # how far a sharp-but-small frame can be enlarged


def _sharpness(path: Path) -> float:
    """Variance of the Laplacian — how much fine detail survived.

    Not a judgement about composition, only about whether the frame is in
    focus. Two of twelve Abu Dhabi photos scored 6 against a normal 44-200:
    they looked merely "cluttered" on a phone and were unusable at full size.
    That is the check this exists to stop doing by eye.
    """
    try:
        from PIL import Image, ImageOps
        import numpy as np
    except ImportError:
        return -1.0
    try:
        with Image.open(path) as im:
            g = np.asarray((ImageOps.exif_transpose(im) or im)
                           .convert("L").resize((512, 512)), dtype=float)
    except Exception:                                 # noqa: BLE001
        return -1.0
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
           - 4 * g[1:-1, 1:-1])
    return float(lap.var())


def scaffold(day: str, library: Path | None = None) -> Path | None:
    """Write a manifest for everything shot on one day.

    An event is a date. Phone cameras name files 20260117_151757.jpg, so the
    day is already in the filename and the ordering is already chronological —
    which is the order you walked round the event in, and therefore the order
    the short should run in.

    What this does NOT do is write captions. Captions name cars, and a caption
    that names the wrong car is the single most expensive mistake this channel
    can make — a VENOM-badged 991 went out of here labelled as a RUF. The
    scaffold leaves every caption blank on purpose. Filling them in is the part
    that needs someone who was standing there.
    """
    lib = library or LIBRARY
    if not lib.exists():
        print(f"No photo library at {lib}")
        return None

    key = day.replace("-", "")
    media = sorted(p for p in lib.iterdir()
                   if p.is_file() and p.name.startswith(key)
                   and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
                   | VIDEO_SUFFIXES)
    if not media:
        print(f"Nothing in {lib} from {day}")
        return None

    good, fixable, rejected = [], [], []
    for m in media:
        if m.suffix.lower() in VIDEO_SUFFIXES:
            good.append((m, "video"))
            continue
        try:
            from PIL import Image
            with Image.open(m) as im:
                w, h = im.size
        except Exception:                             # noqa: BLE001
            rejected.append((m, "unreadable"))
            continue
        sharp = _sharpness(m)
        small = min(w, h) < MIN_EDGE
        soft = 0 <= sharp < MIN_SHARP

        # Small and soft are different problems and the first version of this
        # treated them the same. A 1134x950 frame off a phone is small but its
        # pixels are fine: crop the obstruction, upscale, and it fills a Short
        # perfectly well. A 4000x3000 frame at sharpness 6 has nothing in it to
        # enlarge. Only the second one is beyond help.
        # What decides whether a small frame survives is not its pixel count
        # but how far it has to stretch to fill 1080x1920. A 960x1280 phone
        # photo needs 1.5x and holds up; a 420x420 thumbnail needs 4.6x and
        # turns to porridge however sharp the original was.
        up = max(T_WIDTH / w, (T_WIDTH * 16 / 9) / h)
        if soft:
            rejected.append((m, f"sharpness {sharp:.0f} — soft, nothing to recover"))
        elif up > MAX_UPSCALE:
            rejected.append((m, f"{w}x{h} — needs {up:.1f}x, too far to stretch"))
        elif small:
            fixable.append((m, f"{w}x{h}, sharp ({sharp:.0f}), needs {up:.1f}x"))
        else:
            good.append((m, f"{w}x{h}, sharpness {sharp:.0f}"))

    out = MEETS / f"{key}.txt"
    lines = [
        f"# title:       ",
        f"# description: ",
        f"# tags:        ",
        f"# kicker:      ",
        f"# question:    ",
        f"# seconds:     2.4",
        "# " + "-" * 72,
        f"# Scaffolded from {len(media)} file(s) shot on {day}.",
        "# Captions are blank ON PURPOSE. Name only the cars you can actually",
        "# name — a wrong model costs more than a silent frame. Delete any line",
        "# you do not want; six to eight frames is a Short.",
        "# " + "-" * 72,
    ]
    for m, why in good:
        lines.append(f"~/Pictures/Car_Pictures/{m.name} |        # {why}")
    if fixable:
        lines.append("#")
        lines.append(f"# Worth rescuing ({len(fixable)}) — small but sharp. Crop out")
        lines.append("# whatever is blocking the shot, upscale past 1080x1920, then")
        lines.append("# move the line up. These are usually the phone-to-WhatsApp route.")
        for m, why in fixable:
            lines.append(f"# ~/Pictures/Car_Pictures/{m.name} |   # {why}")
    if rejected:
        lines.append("#")
        lines.append(f"# Beyond help ({len(rejected)}):")
        for m, why in rejected:
            lines.append(f"# ~/Pictures/Car_Pictures/{m.name} |   # {why}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(good)} usable, {len(fixable)} worth rescuing, "
          f"{len(rejected)} beyond help -> {out}")
    print("Fill in the title and any captions, then:")
    print(f"  python -m autoedits.photo_short {out} --draft")
    return out



def rescue(*paths: str) -> list[Path]:
    """Enlarge small-but-sharp frames so the renderer never has to.

    A plain upscale is safe to automate; a crop is not. This does the first
    and leaves the second alone — if something is blocking the shot, crop it
    yourself first and run this after.

    Writes <name>_hi.jpg beside the original. The original is never touched.
    """
    from PIL import Image, ImageOps, ImageFilter

    made = []
    for raw in paths:
        src = Path(raw).expanduser()
        if not src.exists():
            print(f"  missing: {src}")
            continue
        im = ImageOps.exif_transpose(Image.open(src)) or Image.open(src)
        w, h = im.size
        up = max(T_WIDTH / w, (T_WIDTH * 16 / 9) / h)
        if up <= 1.0:
            print(f"  {src.name}: already {w}x{h}, nothing to do")
            continue
        if up > MAX_UPSCALE:
            print(f"  {src.name}: needs {up:.1f}x — past the {MAX_UPSCALE}x "
                  f"limit, skipped")
            continue
        out_size = (round(w * up), round(h * up))
        big = im.convert("RGB").resize(out_size, Image.LANCZOS)
        # Enlarging softens edges; one modest pass puts the bite back without
        # the halo you get from sharpening hard.
        big = big.filter(ImageFilter.UnsharpMask(radius=2.2, percent=115,
                                                 threshold=3))
        out = src.with_name(src.stem + "_hi.jpg")
        big.save(out, quality=95, subsampling=0)
        print(f"  {src.name}: {w}x{h} -> {out_size[0]}x{out_size[1]} "
              f"({up:.1f}x) -> {out.name}")
        made.append(out)
    return made


def build_all(draft: bool = False) -> list[Path]:
    manifests = sorted(MEETS.glob("*.txt"))
    if not manifests:
        print(f"No manifests in {MEETS}")
        return []
    made = []
    for m in manifests:
        print(f"\n{m.name}")
        try:
            if (out := build(m, draft=draft)):
                made.append(out)
        except Exception as exc:                      # noqa: BLE001
            print(f"  failed: {type(exc).__name__}: {str(exc)[:200]}")
    if made:
        print(f"\n{len(made)} short(s) built."
              + (" Review: streamlit run review_app.py" if draft else ""))
    return made


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    draft = "--draft" in sys.argv

    if "--rescue" in sys.argv:
        targets = [a for a in args]
        if not targets:
            print("usage: python -m autoedits.photo_short --rescue <file> ...")
            raise SystemExit(2)
        raise SystemExit(0 if rescue(*targets) else 1)

    if "--scaffold" in sys.argv:
        i = sys.argv.index("--scaffold")
        if i + 1 >= len(sys.argv):
            print("usage: python -m autoedits.photo_short --scaffold 20260117")
            raise SystemExit(2)
        raise SystemExit(0 if scaffold(sys.argv[i + 1]) else 1)

    if "--all" in sys.argv:
        raise SystemExit(0 if build_all(draft=draft) else 1)
    if not args:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(0 if build(Path(args[0]).expanduser(), draft=draft) else 1)
