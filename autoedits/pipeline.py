"""
The nightly run: topic -> script -> voice -> render -> draft in the queue.

Nothing is ever published from here. Every run ends with drafts waiting for
you in the review app, which is the whole design: production is automated,
judgement is not.
"""

from __future__ import annotations

import json
import re
import traceback

from . import cars, db, render as R, script, voice
from .config import CFG, DRAFTS_PER_NIGHT, WORK

# Pulls matching rows from your curated data, excluding anything flagged
# CONFLICT or gone stale. See autoedits/cars.py.
facts_for = cars.facts_for


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def make_one(topic_row) -> int | None:
    """Produce a single draft. Returns the video id, or None if it was skipped."""
    query = topic_row["query"]
    slug = slugify(query)
    print(f"  → {query}")

    spec = script.generate(query, facts=facts_for(query))

    # Rescue scenes whose figures trace back to cars.csv but where the model
    # forgot to cite them. Only genuinely untraceable numbers block a build.
    rescued = script.attach_sources(spec)
    if rescued:
        print(f"    auto-cited {rescued} scene(s) from cars.csv")

    missing = script.unsourced(spec)
    if missing and CFG["pipeline"]["require_sources"]:
        print(f"    skipped: numbers with no traceable source in {missing}")
        db.mark_topic_used(topic_row["id"])
        return None

    # The writer sometimes returns only hook/verdict/question — a video that
    # asserts something and shows nothing. Leave the topic unused so it can be
    # retried, rather than burning it on an empty script.
    if not script.has_evidence(spec):
        print("    skipped: no stat or comparison scene — nothing to show")
        return None

    out_dir = WORK / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save the script before the expensive part. Voice takes ~15 minutes on a
    # CPU-only box; if rendering then fails, `--rebuild <slug>` reuses both.
    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2))

    audio, durations = voice.narrate(script.narrations(spec), slug)
    (out_dir / "durations.json").write_text(json.dumps(durations))
    scenes = script.to_scenes(spec, durations)

    # -shortest cuts the voice to the length of the video, so a scene budget
    # the narration overran means the end of the script is simply gone. The
    # checks in script.py are meant to prevent this before the voice is even
    # generated; this is the backstop for when the length estimate is wrong,
    # and it refuses rather than shipping a video that stops mid-sentence.
    lost = script.truncation_seconds(scenes, durations)
    if lost > 0.25:
        raise RuntimeError(
            f"the narration is {sum(durations):.1f}s but the scenes only hold "
            f"{sum(sc.duration for sc in scenes):.1f}s, so {lost:.1f}s of "
            f"voiceover would be cut and the video would end mid-sentence.\n"
            f"  Re-roll the script — the length checks should catch this "
            f"before the voice is generated — or raise the budget for the "
            f"long scene in script.SCENE_BUDGET.")

    video_path = out_dir / f"{slug}.mp4"
    poster_path = out_dir / f"{slug}.jpg"
    R.render(scenes, str(audio), str(video_path))
    R.thumbnail(scenes, str(poster_path), at=2.0)

    vid = db.add_video(topic_row["id"], spec["title"], script.describe(spec),
                       spec.get("tags", []), spec["scenes"],
                       str(video_path), str(poster_path))
    db.mark_topic_used(topic_row["id"])
    print(f"    draft #{vid}  {video_path.name}  "
          f"{sum(s.duration for s in scenes):.0f}s")
    return vid


def run(n: int | None = None) -> list[int]:
    db.init()
    n = n or DRAFTS_PER_NIGHT

    # Prefer topics your data can actually support. A script whose figures
    # can't be cited is discarded, and on a CPU-only box that discard costs
    # six minutes of writing — so it's worth spending a millisecond up front
    # checking whether cars.csv has anything to say about the subject.
    candidates = db.next_topics(n * 10)
    if not candidates:
        print("No topics queued. Run: python -m autoedits.topics")
        return []

    # A topic with no rows in cars.csv gives the writer nothing to stand on.
    # It does not fail loudly — it produces a script that gestures at figures
    # it never states ("this figure", "those fees") and invents a verdict to
    # fill the required field. That is what 74 binned drafts looked like.
    #
    # So the quota does NOT get topped up. Fewer drafts beats hollow ones.
    covered = [r for r in candidates if facts_for(r["query"])]
    uncovered = [r["query"] for r in candidates if not facts_for(r["query"])]
    topics = covered[:n]

    if topics:
        print(f"{len(covered)} of {len(candidates)} queued topics have data in "
              f"cars.csv; building {len(topics)}.")
        if len(topics) < n:
            print(f"    ({n - len(topics)} fewer than the nightly target — the "
                  f"rest have no supporting data and were left queued.)")
    # A count was all this printed, which told you a number and gave you
    # nothing to do with it. The queue holds 1,491 phrases; knowing that 38 of
    # the top 50 have no data does not tell you WHICH, and the ones worth
    # acting on are always at the top. Naming them turns a statistic into a
    # list of rows to add.
    if uncovered:
        print(f"\n  No data for {len(uncovered)}, highest-demand first:")
        for q in uncovered[:8]:
            print(f"    · {q}")
        if len(uncovered) > 8:
            print(f"    … and {len(uncovered) - 8} more")
        print(f"  Why one of them matched nothing:\n"
              f"    python -m autoedits.cars --why {uncovered[0]!r}")
    else:
        print(f"None of the top {len(candidates)} queued topics have data in "
              f"cars.csv, so nothing was built — a script with no figures is "
              f"not worth the render time.\n"
              f"  Add rows to data/cars.csv for a subject you have queued, or "
              f"queue topics your data covers: python -m autoedits.topics")
        return []

    made = []
    for row in topics:
        try:
            vid = make_one(row)
            if vid:
                made.append(vid)
        except RuntimeError as exc:
            # Our own errors already say what to do — a 60-line traceback
            # buries that.
            print(f"    failed: {exc}")
        except Exception as exc:                      # noqa: BLE001
            print(f"    failed on '{row['query']}': "
                  f"{type(exc).__name__}: {str(exc)[:200]}")
            if CFG["pipeline"].get("debug"):
                traceback.print_exc()
    print(f"\n{len(made)} draft(s) ready. Review: streamlit run review_app.py")
    return made


def from_spec(slug: str, engine: str | None = None) -> int | None:
    """Build a draft from a spec.json you wrote by hand.

    make_one() runs the topic through the local writer. That is right for the
    nightly queue and wrong whenever the angle is the whole point — a 7B model
    asked about a fines table writes "here are the fines", which is the exact
    shape of video this channel's own retention data says dies. This path skips
    the model and keeps everything after it: voice, render, sourcing check,
    draft in the review queue. The script is yours; the machinery is shared.

        mkdir -p work/my-slug && $EDITOR work/my-slug/spec.json
        python -m autoedits.pipeline --from-spec my-slug
    """
    d = WORK / slug
    spec_path = d / "spec.json"
    if not spec_path.exists():
        print(f"No script at {spec_path}")
        return None

    spec = json.loads(spec_path.read_text())

    # A hand-written script gets the same sourcing gate as a generated one.
    # Writing it yourself is not evidence.
    missing = script.unsourced(spec)
    if missing and CFG["pipeline"]["require_sources"]:
        print(f"  refused: numbers with no traceable source in {missing}")
        return None

    if not script.has_evidence(spec):
        print("  refused: no stat or comparison scene — nothing to show")
        return None

    print(f"  → {spec['title']}")
    audio, durations = voice.narrate(script.narrations(spec), slug, engine)
    (d / "durations.json").write_text(json.dumps(durations))
    scenes = script.to_scenes(spec, durations)

    # -shortest cuts the voice to the length of the video, so a scene budget
    # the narration overran means the end of the script is simply gone. The
    # checks in script.py are meant to prevent this before the voice is even
    # generated; this is the backstop for when the length estimate is wrong,
    # and it refuses rather than shipping a video that stops mid-sentence.
    lost = script.truncation_seconds(scenes, durations)
    if lost > 0.25:
        raise RuntimeError(
            f"the narration is {sum(durations):.1f}s but the scenes only hold "
            f"{sum(sc.duration for sc in scenes):.1f}s, so {lost:.1f}s of "
            f"voiceover would be cut and the video would end mid-sentence.\n"
            f"  Re-roll the script — the length checks should catch this "
            f"before the voice is generated — or raise the budget for the "
            f"long scene in script.SCENE_BUDGET.")

    video_path, poster_path = d / f"{slug}.mp4", d / f"{slug}.jpg"
    R.render(scenes, str(audio), str(video_path))
    R.thumbnail(scenes, str(poster_path), at=2.0)

    db.init()
    db.supersede(str(video_path))
    vid = db.add_video(None, spec["title"], script.describe(spec),
                       spec.get("tags", []), spec["scenes"],
                       str(video_path), str(poster_path))
    print(f"draft #{vid} → {video_path}")
    return vid


def rebuild(slug: str) -> int | None:
    """Re-render a draft from saved script + existing voice track.

    For when the render fails after the voice is already generated — which
    costs a quarter of an hour you should not have to spend twice.
    """
    d = WORK / slug
    spec_path, audio = d / "spec.json", d / "voice.mp3"
    if not spec_path.exists():
        print(f"No saved script at {spec_path}")
        return None
    if not audio.exists():
        print(f"No voice track at {audio}")
        return None

    spec = json.loads(spec_path.read_text())
    dur_path = d / "durations.json"
    durations = json.loads(dur_path.read_text()) if dur_path.exists() else None

    scenes = script.to_scenes(spec, durations)
    video_path, poster_path = d / f"{slug}.mp4", d / f"{slug}.jpg"
    R.render(scenes, str(audio), str(video_path))
    R.thumbnail(scenes, str(poster_path), at=2.0)

    db.init()
    vid = db.add_video(None, spec["title"], script.describe(spec),
                       spec.get("tags", []), spec["scenes"],
                       str(video_path), str(poster_path))
    print(f"rebuilt draft #{vid} → {video_path}")
    return vid


if __name__ == "__main__":
    import sys

    if "--from-spec" in sys.argv:
        i = sys.argv.index("--from-spec")
        if i + 1 >= len(sys.argv):
            print("usage: python -m autoedits.pipeline --from-spec <slug>")
            raise SystemExit(2)
        eng = None
        if "--voice" in sys.argv:
            j = sys.argv.index("--voice")
            eng = sys.argv[j + 1] if j + 1 < len(sys.argv) else None
        raise SystemExit(0 if from_spec(sys.argv[i + 1], eng) else 1)

    if "--rebuild" in sys.argv:
        i = sys.argv.index("--rebuild")
        if i + 1 >= len(sys.argv):
            print("usage: python -m autoedits.pipeline --rebuild <slug>")
            print("slugs available:")
            for p in sorted(WORK.glob("*/spec.json")):
                print(f"  {p.parent.name}")
            raise SystemExit(1)
        raise SystemExit(0 if rebuild(sys.argv[i + 1]) else 1)

    run()
