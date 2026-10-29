"""Regression tests for topic selection and the nightly run's reporting.

Both bugs here produced the same symptom — "0 draft(s) ready" for two nights
running — and neither raised anything. One starved the queue; the other threw
away the sentence that would have explained it.

    python tests/test_queue.py
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits import db as D                      # noqa: E402
from autoedits import pipeline as P                # noqa: E402


def _sim(query: str, title: str) -> float:
    a, b = D._subject(query), D._subject(title)
    return D._similarity(a, b, D._idf([a, b]))


def test_a_one_word_subject_is_not_swallowed_by_a_longer_title():
    """The bug that starved the queue.

    "cheapest cars in uae" reduces to {cheapest} once stopwords go. Dividing
    by the shorter subject made containment automatic, so it scored 1.00
    against any title containing the word — and 305 of the top 400 queued
    topics were refused this way while 1,186 topics with data sat behind the
    guard.
    """
    s = _sim("cheapest cars in uae",
             "Toyota GR prices in UAE - which one is cheapest")
    assert s < D.SAME_TOPIC, (
        f"a one-word subject scored {s:.2f} against an unrelated title; "
        f"anything >= {D.SAME_TOPIC} blocks it")


def test_a_genuine_rephrasing_is_still_refused():
    """The behaviour the guard exists for, which the fix must not weaken."""
    for q in ("black points uae", "how to check black points in uae"):
        s = _sim(q, "How to Check Black Points in UAE")
        assert s >= D.SAME_TOPIC, f"{q!r} scored only {s:.2f}; it is the same video"


class _Stop(Exception):
    pass


def _render_spec(spec, entry="from_spec", voice_exists=False):
    """Run a render path on a spec in a throwaway work dir. Returns
    (what it printed, whether the voice step was reached, superseded paths)."""
    import json, tempfile
    from autoedits import pipeline as Pm, voice as V
    reached, superseded = [], []
    real = (Pm.WORK, V.narrate, Pm.R.render, Pm.db.supersede, Pm.db.add_video,
            Pm.R.thumbnail, Pm.db.init)
    with tempfile.TemporaryDirectory() as tmp:
        Pm.WORK = Path(tmp)
        d = Path(tmp) / "slug"
        d.mkdir()
        (d / "spec.json").write_text(json.dumps(spec))
        if voice_exists:
            (d / "voice.mp3").write_bytes(b"x")

        def narrate(*a, **k):
            reached.append("voice")
            raise _Stop()
        V.narrate = narrate
        Pm.R.render = lambda *a, **k: reached.append("render")
        Pm.R.thumbnail = lambda *a, **k: None
        Pm.db.init = lambda: None
        Pm.db.supersede = lambda p, *a, **k: superseded.append(p) or 0
        Pm.db.add_video = lambda *a, **k: 1
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                getattr(Pm, entry)("slug")
        except _Stop:
            pass
        finally:
            (Pm.WORK, V.narrate, Pm.R.render, Pm.db.supersede, Pm.db.add_video,
             Pm.R.thumbnail, Pm.db.init) = real
    return buf.getvalue(), reached, superseded


_GOOD = {"title": "Toyota Hilux 2027 price in UAE", "tags": [], "scenes": [
    {"type": "hook", "text": "Hilux price?", "narration": "What does a Hilux cost?"},
    {"type": "stat", "label": "Hilux from", "value": 120900, "prefix": "AED",
     "source": "https://www.toyota.ae/en/new-cars/hilux",
     "narration": "The Hilux starts at 120,900 dirhams."},
    {"type": "verdict", "text": "Start with the GL.", "narration": "Start with the GL."},
    {"type": "question", "text": "Petrol or diesel?", "narration": "Petrol or diesel?"}]}


def test_from_spec_refuses_a_failing_script_before_the_voice():
    """--from-spec ran only the sourcing gate, so a hand-edited spec with a
    template line in it went straight to the voice and the render."""
    import copy
    bad = copy.deepcopy(_GOOD)
    bad["scenes"][3]["narration"] = "Answer in four words."
    text, reached, _ = _render_spec(bad)
    assert "refused" in text and "four words" in text, text
    assert reached == [], f"reached {reached} with a failing script"


def test_from_spec_lets_a_clean_script_through():
    text, reached, _ = _render_spec(_GOOD)
    assert reached == ["voice"], (reached, text)


def test_rebuild_checks_and_retires_the_old_draft():
    import copy
    bad = copy.deepcopy(_GOOD)
    bad["scenes"][3]["narration"] = "Answer in four words."
    text, reached, _ = _render_spec(bad, "rebuild", voice_exists=True)
    assert "refused" in text and reached == [], (text, reached)
    text, reached, superseded = _render_spec(_GOOD, "rebuild", voice_exists=True)
    assert reached == ["render"], (reached, text)
    assert superseded, "the rebuilt draft did not retire the old one"


def test_a_price_in_a_title_does_not_hide_a_repeat():
    """#137 "Best budget car in the UAE under 40,000 dirhams" and #138 "best
    budget car in uae dubai" were built on consecutive nights. The price
    words diluted #137's subject to 0.20 against a cooldown of 0.28."""
    s = _sim("best budget car in uae dubai",
             "Best budget car in the UAE under 40,000 dirhams")
    assert s >= D.TOO_SOON, f"only {s:.2f}; these are the same video"
    s = _sim("best budget car in uae dubai", "Best budget car in UAE Dubai under 40k")
    assert s >= D.TOO_SOON, f"only {s:.2f} with a '40k' price"


def test_a_bike_topic_is_not_a_repeat_of_a_car_video():
    """Dropping "motorcycle" as a stopword turned "motorcycle licence age in
    uae" into {licence, age}, refused as a repeat of a black-points video."""
    s = _sim("motorcycle licence age in uae",
             "How to Check Black Points on License in Dubai")
    assert s < D.TOO_SOON, f"scored {s:.2f} against an unrelated car video"
    s = _sim("motorcycle insurance cost in uae", "Car insurance cost in UAE")
    assert s < D.SAME_TOPIC, f"a bike topic scored {s:.2f} against its car twin"


def _queue_db(fn):
    """Run fn against a throwaway database."""
    import tempfile
    old = D.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        D.DB_PATH = Path(tmp) / "t.db"
        try:
            D.init()
            return fn()
        finally:
            D.DB_PATH = old


def _made(title):
    with D.conn() as c:
        c.execute("INSERT INTO videos(topic_id,status,title,description,tags,"
                  "scenes,video_path,poster_path,created_at) "
                  "VALUES (0,'draft',?,'','[]','[]','','',?)", (title, D.now()))


def _history():
    """A history shaped like the channel's: "cost" in many titles, "licence"
    in one — which is what makes the shared word decide. 30 cost videos also
    push the licence video out of the ten-night cooldown."""
    _made("Motorcycle licence age in UAE")
    for i in range(30):
        _made(f"Car model {i} running cost in UAE")


def test_an_evergreen_line_skips_only_the_permanent_guard():
    """"motorcycle licence cost" is a different video from "licence age",
    but scored 0.56 on the shared word and would never have been built."""
    def run():
        _history()
        D.promote_topic("motorcycle licence cost in dubai", "evergreen", 900)
        return [r["query"] for r in D.next_topics(5)], \
            D.why_blocked("motorcycle licence cost in dubai")
    picked, why = _queue_db(run)
    assert "motorcycle licence cost in dubai" in picked, picked
    assert why is None, why


def test_an_autocomplete_line_keeps_the_permanent_guard():
    def run():
        _history()
        D.promote_topic("motorcycle licence cost in dubai", "autocomplete", 900)
        return [r["query"] for r in D.next_topics(5)]
    assert "motorcycle licence cost in dubai" not in _queue_db(run)


def test_an_evergreen_line_still_waits_out_the_cooldown():
    def run():
        _made("Motorcycle licence age in UAE")
        D.promote_topic("motorcycle licence cost in dubai", "evergreen", 900)
        return [r["query"] for r in D.next_topics(5)]
    assert "motorcycle licence cost in dubai" not in _queue_db(run)


def test_loading_the_list_names_a_true_repeat():
    def run():
        _made("How to Check Black Points in UAE")
        return D.repeats_of(["black points uae", "motorcycle helmet fine in uae"])
    found = _queue_db(run)
    assert [q for q, _, _ in found] == ["black points uae"], found


def test_the_evergreen_loader_prints_the_warning():
    """Runs the real loader. No other test imported topics.py, and a broken
    string literal in this warning once got past the whole suite."""
    from autoedits import topics as T
    def run():
        _made("How to Check Black Points in UAE")
        real = T.load_evergreen
        T.load_evergreen = lambda: ["black points uae", "motorcycle helmet fine in uae"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                T.seed_evergreen(verbose=True)
            return buf.getvalue()
        finally:
            T.load_evergreen = real
    text = _queue_db(run)
    assert "already made" in text and "black points uae" in text, text
    assert "helmet" not in text.split("already made", 1)[1], text


def test_different_bike_topics_are_not_near_repeats():
    """The pool marker is not a subject word. Counted, it made every pair of
    bike topics look related, and one bike video blocked the bike queue."""
    for q in ("motorcycle helmet fine in uae", "motorcycle insurance cost in uae",
              "motorcycle red light fine in uae", "ducati prices in uae"):
        s = _sim(q, "Motorcycle licence age in UAE")
        assert s < D.TOO_SOON, f"{q!r} scored {s:.2f} against an unrelated bike video"


def test_two_wordings_of_one_bike_topic_still_match():
    s = _sim("bike licence age uae", "Motorcycle licence age in UAE")
    assert s >= D.SAME_TOPIC, f"only {s:.2f}; these are the same video"


def test_an_unrelated_topic_scores_nothing():
    assert _sim("budget suv in uae", "Tyre tread law in UAE: avoid fines") == 0.0


def _run_with(topics, covered):
    """Run the nightly selection with the queue and coverage stubbed out."""
    text, out, _ = _run_built(topics, covered, 5)
    return text, out


def _run_built(topics, covered, n, mine=()):
    """As _run_with, also returning the queries make_one was handed, in order."""
    real_next, real_facts, real_make = D.next_topics, P.facts_for, P.make_one
    real_mine = D.hand_written
    D.hand_written = lambda: set(mine)
    built = []
    D.next_topics = lambda k, match=None: [
        {"id": i, "query": q} for i, q in enumerate(topics)
        if match is None or match(q)][:k]
    P.facts_for = lambda q: "a row" if q in covered else ""
    P.make_one = lambda row: built.append(row["query"])
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = P.run(n)
        return buf.getvalue(), out, built
    finally:
        D.next_topics, P.facts_for, P.make_one = real_next, real_facts, real_make
        D.hand_written = real_mine


# Real phrases: a made-up one like "car topic 3 in uae" is now, correctly,
# skipped as junk ("topic" names nothing in the data).
CAR_TOPICS = ["toyota land cruiser price in uae", "nissan patrol price in uae",
              "byd seal price in uae", "hyundai tucson price in uae",
              "kia sportage price in uae"]


def test_one_slot_a_night_goes_to_a_covered_bike_topic():
    """Bike topics sit far below the car topics by score. The reserved slot
    is the only way one is ever built."""
    cars = CAR_TOPICS
    text, _, built = _run_built(cars + ["cheapest motorcycle in uae"],
                                set(cars) | {"cheapest motorcycle in uae"}, 3)
    assert built[0] == "cheapest motorcycle in uae", built
    assert built[1:] == cars[:2], f"the car slots were not filled in order: {built}"


def test_an_unbacked_bike_slot_goes_back_to_the_cars():
    cars = CAR_TOPICS
    text, _, built = _run_built(cars + ["yamaha r1 price in uae"], set(cars), 3)
    assert built == cars[:3], built
    assert "slot goes to a car topic" in text, text


def test_a_night_with_nothing_to_build_says_what_to_do():
    """The `else` that got re-bound.

    Inserting the uncovered listing between `if topics:` and its `else` moved
    that `else` onto `if uncovered:` — valid Python, silently wrong. The run
    printed the topics it could not build, skipped the sentence explaining
    what to do, and fell through instead of returning.
    """
    text, made = _run_with(["chevrolet tahoe price in dubai", "ford mustang price in dubai"],
                           covered=set())
    assert "nothing was built" in text, (
        "a night that built nothing never said so:\n" + text)
    assert "Add rows to data/cars.csv" in text, "no next step was offered"
    assert "No data for 2" in text, "the uncovered topics were not named"
    assert made == [], made


def test_a_productive_night_reports_what_it_built():
    text, _ = _run_with(["cheapest cars in uae", "ford mustang price in dubai"],
                        covered={"cheapest cars in uae"})
    assert "1 buildable car topic in the queue" in text, text
    assert "nothing was built" not in text, "claimed failure on a working night"
    assert "No data for 1" in text, "did not name the one it skipped"


def test_a_buildable_topic_below_the_window_is_found():
    """28 Oct: the window of 400 was cut BEFORE the data check. 349 of the top
    400 were repeats and the rest mostly had no data, so the run built no car
    video for five nights while 495 buildable topics sat further down."""
    import tempfile
    old = D.DB_PATH
    real_facts, real_make = P.facts_for, P.make_one
    built = []
    with tempfile.TemporaryDirectory() as tmp:
        D.DB_PATH = Path(tmp) / "t.db"
        try:
            D.init()
            for i in range(400):
                D.add_topic(f"nodata subject{i} in uae", demand=10.0 + i)
            D.add_topic("toyota land cruiser price in uae", demand=1.0)
            P.facts_for = lambda q: "a row" if q.startswith("toyota") else ""
            P.make_one = lambda row: built.append(row["query"])
            with redirect_stdout(io.StringIO()):
                P.run(2)
        finally:
            D.DB_PATH = old
            P.facts_for, P.make_one = real_facts, real_make
    assert built == ["toyota land cruiser price in uae"], built


def test_junk_is_never_built_but_your_own_phrase_is():
    topics = ["car insurance uae login", "best family car in uae kannada",
              "toyota land cruiser price in uae"]
    _, _, built = _run_built(topics, set(topics), 3)
    assert built == ["toyota land cruiser price in uae"], built
    _, _, built = _run_built(topics, set(topics), 3,
                             mine={"car insurance uae login"})
    assert "car insurance uae login" in built, "a phrase you added was filtered"


def test_junk_reason_on_real_queue_phrases():
    from autoedits.cars import junk_reason
    junk = ["car insurance uae login", "best family car in uae kannada",
            "car maintenance cost dubai airlines", "hybrid car in uae zip",
            "car tyres uae uae", "best first car in uae vlog"]
    fine = ["land cruiser 70 series uae", "toyota rav4 hybrid 2025 uae review",
            "petrol price uae", "cheapest motorcycle in uae",
            "dubai food delivery bike rider", "byd seal 7 price uae",
            "best affordable car in uae"]
    for q in junk:
        assert junk_reason(q), f"kept junk: {q!r}"
    for q in fine:
        assert junk_reason(q) is None, f"{q!r}: {junk_reason(q)}"


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"ok    {name}")
            except AssertionError as exc:
                bad += 1
                print(f"FAIL  {name}\n      {exc}")
    raise SystemExit(bad)
