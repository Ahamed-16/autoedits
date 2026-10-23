"""The motorcycle expansion: separate pools, and the nightly bike slot.

The failure these guard against is a quiet one. A car query handed a 4,990
Sharmax would call it "the cheapest car in the UAE"; a bike query handed a
Kia would read out a car price as a motorcycle's. Both read as sourced.

    python tests/test_bikes.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits import cars as C                    # noqa: E402
from autoedits import db as D                      # noqa: E402
from autoedits import script as S                  # noqa: E402

BIKE_BRANDS = {r["brand"] for r in C.load_bikes()}
BIKE_CATS = {r["category"] for r in C.usable_facts("bike")}


def _lines(q):
    return [l for l in C.facts_for(q).splitlines() if l.strip()]


def _is_bike_line(line: str) -> bool:
    return (any(line.startswith(b + " ") for b in BIKE_BRANDS)
            or any(line.startswith(c + ":") for c in BIKE_CATS))


def test_bike_queries_never_see_a_car():
    for q in ("cheapest motorcycle in uae", "honda motorcycle prices in uae",
              "motorcycle licence cost in dubai", "motorcycle insurance cost in uae",
              "cheapest scooter in dubai", "helmet fine uae",
              "honda cb300r price uae", "motorcycle red light fine in uae"):
        lines = _lines(q)
        assert lines, f"{q!r} found nothing"
        cars = [l[:70] for l in lines if not _is_bike_line(l)]
        assert not cars, f"{q!r} was handed non-motorcycle rows: {cars}"


def test_car_queries_never_see_a_bike():
    bike_cats = BIKE_CATS - {r["category"] for r in C.usable_facts("car")}
    for q in ("cheapest car in uae", "honda price uae", "honda civic price uae",
              "running a red light fine uae", "car insurance cost uae",
              "cheapest suv in dubai", "best first car in uae"):
        bad = [l[:70] for l in _lines(q)
               if any(l.startswith(b + " ") for b in BIKE_BRANDS - {"Honda"})
               or any(l.startswith(c + ":") for c in bike_cats)
               or " motorcycle |" in l or l.startswith("Honda CB")]
        assert not bad, f"{q!r} was handed motorcycle rows: {bad}"


def test_a_shared_brand_needs_a_bike_word():
    """Honda makes both. 'honda price uae' is a car question until it says
    motorcycle — or names a model only a bike has."""
    assert not C.is_bike_query("honda price uae")
    assert C.is_bike_query("honda motorcycle price uae")
    assert C.is_bike_query("honda cb300r price uae")
    assert C.is_bike_query("ducati price uae")
    # Bentley makes a Continental GT; so does Royal Enfield.
    assert not C.is_bike_query("continental gt price uae")


def test_off_road_bikes_only_when_asked():
    """A pit bike at 3,590 is not 'the cheapest motorcycle in the UAE': it
    cannot be registered for the road."""
    plain = C.facts_for("cheapest motorcycle in uae")
    assert "Sport 130 Mini" not in plain and "Pitbike" not in plain, plain[:300]
    assert "Sport 130 Mini" in C.facts_for("cheapest dirt bike in uae")
    # "trail" is an off-road word; "trailer" must not be.
    assert not C.wants_offroad("motorcycle trailer price dubai")


def test_bicycles_and_e_scooters_get_nothing():
    for q in ("e scooter rules dubai", "electric scooter fine dubai",
              "bicycle helmet rules uae", "e-bike price dubai"):
        assert not C.facts_for(q), f"{q!r} was handed motorcycle data"


def test_american_spelling_reaches_the_licence_rows():
    """Every row says "licence". Unfolded, "license renewal" matched only on
    "renewal" and led with the registration fee."""
    lead = _lines("motorcycle license renewal uae")[0]
    assert "Licence renewal" in lead, lead


def test_contradicted_fees_are_withheld():
    """Belhasa quotes 225, 320 and 220 (and 120 elsewhere on its own page);
    RTA's page says 100, 300 and an unlabelled 200. None of the disputed
    figures may reach the writer."""
    text = C.facts_for("motorcycle licence cost in dubai") + \
        C.facts_for("motorcycle licence fee under 21 dubai")
    for item in ("Belhasa-quoted", "add a category"):
        assert item not in text, f"withheld row {item!r} reached the writer"
    assert "passenger without a helmet - black points" not in \
        C.facts_for("motorcycle passenger helmet fine uae")


def test_bike_law_rows_pass_the_source_gate():
    from autoedits.sources import LAW_CATEGORIES, ACCEPTABLE_FOR_LAW, tier_of
    rows = [r for r in C.load_facts("all")
            if r["category"].startswith(("Motorcycle", "Delivery"))
            or r["category"] == "Traffic offence (all vehicles)"]
    law = [r for r in rows if r["category"] in LAW_CATEGORIES]
    assert len(law) > 50, f"bike law categories are not gated: {len(law)}"
    bad = [r["item"] for r in law if tier_of(r["source_url"]) not in ACCEPTABLE_FOR_LAW]
    assert not bad, f"bike law rows on a non-official source: {bad}"
    # A driving school is never a legal source.
    assert tier_of("https://www.bdc.ae/motorcycle-course/") == "provider"


def _cheapest_spec(title, value):
    return {"title": title, "scenes": [
        {"type": "stat", "label": "Cheapest", "value": value,
         "narration": f"It starts at {value:,} dirhams."}]}


def test_a_false_cheapest_motorcycle_is_caught():
    f = S.false_superlative(_cheapest_spec("Cheapest motorcycle in the UAE", 6990))
    assert f and "motorcycle" in f[0] and "4,990" in f[0], f


def test_a_true_cheapest_motorcycle_passes_despite_pit_bikes():
    road = min(int(r["price_from_aed"]) for r in C.load_bikes()
               if C.usable(r) and C.road_bike(r))
    assert not S.false_superlative(_cheapest_spec("Cheapest motorcycle in the UAE", road))


def test_a_cheap_car_claim_is_not_judged_against_bikes():
    """The cheapest car must not fail because a scooter costs 5,990."""
    car = min(int(r["price_from_aed"]) for r in C.load()
              if C.usable(r) and r["price_from_aed"])
    assert not S.false_superlative(_cheapest_spec("Cheapest car in the UAE", car))


def test_new_units_are_not_drawn_as_dirhams():
    for u in ("lanes", "lane", "hours", "lectures", "km/h"):
        assert S._unit(u)[0] != "AED", f"unit {u!r} would render as AED"


def test_the_bike_slot_reaches_past_the_car_queue():
    """Bike topics are a few dozen rows behind 1,500 car phrases. Without
    the match filter they never enter the 400-row window at all."""
    old = D.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        D.DB_PATH = Path(tmp) / "t.db"
        try:
            D.init()
            for i in range(450):
                D.promote_topic(f"car topic {i} uae", "harvest", 1000 - i)
            D.promote_topic("cheapest motorcycle in uae", "evergreen", 1)
            plain = [r["query"] for r in D.next_topics(400)]
            bikes = [r["query"] for r in D.next_topics(5, match=C.is_bike_query)]
            cars_only = [r["query"] for r in
                         D.next_topics(400, match=lambda q: not C.is_bike_query(q))]
        finally:
            D.DB_PATH = old
    assert "cheapest motorcycle in uae" not in plain
    assert bikes == ["cheapest motorcycle in uae"], bikes
    assert "cheapest motorcycle in uae" not in cars_only


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as exc:
                bad += 1
                print(f"FAIL  {name}  {exc}")
    raise SystemExit(bad)
