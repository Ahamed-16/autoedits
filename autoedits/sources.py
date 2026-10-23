"""
Which sources are allowed to back which claims.

`cars.known_source_urls()` already stops the writer inventing citations: a URL
has to be one you personally put in a CSV. That catches fabrication. It does
not catch the other failure — a real URL you added in good faith that is not
entitled to settle the question.

A car-rental blog can tell you what a Corolla costs. It cannot tell you what
the law is, and when it tries, it gets it wrong in ways that read perfectly:
tiers shifted by one rung, black points invented, a fine schedule from the
previous decree presented as current. Three such blogs will give three
different answers and every one of them will look sourced.

So sources are tiered, in data/sources.csv:

    primary    the legislation itself — uaelegislation.gov.ae, moj.gov.ae
    official   the body that administers it — u.ae, RTA, MoI, Dubai Police,
               the Central Bank rulebook
    manufacturer  a brand or its UAE distributor: the last word on its own
               prices, no word at all on the law
    provider   a driving school (Belhasa, EDI): the last word on its own
               course fees, no word on RTA's — Belhasa's page quotes three
               different licence fees, none of them RTA's own
    press      Gulf News, Khaleej Times. Good for *that a rule changed*.
               Never good enough for *what the rule says*.
    unlisted   everything else

A row in a LAW category must be primary or official. Anything else is a
finding, not a preference.

    python -m autoedits.sources          # audit every fact row
    python -m autoedits.sources --list   # show the registry
"""

from __future__ import annotations

import csv
import sys
from functools import lru_cache
from urllib.parse import urlparse

from .config import ROOT

REGISTRY = ROOT / "data" / "sources.csv"

# Categories that make a claim about what is legally required or penalised.
# A number in one of these is not an opinion or a market price — someone can
# be fined on the strength of it, so it carries the strictest sourcing.
LAW_CATEGORIES = {
    "Traffic law", "Motor insurance law", "Comprehensive policy",
    "Driving licence", "White points", "Car finance",
    "Tyre law", "Window tint", "Child safety",
    # data/bike_rules.csv. Course fees, training hours and gear ADVICE are
    # deliberately not here: a school's price list is not a legal claim, and
    # "a reflective vest is advised" must never be gated as if it were law.
    "Motorcycle law", "Motorcycle licence", "Motorcycle helmet",
    "Motorcycle offence", "Traffic offence (all vehicles)",
    "Delivery bike rules", "Motorcycle registration",
}

# The law actually in force. Federal Decree-Law No. 14 of 2024 replaced the
# 2017 traffic law on 29 March 2025 — and crucially, Article 45 delegates the
# fines and black points to a Cabinet resolution rather than setting them
# itself. That is why no two published fine tables agree: they are quoting
# schedules of different vintages. A row whose legal_basis is blank is not
# necessarily wrong; it is unaudited, which is the thing worth knowing.
GOVERNING = {
    "traffic": {
        "law": "Federal Decree-Law No. 14 of 2024 on Traffic Regulation",
        "effective": "2025-03-29",
        "url": "https://uaelegislation.gov.ae/en/legislations/2598",
        "note": "Fines and black points are set by Cabinet resolution under "
                "Article 45, not by the decree itself.",
    },
    # Tint and tyre limits are three documents deep, and the last one is not
    # published free. This is why every blog paraphrases and why the numbers
    # drift: nobody quoting them has read the text that sets them.
    "vehicle_standards": {
        "law": "Cabinet Resolution No. 117 of 2024 on the Technical "
               "Regulation for Safety Requirements for Modified Vehicles",
        "effective": "2024",
        "url": "https://uaelegislation.gov.ae/en/legislations/2687",
        "note": "The resolution only makes standard UAE.S 5014:2024 "
                "mandatory; the figures live in that standard, which MOIAT "
                "SELLS rather than publishes. Confirmed at "
                "eservices.moiat.gov.ae → Purchase Standards. So no free "
                "source can quote it properly, and every blog paraphrase is "
                "second-hand at best. Either buy the standard, or source the "
                "figure to a regulator page that states it outright — or "
                "write the video so it makes no numeric legal claim.",
    },
}

# A carmaker is the last word on its own prices and specs, and no word at all
# on the law. "manufacturer" is deliberately absent from this set so a legal
# claim sourced to toyota.ae or honda-mideast.com still fails the gate.
ACCEPTABLE_FOR_LAW = {"primary", "official"}


@lru_cache(maxsize=1)
def registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    with REGISTRY.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("domain")]


def _host(url: str) -> str:
    host = (urlparse(url.strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def tier_of(url: str) -> str:
    """primary | official | press | unlisted.

    Matched on the longest registered suffix, so rulebook.centralbank.ae wins
    its own entry rather than inheriting the looser centralbank.ae one.
    """
    host = _host(url)
    if not host:
        return "unlisted"
    best, best_len = "unlisted", -1
    for row in registry():
        dom = row["domain"].lower()
        if (host == dom or host.endswith("." + dom)) and len(dom) > best_len:
            best, best_len = row["tier"].strip(), len(dom)
    return best


def authority_for(url: str) -> str:
    host = _host(url)
    for row in registry():
        if host == row["domain"].lower():
            return row.get("authority", "")
    return ""


def audit(rows: list[dict]) -> list[dict]:
    """Every fact row whose sourcing does not meet its category's bar."""
    problems = []
    for r in rows:
        cat = (r.get("category") or "").strip()
        if cat not in LAW_CATEGORIES:
            continue
        url = (r.get("source_url") or "").strip()
        tier = tier_of(url)
        if tier not in ACCEPTABLE_FOR_LAW:
            problems.append({
                "category": cat,
                "item": (r.get("item") or "").strip(),
                "tier": tier,
                "host": _host(url) or "(no source)",
                "why": "press reporting is not a legal source" if tier == "press"
                       else "domain is not in the official registry",
            })
    return problems


def report() -> int:
    from .cars import load_facts

    rows = load_facts("all")
    law_rows = [r for r in rows
                if (r.get("category") or "").strip() in LAW_CATEGORIES]
    problems = audit(rows)

    print(f"\nSource audit — {len(law_rows)} legal claims across "
          f"{len(rows)} fact rows\n")

    counts: dict[str, int] = {}
    for r in law_rows:
        counts[tier_of(r.get("source_url", ""))] = \
            counts.get(tier_of(r.get("source_url", "")), 0) + 1
    for tier in ("primary", "official", "manufacturer", "provider", "press",
                 "unlisted"):
        if counts.get(tier):
            mark = "ok " if tier in ACCEPTABLE_FOR_LAW else "BAD"
            print(f"  {mark}  {tier:<12} {counts[tier]:>3} claims")

    if not problems:
        print("\nEvery legal claim rests on a primary or official source.\n")
        return 0

    print(f"\n{len(problems)} claim(s) cannot be defended:\n")
    by_cat: dict[str, list[dict]] = {}
    for p in problems:
        by_cat.setdefault(p["category"], []).append(p)
    for cat, items in sorted(by_cat.items()):
        print(f"  {cat}  — {items[0]['host']} ({items[0]['why']})")
        for p in items:
            print(f"      · {p['item']}")

    g = GOVERNING["traffic"]
    print(f"\nThe governing traffic law is {g['law']}, in force "
          f"{g['effective']}.\n  {g['url']}\n  {g['note']}")
    print("\nReplace the source_url on each row above with the regulator's "
          "own page.\nUntil then those rows should not become videos.\n")
    return 1


if __name__ == "__main__":
    if "--list" in sys.argv[1:]:
        print()
        for r in registry():
            print(f"  {r['tier']:<9} {r['domain']:<26} {r['authority']}")
            print(f"  {'':<9} {r['entry_url']}")
        print()
        raise SystemExit(0)
    raise SystemExit(report())
