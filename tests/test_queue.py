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


def test_a_bike_topic_is_not_a_repeat_of_a_car_video():
    """Dropping "motorcycle" as a stopword turned "motorcycle licence age in
    uae" into {licence, age}, refused as a repeat of a black-points video."""
    s = _sim("motorcycle licence age in uae",
             "How to Check Black Points on License in Dubai")
    assert s < D.TOO_SOON, f"scored {s:.2f} against an unrelated car video"
    s = _sim("motorcycle insurance cost in uae", "Car insurance cost in UAE")
    assert s < D.SAME_TOPIC, f"a bike topic scored {s:.2f} against its car twin"


def test_two_wordings_of_one_bike_topic_still_match():
    s = _sim("bike licence age uae", "Motorcycle licence age in UAE")
    assert s >= D.SAME_TOPIC, f"only {s:.2f}; these are the same video"


def test_an_unrelated_topic_scores_nothing():
    assert _sim("budget suv in uae", "Tyre tread law in UAE: avoid fines") == 0.0


def _run_with(topics, covered):
    """Run the nightly selection with the queue and coverage stubbed out."""
    text, out, _ = _run_built(topics, covered, 5)
    return text, out


def _run_built(topics, covered, n):
    """As _run_with, also returning the queries make_one was handed, in order."""
    real_next, real_facts, real_make = D.next_topics, P.facts_for, P.make_one
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


def test_one_slot_a_night_goes_to_a_covered_bike_topic():
    """Bike topics sit far below the car topics by score. The reserved slot
    is the only way one is ever built."""
    cars = [f"car topic {i} in uae" for i in range(5)]
    text, _, built = _run_built(cars + ["cheapest motorcycle in uae"],
                                set(cars) | {"cheapest motorcycle in uae"}, 3)
    assert built[0] == "cheapest motorcycle in uae", built
    assert built[1:] == cars[:2], f"the car slots were not filled in order: {built}"


def test_an_unbacked_bike_slot_goes_back_to_the_cars():
    cars = [f"car topic {i} in uae" for i in range(5)]
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
    text, made = _run_with(["car ride in dubai", "car mechanic in dubai"], covered=set())
    assert "nothing was built" in text, (
        "a night that built nothing never said so:\n" + text)
    assert "Add rows to data/cars.csv" in text, "no next step was offered"
    assert "No data for 2" in text, "the uncovered topics were not named"
    assert made == [], made


def test_a_productive_night_reports_what_it_built():
    text, _ = _run_with(["cheapest cars in uae", "car ride in dubai"],
                        covered={"cheapest cars in uae"})
    assert "1 of 2 queued topics have data" in text, text
    assert "nothing was built" not in text, "claimed failure on a working night"
    assert "No data for 1" in text, "did not name the one it skipped"


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
