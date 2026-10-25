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

# One of the nightly drafts is a motorcycle topic when one is covered. A
# reserved slot rather than a shared queue, because by score alone the car
# topics win every night: there are 1,500 of them and a few dozen bike ones.
BIKE_SLOTS = int(CFG["pipeline"].get("bike_slots_per_night", 1))

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
    is_bike = cars.is_bike_query
    candidates = db.next_topics(n * 10, match=lambda q: not is_bike(q))
    bike_cands = db.next_topics(10, match=is_bike) if BIKE_SLOTS else []
    if not candidates and not bike_cands:
        print("No topics queued. Run: python -m autoedits.topics")
        return []

    # Bikes first, so the reserved slot is filled from the bike queue; the
    # car topics then take what is left. If no bike topic has data the slot
    # goes back to the cars — a covered car video is not a hollow one.
    bikes = [r for r in bike_cands if facts_for(r["query"])][:min(BIKE_SLOTS, n)]
    if BIKE_SLOTS:
        if bikes:
            print(f"Bike slot: {bikes[0]['query']!r}")
        else:
            print(f"Bike slot: none of {len(bike_cands)} queued motorcycle "
                  f"topics have data in bikes.csv or bike_rules.csv; the slot "
                  f"goes to a car topic tonight.")
    n_cars = n - len(bikes)

    # A topic with no rows in cars.csv gives the writer nothing to stand on.
    # It does not fail loudly — it produces a script that gestures at figures
    # it never states ("this figure", "those fees") and invents a verdict to
    # fill the required field. That is what 74 binned drafts looked like.
    #
    # So the quota does NOT get topped up. Fewer drafts beats hollow ones.
    covered = [r for r in candidates if facts_for(r["query"])]
    uncovered = [r["query"] for r in candidates if not facts_for(r["query"])]
    topics = bikes + covered[:n_cars]

    if topics:
        print(f"{len(covered)} of {len(candidates)} queued topics have data in "
              f"cars.csv; building {len(topics)}"
              + (f", {len(bikes)} of them a motorcycle topic." if bikes else "."))
        if len(topics) < n:
            print(f"    ({n - len(topics)} fewer than the nightly target — the "
                  f"rest have no supporting data and were left queued.)")
    else:
        print(f"None of the top {len(candidates)} queued topics have data in "
              f"cars.csv, so nothing was built — a script with no figures is "
              f"not worth the render time.\n"
              f"  Add rows to data/cars.csv for a subject you have queued, or "
              f"queue topics your data covers: python -m autoedits.topics")

    # A count was all this printed, which told you a number and gave you
    # nothing to do with it. The queue holds ~1,500 phrases; knowing that 38
    # of the top 50 have no data does not tell you WHICH, and the ones worth
    # acting on are always at the top. Naming them turns a statistic into a
    # list of rows to add. It is printed on the way out too, because a night
    # that built nothing is exactly when you need it.
    if uncovered:
        print(f"\n  No data for {len(uncovered)}, highest-demand first:")
        for q in uncovered[:8]:
            print(f"    · {q}")
        if len(uncovered) > 8:
            print(f"    … and {len(uncovered) - 8} more")
        print(f"  Why one of them matched nothing:\n"
              f"    python -m autoedits.cars --why {uncovered[0]!r}")

    # This `return` used to be the tail of the `else` above. Inserting the
    # uncovered listing between the `if` and its `else` silently re-bound
    # that `else` to `if uncovered:` — Python accepts it, since either `if`
    # can own an `else`. The run then printed the list of topics it could not
    # build, skipped the sentence explaining what to do about it, and fell
    # through to iterate an empty list. Two nights produced nothing with no
    # usable diagnosis.
    if not topics:
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


def _spec_facts(spec: dict, slug: str) -> str:
    """The facts a saved spec is checked against.

    A spec saved by `script --probe --save` records its query. Older ones
    don't, but their folder name is the slugified query, and a hand-written
    one at least has a title. Every distinct row any of them finds is used,
    so a figure is not called invented just because one phrasing missed it.
    """
    seen, rows = set(), []
    for q in (spec.get("query"), slug.replace("-", " "), spec.get("title")):
        for line in (facts_for(q) if q else "").splitlines():
            if line and line not in seen:
                seen.add(line)
                rows.append(line)
    return "\n".join(rows)


def _passes_checks(spec: dict, slug: str) -> bool:
    """The checkpoints a generated script passes, applied to a saved one.

    --from-spec ran only the sourcing gate, and --rebuild ran nothing, so a
    script edited by hand after it was saved reached a render without the
    narration checks or the description check. There is no repair pass here
    — the script is yours to edit — so a failing line refuses the build and
    says which line and why.
    """
    facts = _spec_facts(spec, slug)
    bad = script._narration_faults(spec, facts)
    if bad:
        print(f"  refused: {len(bad)} line(s) fail the narration checks. "
              f"Edit work/{slug}/spec.json and run it again:")
        for b in bad:
            print(f"    {b[:160]}")
        return False
    dropped = script.clean_description(spec, facts)
    if dropped:
        print(f"  description: dropped {len(dropped)} sentence(s) that failed "
              f"the figure checks")
        for d in dropped:
            print(f"    {d[:150]}")
    return True


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
    script.attach_sources(spec)
    missing = script.unsourced(spec)
    if missing and CFG["pipeline"]["require_sources"]:
        print(f"  refused: numbers with no traceable source in {missing}")
        return None

    if not script.has_evidence(spec):
        print("  refused: no stat or comparison scene — nothing to show")
        return None

    if not _passes_checks(spec, slug):
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
    # The voice track was recorded from this narration, so a line that fails
    # a check now is already IN the audio. Re-rendering would ship it again.
    if not _passes_checks(spec, slug):
        return None
    dur_path = d / "durations.json"
    durations = json.loads(dur_path.read_text()) if dur_path.exists() else None

    scenes = script.to_scenes(spec, durations)
    video_path, poster_path = d / f"{slug}.mp4", d / f"{slug}.jpg"
    R.render(scenes, str(audio), str(video_path))
    R.thumbnail(scenes, str(poster_path), at=2.0)

    db.init()
    # The rebuild overwrote the same .mp4, so the older draft row now points
    # at footage nobody reviewed. from_spec already retired it; this did not,
    # and each rebuild left a duplicate in the review queue.
    db.supersede(str(video_path))
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
