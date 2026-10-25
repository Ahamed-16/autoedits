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

    def capture(prompt, schema, name, want=None, system=None):
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

    def capture(prompt, schema, name, want=None, system=None):
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


def test_a_persistently_short_clip_is_refused_not_shipped():
    """A clip far under length has WORDS MISSING and sounds fluent anyway.

    This used to print a warning and hand the clip back, and nothing
    downstream could notice half a price had gone missing.
    """
    from autoedits import voice as V
    calls = {"n": 0}

    def always_short(text, out_path):
        calls["n"] += 1

    real_dur, V.duration = V.duration, lambda p: 0.1
    try:
        raised = None
        try:
            V._speak_checked(always_short, "a line with many spoken words here",
                             __import__("pathlib").Path("/tmp/x.mp3"))
        except RuntimeError as exc:
            raised = exc
        assert raised is not None, "a short clip was returned instead of refused"
        assert "missing part of the sentence" in str(raised), str(raised)
        assert calls["n"] == V.RETRIES + 1, (
            f"gave up after {calls['n']} attempts, expected {V.RETRIES + 1}")
    finally:
        V.duration = real_dur


def test_a_clip_of_the_right_length_is_accepted():
    from autoedits import voice as V
    real_dur, V.duration = V.duration, lambda p: 99.0
    try:
        out = V._speak_checked(lambda t, p: None, "some words",
                               __import__("pathlib").Path("/tmp/x.mp3"))
        assert out is not None
    finally:
        V.duration = real_dur


# Two drafts on one night named two different "cheapest electric cars",
# 74,900 and 109,900, because they were handed two different sets of rows.
# The second was false by this project's own data.
def test_a_false_cheapest_claim_is_caught():
    spec = {"title": "Cheapest electric car in Dubai 2026", "scenes": [
        {"type": "stat", "label": "Base price of cheapest electric SUV",
         "value": 109900,
         "narration": "The Chevrolet Captiva EV starts at 109,900 dirhams."}]}
    faults = S.false_superlative(spec)
    assert faults, "a 109,900 'cheapest EV' passed with cheaper EVs on file"
    assert "cheapest electric car" in faults[0], faults[0]


def test_a_true_cheapest_claim_passes():
    from autoedits.cars import load, usable
    ev = min((r for r in load() if usable(r) and r["price_from_aed"]
              and "electric" in r["powertrain"].lower()),
             key=lambda r: int(r["price_from_aed"]))
    spec = {"title": "Cheapest electric car in Dubai 2026", "scenes": [
        {"type": "stat", "label": "Cheapest EV", "value": int(ev["price_from_aed"]),
         "narration": f"The {ev['model']} starts at {ev['price_from_aed']} dirhams."}]}
    assert not S.false_superlative(spec), S.false_superlative(spec)


def test_a_cheapest_claim_inside_a_named_brand_is_left_alone():
    """'Toyota GR prices - which one is cheapest' is about Toyota's range,
    which retrieval fetches in full. It must not be judged against every car."""
    spec = {"title": "Toyota GR prices in UAE - which one is cheapest", "scenes": [
        {"type": "stat", "label": "Cheapest GR", "value": 162900,
         "narration": "The GR 86 is the cheapest at 162,900 dirhams."}]}
    assert not S.false_superlative(spec), S.false_superlative(spec)


def test_a_withheld_row_cannot_be_the_cheapest():
    """The Qin Plus EV is marked CONFLICT. usable() must keep it out of
    retrieval, and therefore out of the superlative check's pool."""
    from autoedits.cars import load, usable
    rows = [r for r in load() if r["model"] == "Qin Plus EV"]
    assert rows and not usable(rows[0]), "the contradicted Qin Plus row is still usable"


def test_a_call_can_reserve_what_it_asks_for():
    assert S._fit_completion("x" * 4000, want=900) == 900
    # And it still shrinks rather than 413 when the prompt is enormous.
    huge = S._fit_completion("x" * (S.GROQ_TPM * 4), want=900)
    assert huge < 900, f"a huge prompt should shrink the reservation, got {huge}"


def _capture_repair():
    """Run a repair with the network stubbed, returning what it would send."""
    spec = {"scenes": [{"type": "stat", "value": 139900, "prefix": "AED",
                        "narration": "The FJ starts at 139,900 dirhams."}]}
    seen = {}

    def capture(prompt, schema, name, want=None, system=None):
        seen.update(prompt=prompt, want=want, system=system)
        return json.dumps({"narrations": ["The FJ starts at 139,900 dirhams."]})

    real, S._groq_json = S._groq_json, capture
    try:
        S.rewrite_narration(spec, [], "AED 139,900")
    finally:
        S._groq_json = real
    return seen


def test_the_repair_does_not_ship_the_writing_brief():
    """SYSTEM is the brief for WRITING a script, useless to a rewrite.

    Sending it anyway spent 2,602 tokens of an 8,000-per-minute budget on
    every repair call, which is what left only 900 for the answer.
    """
    seen = _capture_repair()
    assert seen["system"] is not None, "the repair fell back to SYSTEM"
    assert seen["system"] != S.SYSTEM
    assert len(seen["system"]) < len(S.SYSTEM) / 4, (
        f"the repair brief is {len(seen['system'])} chars against SYSTEM's "
        f"{len(S.SYSTEM)}; it should be a fraction of it")


def test_the_repair_budget_can_finish_a_document():
    """900 did not. The model reasons before it answers, and two of three
    topics in one night died on 'max completion tokens reached before
    generating a valid document'."""
    seen = _capture_repair()
    assert seen["want"] >= 1800, (
        f"the repair asked for only {seen['want']} completion tokens")
    budget = S._fit_completion(seen["prompt"], seen["want"],
                               system=seen["system"])
    assert budget == seen["want"], (
        f"the prompt crushed the reservation to {budget}")


def test_the_repair_brief_keeps_the_abbreviation_rule():
    """unspeakable() checks repaired lines too, so a rewrite that
    reintroduces "AED" fails. That rule lived only in SYSTEM."""
    sysmsg = _capture_repair()["system"]
    assert "dirhams" in sysmsg and "AED" in sysmsg, sysmsg



# ------------------------------------------------------------ description --

def _desc_spec(description, title="BYD Seagull price in UAE"):
    return {"title": title, "description": description, "scenes": [
        {"type": "compare", "rows": [{"name": "Sealion 5", "value": 89900},
                                     {"name": "Atto 3", "value": 109900}],
         "narration": "Sealion 5 starts at 89,900 dirhams."}]}


def test_a_false_cheapest_in_the_description_is_dropped():
    """Draft #134 published "the cheapest BYD model we found costs 109,900"
    two lines above its own 89,900 Sealion 5. Inside a named brand the claim
    is checked against that brand's rows."""
    spec = _desc_spec("The cheapest BYD model we found in the UAE costs 109,900 "
                      "dirhams. Prices exclude registration and insurance.")
    dropped = S.clean_description(spec, "")
    assert dropped and "109,900" in dropped[0], dropped
    assert "109,900" not in spec["description"], spec["description"]
    assert "exclude registration" in spec["description"], "a good sentence was lost"


def test_true_and_bounded_cheapest_claims_stay():
    for sent, title in [
            ("The cheapest BYD electric SUV starts at 109,900 dirhams.", ""),
            ("The GR 86 is the cheapest at 162,900 dirhams.",
             "Toyota GR prices in UAE - which one is cheapest"),
            ("Buy the Chery Arrizo 5 if you want the cheapest new sedan under "
             "40,000 dirhams.", ""),
            ("The cheapest motorcycle we found is the Sharmax RST 150 Ultra at "
             "4,990 dirhams.", "")]:
        assert S._description_superlative(sent, title) is None, sent


def test_an_invented_figure_in_the_description_is_dropped():
    spec = _desc_spec("Sealion 5 costs 89,900 dirhams. Insurance adds about "
                      "6,500 a year.", title="BYD Sealion 5 price in UAE")
    dropped = S.clean_description(spec, "BYD Sealion 5 | from AED 89,900")
    assert len(dropped) == 1 and "6,500" in dropped[0], dropped
    assert "89,900" in spec["description"]


def test_citations_and_dates_are_not_claims():
    # A real link carries numbers too: listing IDs, article slugs.
    spec = _desc_spec("• Sealion 5: 89,900 (https://www.yallamotor.com/new-cars/"
                      "byd/sealion-5/48213, checked 2026-10-07)",
                      title="BYD Sealion 5 price")
    assert not S.description_faults(spec, "from AED 89,900"), \
        S.description_faults(spec, "from AED 89,900")


def test_generate_cleans_the_description():
    """The check is only a gate if the real entry point runs it."""
    real = S._generate
    S._generate = lambda q, facts="", writer=None: _desc_spec(
        "The cheapest BYD model we found in the UAE costs 109,900 dirhams.")
    try:
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            spec = S.generate("byd price in uae", "")
    finally:
        S._generate = real
    assert "109,900" not in spec["description"], spec["description"]



# ------------------------------------------------ figures under 1,000 --

_SEATBELT = "Traffic law: Not wearing a seat belt | AED 400 | 4 black points"


def _one_line(text, value=400):
    return {"title": "Seat belt fine in UAE", "scenes": [
        {"type": "stat", "value": value, "label": "Seat belt fine",
         "narration": "Skipping the seat belt costs 400 dirhams."},
        {"type": "verdict", "narration": text}]}


def test_a_small_invented_fine_is_caught():
    """PROSE_FLOOR skipped every number under 1,000, so an invented 600
    dirham impound fee passed every check. Most fines live under 1,000."""
    bad = S.invents_a_figure(_one_line(
        "Do it twice and you pay 800 dirhams plus a 600 dirham impound fee."),
        _SEATBELT)
    assert any("-> 600 " in b for b in bad), bad
    assert not any("-> 800 " in b for b in bad), "400 + 400 is honest arithmetic"


def test_invented_black_points_are_caught_in_digits_and_words():
    for line in ("It also costs 6 black points.", "It also costs six black points."):
        bad = S.invents_a_figure(_one_line(line), _SEATBELT)
        assert bad and "-> 6 " in bad[0], (line, bad)
    for line in ("It also costs 4 black points.", "It also costs four black points."):
        assert not S.invents_a_figure(_one_line(line), _SEATBELT), line


def test_small_numbers_that_are_not_claims_are_left_alone():
    for line in ("A 7 seat SUV fits the whole family.",
                 "Check your tyre pressure every 30 days in summer.",
                 "It takes about 20 minutes at the RTA centre."):
        assert not S.invents_a_figure(_one_line(line), _SEATBELT), line


def test_false_alarms_found_on_past_scripts_stay_quiet():
    """Each of these was flagged by the first version of the small-figure
    check, measured across all 140 saved scripts."""
    facts = ("Land Cruiser 2026 | from AED 239,900\nChery Arrizo 5 | AED 35,795"
             "\nMitsubishi Attrage | from AED 36,000\nJetour X70 | 84,900"
             "\nJetour Dashing | 94,900\nJetour X50 | 74,900")
    spec = {"title": "t", "scenes": [
        {"type": "compare", "rows": [{"name": "Arrizo 5", "value": 35795},
                                     {"name": "Attrage", "value": 36000},
                                     {"name": "Dashing", "value": 94900},
                                     {"name": "X70", "value": 84900},
                                     {"name": "X50", "value": 74900}],
         "narration": "x"},
        {"type": "verdict", "narration":
         "The base price is two hundred thirty-nine thousand nine hundred dirhams."},
        {"type": "bullets", "narration":
         "The Arrizo 5 undercuts the competition by at least 200 dirhams."},
        {"type": "question", "narration":
         "The Dashing is about AED 10k more than the X70 and AED 20k more than the X50."}]}
    assert not S.invents_a_figure(spec, facts), S.invents_a_figure(spec, facts)


def test_an_impound_period_is_a_claim():
    bad = S.invents_a_figure(_one_line("Your car is impounded for 30 days."),
                             _SEATBELT)
    assert bad and "-> 30 " in bad[0], bad


def test_a_small_invented_figure_in_the_description_is_dropped():
    spec = _one_line("Buckle up.")
    spec["description"] = ("The seat belt fine is 400 dirhams. Repeat offenders "
                           "pay 750 dirhams.")
    dropped = S.clean_description(spec, _SEATBELT)
    assert len(dropped) == 1 and "750" in dropped[0], dropped



# --------------------------------------------------- template read aloud --

def _leak(field, text, kind="verdict"):
    return {"title": "Car battery life in UAE", "scenes": [{"type": kind, field: text}]}


def test_template_instructions_read_aloud_are_caught():
    """All of these went out in published videos (#5, #23, #30, #37, #63, #81)."""
    for field, text, kind in [
            ("narration", "Quickly address the hook with facts.", "hook"),
            ("narration", "Ask viewers for their current situation.", "question"),
            ("narration", "Answer in four words.", "question"),
            ("narration", "Here's what the price hides.", "bullets"),
            ("title", "What the price hides", "bullets")]:
        assert S.reads_the_template(_leak(field, text, kind)), (field, text)


def test_ordinary_lines_are_not_template():
    for text in ("Batteries last two to three years in UAE heat.",
                 "The excess is what you pay before the insurer pays.",
                 "Here is what the dealer leaves out of the price.",
                 "Answer this: would you pay 10,000 more for a hybrid?"):
        assert not S.reads_the_template(_leak("narration", text)), text


def test_the_template_check_runs_with_the_others():
    assert S._narration_faults(_leak("narration", "Answer in four words.",
                                     "question"), "")


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
