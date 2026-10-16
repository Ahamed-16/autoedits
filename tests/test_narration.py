"""Regression tests for the narration checks and the prompts that feed them.

Two bugs here cost a whole evening of re-rolls, and both were cases of the
project telling the model to do the thing it then failed the model for:

  * SYSTEM said "write NUMBERS AS DIGITS" on one line and showed a worked
    example spelling a price out in words on another. A model follows the
    example.
  * The repair prompt's only GOOD example did the same.

A rule and an example that disagree are invisible in review and obvious in
output, so they get a test.

    python tests/test_narration.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits import script as S          # noqa: E402


def _positive_lines(text: str) -> list[str]:
    """Lines that show the model what TO do.

    A line introducing a counter-example is exempt: the explanation of why
    spelled-out numbers break is worth keeping, and it has to quote one.
    """
    out = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("not ", "never", "bad:", "instead of",
                                  "produced", "dropped from")):
            continue
        out.append(line)
    return out


def test_system_prompt_never_demonstrates_a_spelled_price():
    bad = [l.strip() for l in _positive_lines(S.SYSTEM)
           if S._SPELLED_BIG.search(l)]
    assert not bad, ("SYSTEM tells the writer to use digits but shows it "
                     "spelling a price out:\n  " + "\n  ".join(bad))


def test_repair_prompt_never_demonstrates_a_spelled_price():
    spec = {"scenes": [{"type": "stat", "value": 139900, "prefix": "AED",
                        "narration": "The FJ starts at 139,900 dirhams."}]}
    seen = {}

    def capture(prompt, schema, name, want=None):
        seen["prompt"] = prompt
        return json.dumps({"narrations": ["The FJ starts at 139,900 dirhams."]})

    real, S._groq_json = S._groq_json, capture
    try:
        S.rewrite_narration(spec, [], "AED 139,900 to 154,900")
    finally:
        S._groq_json = real

    bad = [l.strip() for l in _positive_lines(seen["prompt"])
           if S._SPELLED_BIG.search(l)]
    assert not bad, ("the repair prompt asks for digits but shows it "
                     "spelling a price out:\n  " + "\n  ".join(bad))


def test_complaints_map_through_unicode_hyphens():
    """The bug that made one line unfixable on every re-roll.

    The checks report the NORMALISED narration; the mapping compared it
    against the raw one. A non-breaking hyphen 44 characters in was enough to
    miss, and a complaint that misses gets its line labelled "return this
    unchanged" — so the model obediently kept the fault, identically, every
    single run.
    """
    raw = ("The Land Cruiser FJ starts at one hundred thirty‑nine "
           "thousand nine hundred dirhams.")
    spec = {"scenes": [{"type": "stat", "narration": raw}]}
    faults = S.spells_out_a_price(spec)
    assert faults, "the check itself stopped firing"
    mapped, unmapped = S._complaints_by_line(spec, faults)
    assert mapped and not unmapped, (
        f"complaint did not map back to its scene: {mapped=} {unmapped=}")


def test_unmapped_complaint_does_not_label_lines_ok():
    """An OK label we are not sure about must not be emitted at all."""
    spec = {"scenes": [{"type": "stat", "narration": "A line."},
                       {"type": "stat", "narration": "Another line."}]}
    seen = {}

    def capture(prompt, schema, name, want=None):
        seen["prompt"] = prompt
        return json.dumps({"narrations": ["A line.", "Another line."]})

    real, S._groq_json = S._groq_json, capture
    try:
        S.rewrite_narration(spec, ["a complaint about a line that is gone"], "")
    finally:
        S._groq_json = real
    assert "OK: return this line unchanged" not in seen["prompt"], (
        "an unplaceable complaint still let the prompt tell the model to "
        "keep lines unchanged")


# Every compare and bullets scene in the project's saved specs was hollow —
# three of three each, across published videos. The screen carried the
# figures and the voiceover carried nothing, and no check looked at it.
HOLLOW = {"scenes": [
    {"type": "hook", "narration": "Which Land Cruiser fits your budget?"},
    {"type": "compare",
     "rows": [{"name": "Land Cruiser FJ EXR", "value": 139900},
              {"name": "Land Cruiser 70", "value": 177900},
              {"name": "Land Cruiser Prado", "value": 199900}],
     "narration": "The FJ is the cheapest Land Cruiser variant at launch."},
    {"type": "bullets",
     "narration": "Toyota's configurator shows monthly payments for each trim."},
]}

SOLID = {"scenes": [
    {"type": "hook", "narration": "Which Land Cruiser fits your budget?"},
    {"type": "compare",
     "rows": [{"name": "Land Cruiser FJ EXR", "value": 139900},
              {"name": "Land Cruiser 70", "value": 177900},
              {"name": "Land Cruiser Prado", "value": 199900}],
     "narration": "The FJ starts at 139,900 dirhams against the 70's 177,900."},
    {"type": "bullets",
     "narration": "Registration and the 177,900 dirham step up to the 70 are "
                  "what the sticker hides."},
]}

FACTS = "Toyota Land Cruiser FJ | AED 139,900 to 154,900\nLand Cruiser 70 | from AED 177,900"


def test_hollow_compare_and_bullets_are_caught():
    assert S.compare_says_nothing(HOLLOW), "a compare scene naming no figure passed"
    assert S.bullets_say_nothing(HOLLOW, FACTS), "a bullets scene naming no amount passed"


def test_solid_compare_and_bullets_pass():
    assert not S.compare_says_nothing(SOLID), S.compare_says_nothing(SOLID)
    assert not S.bullets_say_nothing(SOLID, FACTS), S.bullets_say_nothing(SOLID, FACTS)


def test_a_gap_counts_as_a_figure():
    """The false positive this check shipped with.

    It demanded the row values specifically and so rejected a line stating
    two exact differences between the three prices on screen — which is the
    comparison expressed better than listing the prices, and the only
    arithmetic a viewer could check against the bars.
    """
    gaps = json.loads(json.dumps(SOLID))
    gaps["scenes"][1]["narration"] = ("The FJ starts 38,000 dirhams cheaper "
                                      "than the 70 and 60,000 cheaper than "
                                      "the Prado.")
    assert not S.compare_says_nothing(gaps), S.compare_says_nothing(gaps)


def test_one_gap_alone_is_not_a_comparison():
    one = json.loads(json.dumps(SOLID))
    one["scenes"][1]["narration"] = "The FJ undercuts the 70 by 38,000 dirhams."
    assert S.compare_says_nothing(one), "one gap is not two figures"


def test_a_compare_scene_needs_two_figures_not_one():
    one = json.loads(json.dumps(SOLID))
    one["scenes"][1]["narration"] = "The FJ starts at 139,900 dirhams."
    assert S.compare_says_nothing(one), (
        "one figure is a stat, not a comparison — this should fail")


def test_system_states_the_rules_the_checks_enforce():
    """A check with no matching rule just causes re-rolls.

    Today proved the converse too: SYSTEM asked for "SPECIFICS with numbers"
    in the bullets scene, nothing verified it, and every bullets scene ever
    written ignored it. Rule and check travel together.
    """
    for phrase in ("compare scene's narration MUST carry at least TWO real",
                   "or two exact GAPS between them",
                   "bullets scene's narration MUST name at least one amount"):
        assert phrase in S.SYSTEM, f"SYSTEM does not state: {phrase!r}"


# Draft #106 shipped 20.2s of video over 26.0s of narration and ended
# mid-sentence, because to_scenes() clamped a 10.2-second compare line into a
# 5-second scene and ffmpeg's -shortest cut the rest. Nothing warned.
#
# This fixture used that draft's own line, which the first version of the
# length check rejected. It should not have: the line measured 10.17s against
# a 10.35s ceiling, so it fit — by 0.18s. The check was over-strict because
# the estimate ignored the trailing pad and miscounted acronyms, and once
# both were fixed it correctly accepted it. So the fixture needs a line that
# is genuinely too long rather than one the old model merely feared.
TRUNCATING = {"scenes": [
    {"type": "hook", "narration": "Which Land Cruiser fits your budget?"},
    {"type": "compare",
     "rows": [{"name": "FJ", "value": 139900}, {"name": "70", "value": 177900}],
     "narration": "The FJ starts at 139,900 dirhams, the 70 at 177,900, the "
                  "Prado at 199,900 and the GR Sport at 249,900."},
]}


def test_an_overlong_line_is_caught_before_the_voice_runs():
    faults = S.too_long_to_speak(TRUNCATING)
    assert faults, "a 14-second line in a 9-second scene passed"
    assert "seconds to speak" in faults[0]


def test_a_line_that_only_just_fits_is_accepted():
    """The 0.18s case. Rejecting it costs a re-roll for nothing."""
    ok = json.loads(json.dumps(TRUNCATING))
    ok["scenes"][1]["narration"] = ("Land Cruiser FJ starts at 139,900 "
                                    "dirhams, while Land Cruiser 70 begins "
                                    "at 177,900 dirhams.")
    assert not S.too_long_to_speak(ok), S.too_long_to_speak(ok)


def test_a_line_that_fits_is_not_flagged():
    ok = json.loads(json.dumps(TRUNCATING))
    ok["scenes"][1]["narration"] = ("The FJ undercuts the 70 by 38,000 and "
                                    "the Prado by 60,000.")
    assert not S.too_long_to_speak(ok), S.too_long_to_speak(ok)


def test_truncation_is_refused_not_silently_cut():
    """The backstop for when the length estimate is wrong anyway."""
    class FakeScene:
        def __init__(self, d): self.duration = d
    scenes = [FakeScene(3.17), FakeScene(5.0)]       # 8.17s of video
    durations = [3.17, 10.17]                         # 13.34s of audio
    lost = S.truncation_seconds(scenes, durations)
    assert round(lost, 2) == 5.17, lost
    # and nothing is lost when the scenes hold the audio
    assert S.truncation_seconds([FakeScene(3.17), FakeScene(10.17)],
                                durations) == 0.0


# Chatterbox said "sixty-two thousand nine hundred" for "162,900" in a
# rendered draft — the leading hundred-thousand gone, in the one figure the
# video existed to state. Writing prices as digits was the fix for spelled-out
# numbers being truncated; it turns out both forms fail, so the engine is no
# longer given the choice.
def test_no_digit_ever_reaches_the_voice_engine():
    from autoedits.voice import speakable
    import re
    lines = ["The GR 86 is the cheapest at 162,900 dirhams.",
             "The Hilux starts at 120,900 dirhams.",
             "The B8 makes 603 horsepower and covers 825 kilometres combined.",
             "A 12.3 inch display, 4x4, 0 to 100 in 4.8 seconds.",
             "The diesel costs 6,000 over the entry petrol."]
    for line in lines:
        out = speakable(line)
        assert not re.search(r"\d", out), f"a digit survived into {out!r}"


def test_the_leading_group_of_a_six_figure_price_survives():
    from autoedits.voice import speakable
    out = speakable("162,900 dirhams").lower()
    assert "one hundred sixty-two thousand nine hundred" in out, out
    # the exact failure seen in the draft
    assert not out.startswith("sixty-two"), "the hundred-thousand was dropped again"


def test_a_model_name_does_not_fuse_with_its_number():
    from autoedits.voice import speakable
    assert speakable("the B8 and the B5") == "the B eight and the B five"
    assert "beight" not in speakable("B8").lower()


def test_a_possessive_stays_attached():
    from autoedits.voice import speakable
    assert speakable("against the B5's 570") == \
        "against the B five's five hundred seventy"
    assert speakable("the 70's price") == "the seventy's price"


def test_decimals_and_dimensions_read_naturally():
    from autoedits.voice import speakable
    assert speakable("4.8 seconds") == "four point eight seconds"
    assert speakable("4x4") == "four by four"
    assert speakable("12.3 inch") == "twelve point three inch"


def test_digits_are_counted_as_spoken_not_written():
    from autoedits.voice import syllables, spoken_syllables
    t = "The entry-level Land Cruiser FJ costs 139,900 dirhams."
    assert spoken_syllables(t) > syllables(t) * 1.5, (
        "a six-figure price must cost far more syllables spoken than written "
        f"— got {syllables(t)} written, {spoken_syllables(t)} spoken")


def test_the_clamp_never_sits_below_the_check():
    """The clamp may exceed the check's ceiling; it must never fall short.

    too_long_to_speak() permits a line up to budget x tolerance because the
    estimate is noisy. If to_scenes() then clamped BELOW that, a line the
    check accepted would have its audio cut by the thing meant to honour it.
    """
    for kind in S.SCENE_BUDGET:
        spec = {"scenes": [{"type": "verdict", "text": "t", "narration": "n"}]}
        at_limit = S.hard_budget_for("verdict")
        scenes = S.to_scenes(spec, [at_limit])
        assert scenes and scenes[0].duration >= at_limit - 1e-9
        assert S.hard_budget_for(kind) + S.TRUNCATION_SLACK >= S.hard_budget_for(kind)


def test_an_underpredicted_line_is_not_cut():
    """The failure that refused the Denza render after the voice had run.

    The estimate's spread is irreducible - the same text runs 2.4 to 5.5
    spoken syllables per second - so a line the check accepted can still come
    back seconds longer. Clamping exactly at the check's ceiling cut it.
    Holding a visual too long is cheap; losing the end of a sentence is not.
    """
    kind = "hook"
    ceiling = S.hard_budget_for(kind)
    worst = ceiling + 2.56        # worst under-prediction seen in 31 clips
    spec = {"scenes": [{"type": kind, "text": "t", "narration": "n"}]}
    scenes = S.to_scenes(spec, [worst])
    assert S.truncation_seconds(scenes, [worst]) == 0.0, (
        f"a {worst:.2f}s clip in a {kind} scene lost "
        f"{S.truncation_seconds(scenes, [worst]):.2f}s")


def test_the_trailing_pad_is_counted():
    """narrate() pads every clip with TAIL and to_scenes consumes the padded
    length, so an estimate that ignores it is short on every scene."""
    from autoedits.voice import TAIL
    assert S.speaking_seconds("") >= TAIL - 1e-9
    assert S.speaking_seconds("one two three") > TAIL


def test_acronyms_are_counted_letter_by_letter():
    """"UAE" has one vowel group and three spoken syllables."""
    from autoedits.voice import spoken_syllables, syllables
    assert spoken_syllables("UAE") >= 3, spoken_syllables("UAE")
    assert spoken_syllables("GLX") >= 3
    assert spoken_syllables("UAE") > syllables("UAE")
    # and a normal word is untouched
    assert spoken_syllables("hybrids") == syllables("hybrids")


def test_a_line_at_the_check_limit_renders_without_truncation():
    kind, text = "stat", "The GR 86 is the cheapest at 162,900 dirhams."
    assert not S.too_long_to_speak(
        {"scenes": [{"type": kind, "narration": text}]}), "fixture should pass"
    spec = {"scenes": [{"type": kind, "label": "x", "value": 1,
                        "narration": text}]}
    need = S.speaking_seconds(text)
    scenes = S.to_scenes(spec, [need])
    assert S.truncation_seconds(scenes, [need]) == 0.0, (
        f"a line the check accepts ({need:.2f}s) is clamped to "
        f"{scenes[0].duration:.2f}s and would be cut")


def test_every_scene_type_has_a_budget():
    for kind in ("hook", "stat", "compare", "bullets", "verdict", "question"):
        assert kind in S.SCENE_BUDGET, f"{kind} has no scene budget"
    # A compare scene must be able to hold two spoken figures, or
    # compare_says_nothing() and too_long_to_speak() contradict each other
    # and no script can satisfy both.
    two_figures = "The FJ starts at 139,900 against the 70's 177,900."
    assert S.speaking_seconds(two_figures) <= (
        S.SCENE_BUDGET["compare"] * S.SPEAK_TOLERANCE), (
        "the compare budget cannot hold the two figures compare scenes are "
        "required to state")


def test_repair_reservation_is_small():
    """The repair returns six sentences, not a script."""
    assert S._fit_completion("x" * 4000, want=900) == 900
    # And it still shrinks rather than 413 when the prompt is enormous.
    huge = S._fit_completion("x" * (S.GROQ_TPM * 4), want=900)
    assert huge < 900, f"a huge prompt should shrink the reservation, got {huge}"


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as exc:
                bad += 1
                print(f"FAIL  {name}\n      {exc}")
    raise SystemExit(bad)
