"""Regression tests for cars.facts_for.

Every case here is a bug that actually shipped. The comments in cars.py
record them in prose; this file makes them fail a test run instead, so the
next person to touch the scoring finds out immediately.

    python -m pytest tests/test_retrieval.py -q
    python tests/test_retrieval.py            # same, without pytest
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits.cars import facts_for     # noqa: E402

# (query, must appear in the first N lines, must not appear anywhere)
# `leads` is checked against the top three rows: ranking is the thing these
# bugs got wrong, and demanding the exact first row makes the test brittle
# against a legitimate price-order change.
CASES: list[tuple[str, list[str], list[str]]] = [
    # The T1 sat seventh in its own query, behind six other Jetours ordered
    # only by price, and a MINI Cooper ELECTRIC outranked it because the
    # phrase rule "ev" fired inside "r-ev-iew".
    ("jetour t1 uae review", ["T1"], ["MINI", "Cooper"]),
    ("jetour g700 uae review", ["G700"], ["MINI", "Cooper"]),

    # "maximum" scored as a rare word and found "Maximum total repayments".
    ("maximum tint percentage uae", ["tint"], ["repayment"]),

    # Both rows contain "car", so a flat word count answered an impound
    # question with a car loan.
    ("car impound rules in dubai", ["impound"], ["loan", "Registration"]),

    # insurance.csv loads first, so file order answered this with a
    # third-party liability table.
    ("salik charges dubai", ["Salik"], ["liability"]),

    # Plural folding: without it this matched no row saying "tyre" and
    # answered an age question with the fine.
    ("how old can car tyres be in uae", ["age", "tyre"], []),

    # Vocabulary bridges: nobody types the word a spec sheet uses.
    ("7 seater car in dubai", ["MPV", "seat", "Large", "Full"], []),
    ("best first car in uae", ["Hatchback", "Sedan", "Compact"], []),

    # Price-ranked questions. These are about RANKING, which is why each one
    # names the row that must lead: a cheapest-X video whose first figure is
    # not the cheapest X is wrong in the one way the title promises.
    ("cheapest cars in uae", ["Arrizo"], []),
    ("budget cars in uae", ["Arrizo"], []),
    ("best budget car in dubai", ["Arrizo"], []),
    # Led by four petrol SUVs, because price sorted ahead of match quality.
    ("cheapest electric suv in uae", ["Spark EUV"], ["Petrol"]),
    # And then by a MINI Cooper ELECTRIC at AED 235,000, because "electric"
    # scores 3x against a model NAME and 1x against a powertrain.
    # This case used to demand "BYD Qin Plus" in the lead, which locked a
    # single aggregator row in as ground truth. That row turned out to be a
    # PHEV listed as an EV, and is now withheld as CONFLICT. A test should
    # pin the RANKING (an electric car, cheapest first), not a car.
    ("cheapest electric car in uae", ["Electric"], ["Petrol"]),
    # Led by a Land Cruiser 70 at AED 177,900 — a Full Size SUV matched two
    # words of the "7 seater" bridge where an MPV matched one.
    ("cheapest 7 seater in uae", ["Xpander", "MPV"], []),
    ("cheapest nissan in uae", ["Magnite"], []),
    # The guard on the fallback: the cheapest rows in this file are not an
    # answer to a question about a brand it has nothing cheap from.
    ("cheapest ferrari in uae", ["Ferrari"], ["Chery", "Mitsubishi"]),

    # The highest-demand phrase in the whole queue, and it returned nothing.
    ("car expenses in dubai", ["Registration", "Salik", "Fuel"], []),
    ("running cost of a car in uae", ["Registration", "Salik", "Fuel"], []),

    # Category words may not score against a model NAME. "electric" matched
    # "MINI Cooper Electric" three times over, so a generic electric-car
    # query led with a 235,000 MINI and never reached the cheap EVs; the
    # writer then called 109,900 "the cheapest electric car in Dubai".
    ("electric car in dubai in kannada", ["Spark EUV", "Aion ES"], []),
    ("ev car in dubai", ["Spark EUV", "Aion ES"], []),
    ("byd sedan uae", ["BYD"], []),      # led by a Mazda3 Sedan, on "sedan"
    # ...but once a family IS named, the same word tells its variants apart.
    ("land cruiser hybrid vs petrol uae", ["Land Cruiser Hybrid"], []),
    ("mini cooper electric uae", ["Cooper Electric"], []),

    # Deliberate non-matches. "black"/"white" and "hot" stay out of the
    # routing words so these remain shopping queries.
    ("white car dubai", [], ["black point", "Black point"]),
    ("hot hatch uae", [], ["temperature", "Cabin"]),
]


def _check(query, leads, forbidden):
    out = facts_for(query)
    problems = []
    if not out:
        # A case that only lists forbidden rows is asserting "do not route
        # this query into the wrong file". Returning nothing satisfies that.
        return [] if not leads else [f"{query!r} returned nothing at all"]
    head = "\n".join(out.splitlines()[:3])
    if leads and not any(w.lower() in head.lower() for w in leads):
        problems.append(
            f"{query!r}: none of {leads} in the top 3 rows:\n      "
            + "\n      ".join(out.splitlines()[:3]))
    for w in forbidden:
        if re.search(rf"(?i)(?<!\w){re.escape(w)}", out):
            problems.append(f"{query!r}: {w!r} should not appear, but does")
    return problems


def test_retrieval_regressions():
    failures = [p for q, l, f in CASES for p in _check(q, l, f)]
    assert not failures, "\n  " + "\n  ".join(failures)


# Topics the data genuinely cannot answer must come back empty rather than
# returning a plausible-looking but unrelated set. A hollow script costs a
# render; these return nothing so the pipeline skips them.
UNCOVERED = ["used car prices in uae", "car mechanic in dubai",
             "car ride in dubai", "vat refund in uae",
             # Process questions about the RTA portal. Routing these in got
             # the writer a seat-belt fine to talk about under a title
             # promising something else — see ROUTE_ONLY in cars.py.
             "traffic fine check online uae", "how to check traffic fine uae"]


def test_a_model_the_data_lacks_finds_nothing():
    """Draft #134, "BYD Seagull price in UAE", was published without ever
    stating a Seagull price: "seagull" matched no row, "byd" matched fourteen,
    and the writer was handed other BYDs under a Seagull title."""
    for q in ("byd seagull uae", "byd leopard 5 review uae",
              "byd yangwang u8 in uae"):
        assert not facts_for(q), f"{q!r} was handed rows for other models"


def test_a_brand_with_a_generic_word_is_still_covered():
    """The rule reads the word after the brand. Generic words, years and
    second brand words must not trip it."""
    for q in ("byd price in uae", "toyota 2026 price uae", "ducati prices in uae",
              "land rover defender price uae", "mercedes benz gle price uae",
              "royal enfield prices in uae", "jetour t1 uae review"):
        assert facts_for(q), f"{q!r} lost its rows"


def test_a_price_is_only_cited_to_the_car_it_belongs_to():
    """The Qin Plus EV's 74,900 was cited to a Dongfeng AX7, which costs the
    same. attach_sources() fills missing citations with this, so a matching
    number from a different car produced a confident, wrong source."""
    from autoedits.cars import source_for
    src = source_for(74900, "BYD Qin Plus EV starts at 74,900 dirhams")
    assert src is None or "Qin" in src, f"cited to another car: {src}"
    src = source_for(74900, "Dongfeng AX7 price")
    assert src and "AX7" in src, src


def test_a_bare_number_is_not_cited_to_whichever_car_matches():
    from autoedits.cars import source_for
    assert source_for(74900, "starting price") is None


def test_a_trim_price_is_found_in_its_own_cars_notes():
    """Trim prices live in the notes ("AT GLX 2.7 petrol 137,900"). With the
    car named, the notes are a safe place to look."""
    from autoedits.cars import source_for
    src = source_for(137900, "Toyota Hilux 2027 AT GLX 2.7 petrol")
    assert src and "Hilux" in src, src


def test_a_rejected_figure_in_the_notes_is_not_a_source():
    """Seal 7 notes keep the aggregator's wrong 109,900 for the record. It
    must never vouch for a script that repeats it."""
    from autoedits.cars import source_for
    assert source_for(109900, "BYD Seal 7 price") is None


def test_auto_citation_cites_the_car_the_script_is_about():
    """Measured on every saved script before this fix: the FJ was cited to a
    Honda Accord, a Land Cruiser GXR to a BYD Seal, and Land Cruiser trims to
    a Dodge Charger and a Genesis G90, all at matching prices."""
    from autoedits.script import attach_sources
    spec = {"title": "Land Cruiser hybrid vs petrol in UAE", "scenes": [
        {"type": "compare", "title": "Petrol vs hybrid, by trim",
         "rows": [{"name": "GXR petrol", "value": 335900},
                  {"name": "VXR petrol", "value": 379900}]},
        {"type": "stat", "label": "Starting price", "value": 154900,
         "narration": "Land Cruiser FJ GXR starts at 154,900 dirhams."}]}
    attach_sources(spec)
    assert "Land Cruiser" in spec["scenes"][0]["source"], spec["scenes"][0]["source"]
    assert "Charger" not in spec["scenes"][0]["source"]
    assert "Land Cruiser FJ" in spec["scenes"][1]["source"], spec["scenes"][1]["source"]


def test_a_line_naming_no_car_is_traced_only_when_unambiguous():
    from autoedits.cars import source_for
    # One row at this price, and it is the kind of car the line says.
    assert "Arrizo" in (source_for(35795, "The cheapest new sedan starts at 35,795") or "")
    # "EV" is a claim about the car; a petrol car at the same price is not it.
    assert source_for(74900, "The cheapest EV starts at 74,900 dirhams") is None


def test_an_apostrophe_is_not_a_model_name():
    """"That's" leaves an "s", which matched the Mercedes S-Class."""
    from autoedits.cars import source_for
    src = source_for(69500, "Cheapest Jetour SUV price. That's the sticker price.")
    assert src and "Jetour" in src, src


def test_a_fact_table_is_not_matched_on_the_narration():
    """"AED 1,000 is the average annual cost" was cited to the 1,000 excess cap."""
    from autoedits.script import attach_sources
    spec = {"title": "best car insurance in uae", "scenes": [
        {"type": "stat", "label": "average annual cost", "value": 1000,
         "narration": "AED 1,000 is the average annual cost."}]}
    attach_sources(spec)
    assert "Excess" not in (spec["scenes"][0].get("source") or ""), spec["scenes"][0]


def test_uncovered_stays_empty():
    wrong = [q for q in UNCOVERED if facts_for(q)]
    assert not wrong, f"these have no supporting data and should return nothing: {wrong}"


def test_a_category_query_is_never_led_by_a_name_match():
    """The lead row of a pure category query must be the category's cheapest,
    not whichever luxury model happens to carry the category in its name."""
    for q in ("electric car in uae", "electric car in dubai in kannada"):
        lead = facts_for(q).splitlines()[0]
        assert not any(w in lead for w in ("MINI Cooper", "Porsche", "Hummer")), (
            f"{q!r} is led by a name match: {lead[:80]}")


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as exc:
                bad += 1
                print(f"FAIL  {name}{exc}")
    raise SystemExit(bad)
