"""
The curated price data, and the guards around it.

    python -m autoedits.cars           # health report
    python -m autoedits.cars tucson    # what the writer would see for a query

Two failure modes this file exists to prevent:

1. **Trim confusion.** "The Land Cruiser costs 239,900" is true of the base and
   wrong by 160,000 dirhams at the top of the range. Aggregator sites quote
   whichever trim they feel like. Rows carry price_from and price_to, and any
   row with a spread wide enough to mislead is labelled.

2. **Stale prices.** A price that was right in March and wrong in September is
   indistinguishable from a made-up one to the viewer who turns up at the
   dealer. Rows expire.

Rows marked CONFLICT are never handed to the writer at all.
"""

from __future__ import annotations

import csv
import math
import re
import sys
from functools import lru_cache
from datetime import date, datetime
from pathlib import Path

from .config import ROOT

CSV_PATH = ROOT / "data" / "cars.csv"
INSURANCE_PATH = ROOT / "data" / "insurance.csv"
OWNERSHIP_PATH = ROOT / "data" / "ownership.csv"
RULES_PATH = ROOT / "data" / "rules.csv"
HEAT_PATH = ROOT / "data" / "heat.csv"

# Cost and rule tables, in the order they should be considered. Everything
# here shares one schema (category, item, value_from, value_to, unit, basis)
# because none of it fits the brand/model shape that cars.csv has.
FACT_PATHS = (INSURANCE_PATH, OWNERSHIP_PATH, RULES_PATH, HEAT_PATH)

STALE_DAYS = 90          # after this, a row needs re-checking before use
WIDE_SPREAD = 0.35       # price_to > price_from * 1.35 → trim range worth naming


def load() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("model")]


def load_facts() -> list[dict]:
    """Costs and rules, which don't fit the brand/model shape at all.

    Three files, one schema:

    * insurance.csv  — the regulated premium tariff bands
    * ownership.csv  — registration, Salik, fuel; some rows expire monthly
    * rules.csv      — the law and the regulations, which barely move at all
    * heat.csv       — what 50-degree summers do to a car, and the tyre,
                       tint and child-safety rules that follow from it

    rules.csv is the useful one. A price is true until the next model year;
    "your insurer may not charge you more than AED 1,000 excess on a car worth
    AED 200,000" has been true since 2016 and will be true next year. Content
    built on it does not rot, which is the whole point of keeping it separate
    from the price files.
    """
    rows = []
    for path in FACT_PATHS:
        if path.exists():
            with open(path, newline="", encoding="utf-8") as fh:
                rows += [r for r in csv.DictReader(fh) if r.get("item")]
    return rows


def usable_facts() -> list[dict]:
    """load_facts() minus the legal claims nothing official stands behind.

    This is the gate. A tyre-age limit sourced to a newspaper is not evidence
    the pipeline may build a video on — not because the paper is careless, but
    because a paraphrase of a regulation is not the regulation, and the errors
    it introduces (a tier shifted, a penalty attached to the wrong band) are
    invisible downstream. Retrieval reads this; audits read load_facts(), so
    the excluded rows stay visible in `python -m autoedits.sources` instead of
    quietly disappearing from the file.
    """
    from .sources import LAW_CATEGORIES, ACCEPTABLE_FOR_LAW, tier_of

    keep = []
    for r in load_facts():
        if (r.get("category") or "").strip() in LAW_CATEGORIES \
                and tier_of(r.get("source_url", "")) not in ACCEPTABLE_FOR_LAW:
            continue
        keep.append(r)
    return keep


# Older name, kept because it reads better at some call sites.
load_insurance = load_facts


def _money(x: str) -> str:
    """Whole dirhams stay whole; fuel prices keep their fils.

    int() truncation turned AED 3.80 diesel into "AED 3", which is not a
    rounding nicety — it is a wrong number on screen.
    """
    try:
        f = float(x)
    except (TypeError, ValueError):
        return ""
    return f"{f:,.2f}".rstrip("0").rstrip(".") if f % 1 else f"{int(f):,}"


def _stem(w: str) -> str:
    """Fold a trailing plural. Applied to queries and to rows alike, so it only
    has to be *consistent*, not linguistically correct — "lexus" becoming
    "lexu" on both sides costs nothing.

    Without this, "how old can car tyres be" matched no row that says "tyre",
    and answered a question about the age limit with the fine instead.
    """
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _tokens(*parts: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", " ".join(parts).lower())}


def _fold(words) -> set[str]:
    return {_stem(w) for w in words}


def _phrase_in(lowered: str, phrase: str) -> bool:
    """Match a phrase on word boundaries.

    A plain `phrase in lowered` let the PHRASE_SEGMENTS key "ev" fire inside
    "r-ev-iew", so every "<model> uae review" query had `electric` injected
    into its terms and came back led by EVs. 56 queued topics did this.
    """
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) is not None


# Two-letter English words that also appear in model names. Rescuing short
# model codes must not resurrect these as search terms.
_SHORT_WORDS = _fold({"in", "on", "at", "to", "of", "it", "is", "be", "as",
                      "by", "or", "an", "my", "do", "up", "go", "no", "so",
                      "we", "he", "if", "us", "me", "ad"})


def _squash(text: str) -> str:
    """"CR-V" -> "crv". People type the model without its punctuation."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@lru_cache(maxsize=1)
def _model_vocab() -> frozenset[str]:
    """Short model codes that must survive the length filter.

    Terms shorter than three characters are dropped as noise, which quietly
    deleted the subject of any query naming a T1, X7, Q6, U5 — or the CR in
    CR-V. 160 rows in this file have such a token. A bare "3" from "BMW 3
    Series" stays excluded: it would match "top 3 cars in uae".
    """
    out = set()
    for row in load():
        for tok in _tokens(row.get("model", "")):
            if (len(tok) == 2 and any(c.isalpha() for c in tok)
                    and tok not in _SHORT_WORDS):
                out.add(tok)
    return frozenset(out)


def _value(lo: str, hi: str, unit: str) -> str:
    """Render a figure in its own unit.

    A cost table only ever held dirhams, so the old version prefixed AED onto
    everything. rules.csv holds black points, days, months and centimetres —
    "AED 4" for a seat-belt penalty is not a formatting wobble, it is a false
    statement on screen. Rows with unit `rule` carry no number at all: the
    fact is the sentence.
    """
    if not lo:
        return ""
    if unit == "percent":
        return f"{lo}%" + (f" to {hi}%" if hi else "")
    if "litre" in unit:
        return f"AED {_money(lo)} per litre"
    if unit.startswith("AED"):
        tail = unit[3:].strip()            # "AED per day" -> "per day"
        val = f"AED {_money(lo)}" + (f" to {_money(hi)}" if hi else "")
        return f"{val} {tail}".strip()
    if not unit:
        return f"AED {_money(lo)}" + (f" to {_money(hi)}" if hi else "")
    return f"{lo}" + (f" to {hi}" if hi else "") + f" {unit}"


def describe_fact(row: dict) -> str:
    val = _value(row.get("value_from", ""), row.get("value_to", ""),
                 row.get("unit", ""))
    bits = [f"{row['category']}: {row['item']}", val, row.get("basis", "")]
    if row.get("notes"):
        bits.append(row["notes"])
    bits.append(f"[source: {row.get('source_url','none')}, "
                f"checked {row.get('checked_on','?')}]")
    return " | ".join(b for b in bits if b)


describe_insurance = describe_fact


# Queries that should pull the cost and rule tables rather than car prices.
FACT_WORDS = _fold({
    "insurance", "insure", "insured", "premium", "premiums", "policy",
    "cover", "coverage", "comprehensive", "tpl", "third", "party", "claim",
    "claims", "deductible", "excess",
    # ownership and running costs
    "salik", "toll", "tolls", "registration", "register", "renew", "renewal",
    "fuel", "petrol", "diesel", "litre", "liter", "running", "ownership",
    "owning", "maintenance", "service", "servicing", "cost", "costs",
    "expensive", "fine", "fines", "rta",
    # "car expenses in dubai" is the single highest-demand phrase in the
    # queue — 105.5, ahead of everything — and it returned nothing, because
    # "expenses" was in none of these lists and "car" and "dubai" are both
    # stopwords. The question is answerable: registration, Salik, fuel and
    # insurance are four files of exactly this.
    "expense", "expenses", "upkeep", "spend", "spending",
    # the law and the regulations — the evergreen half of the channel
    # Words chosen to be *unambiguous*. "black" and "white" would route
    # "white car dubai" into the black-points table; "seat" would send every
    # 7-seater query to the insurance tariff, because PHRASE_SEGMENTS adds
    # that token itself. "points" and "belt" catch the same questions without
    # hijacking a shopping query.
    "law", "laws", "legal", "rule", "rules", "regulation", "fined",
    "penalty", "penalties", "points", "licence", "license", "impound",
    "impounded", "seized", "belt", "seatbelt", "child", "kids", "tint",
    "speeding", "signal", "accident", "write", "total", "loss",
    "depreciation", "excess", "loan", "finance", "financing", "instalment",
    "installment", "down", "payment", "salary", "bank", "claim", "claims",
    # heat, and the rules that exist because of it. "hot" is deliberately
    # absent — "hot hatch uae" is a shopping query, not a summer one.
    "heat", "summer", "temperature", "degrees", "tyre", "tyres", "tire",
    "tires", "tread", "worn", "pressure", "psi", "tint", "tinted", "tinting",
    "windscreen", "windshield", "battery", "batteries", "parked", "shade",
})

# Some questions are only recognisable as two words together. "limit", "front",
# "age" and "red" are far too generic to route on their own — "front wheel
# drive suv uae" is a shopping query — but "speed limit" and "front seat" are
# unambiguous. Phrases are checked against the raw query, not the token set.
FACT_PHRASES = {
    "front seat", "back seat", "age limit", "speed limit", "red light",
    "black point", "white point", "total loss", "write off", "written off",
    "seat belt", "seatbelt", "car seat", "child seat", "no claims",
    "down payment", "loan to value", "loss of use", "courtesy car",
    "tyre age", "tire age", "how hot", "how old", "in the sun",
    "left in the car", "left in a car", "window tint", "car tint",
    "tint limit", "tint percentage", "how much tint",
    "running cost", "cost of owning", "cost to own", "expenses", "expense",
}

# What a phrase is really asking about, in the vocabulary the files use.
# Nobody types "loss of use allowance"; they type "courtesy car".
PHRASE_TERMS = {
    "courtesy car": {"loss", "use", "allowance", "replacement"},
    "loss of use": {"loss", "use", "allowance"},
    "replacement car": {"loss", "use", "allowance", "replacement"},
    "total loss": {"total", "loss", "threshold"},
    "write off": {"total", "loss", "threshold"},
    "written off": {"total", "loss", "threshold"},
    "down payment": {"loan", "value"},
    "deposit": {"loan", "value"},
    "loan to value": {"loan", "value"},
    "how long": {"period", "term", "months"},
    "loan period": {"term", "months"},
    "loan term": {"term", "months"},
    "loan tenure": {"term", "months"},
    "front seat": {"front", "minimum"},
    "age limit": {"age", "minimum"},
    "speed limit": {"speeding"},
    "red light": {"red", "light", "signal"},
    "car seat": {"child", "safety", "seat"},
    "child seat": {"child", "safety", "seat"},
    "seat belt": {"belt"},
    "no claims": {"claims", "discount"},
    "impound": {"impound", "seized"},
    "excess": {"excess", "deductible"},
    "deductible": {"excess", "deductible"},
    "tyre age": {"age", "maximum", "years"},
    "tire age": {"age", "maximum", "years"},
    "how hot": {"temperature", "cabin", "parked", "degrees"},
    "in the sun": {"parked", "cabin", "temperature"},
    "left in the car": {"child", "alone"},
    "left in a car": {"child", "alone"},
    "window tint": {"tint"},
    "car tint": {"tint"},
    "tint limit": {"tint", "maximum"},
    "tint percentage": {"tint", "maximum"},
    "how much tint": {"tint", "maximum"},
    "expire": {"age", "maximum", "years"},
    # Nobody types "registration renewal and Salik tolls". They type
    # "expenses", and mean the whole running-cost picture.
    "expenses": {"registration", "renewal", "salik", "crossing", "fuel",
                 "petrol", "insurance", "premium", "inspection"},
    "expense": {"registration", "renewal", "salik", "crossing", "fuel",
                "petrol", "insurance", "premium", "inspection"},
    "running cost": {"registration", "renewal", "salik", "crossing", "fuel",
                     "petrol", "insurance", "premium", "inspection"},
    "cost of owning": {"registration", "renewal", "salik", "crossing",
                       "fuel", "petrol", "insurance", "premium"},
    "cost to own": {"registration", "renewal", "salik", "crossing",
                    "fuel", "petrol", "insurance", "premium"},
    "expiry": {"age", "maximum", "years"},
}

# Deciding WHICH FILE to look in is a different job from ranking inside it,
# and these words can do the first but not the second. Both sit in FACT_WORDS
# and in STOPWORDS, so testing the stopword-stripped term set meant they could
# never route anything: "is window tint legal in uae" and "total cost of
# owning a car in uae" both came back empty while rules.csv held the answer.
# They still may not score, because a word in half the rows ranks nothing.
#
# "fine" is the third word in both sets and is deliberately NOT here. Routing
# on it unlocks "traffic fine check online uae" and five more like it — but
# those ask how to USE the RTA portal, which no row in this project answers,
# and the writer handed a seat-belt fine instead produces a video whose title
# promises one thing and whose script says another. Leaving them uncovered
# gets them named in the nightly skip list, which is the honest outcome.
ROUTE_ONLY = _fold({"legal", "total"})

# Words that appear in almost every row and every query, and so tell you
# nothing about which row to return. Leaving them in was why "car impound
# rules in dubai" answered with a car loan: both rows contained "car".
STOPWORDS = _fold({"car", "cars", "uae", "dubai", "abu", "dhabi", "sharjah",
                   "emirates", "gcc", "the", "and", "for", "with", "your",
                   "you", "what", "how", "when", "does", "are", "buy",
                   "buying", "best", "legal", "can", "get", "much", "many",
                   # Quantifiers describe the SHAPE of a value, not its
                   # subject. In a corpus this small they score as rare words
                   # and hijack matches: "maximum tint" found "Maximum total
                   # repayments" on the strength of "maximum" alone.
                   "maximum", "minimum", "total", "typical", "average",
                   "per", "allowed", "permitted",
                   # "percent" was here and "percentage" was not, so
                   # "maximum tint percentage uae" came back led by
                   # "Percentage of vehicle market value" — the comprehensive
                   # insurance rate — instead of the tint limit.
                   "percentage", "proportion", "share", "rate", "ratio",
                   # Units of time are part of a value's shape too. Without
                   # these, "maximum tyre age years" matched "Parts
                   # depreciation in year 2" on the word "year" alone.
                   "year", "years", "day", "days", "month", "months",
                   "aed", "percent", "fine",
                   # Function words. Obvious in hindsight, and they were not
                   # here: "how old can car tyres be in uae" kept the tokens
                   # "be" and "in", which are rare enough in this corpus to
                   # score as DISTINCTIVE, and the topic queue then rejected
                   # it for resembling "Total Loss in UAE Cars" — on "in".
                   "be", "is", "was", "in", "on", "at", "of", "to", "a", "an",
                   "it", "its", "my", "do", "i", "vs", "or", "if", "from",
                   "that", "this", "they", "will", "have", "has", "any"})


def _idf() -> dict[str, float]:
    """How much a matched word is worth, by how rare it is in the data.

    "insurance" appears in half the rows and separates nothing; "depreciation"
    appears in six and identifies exactly what the viewer asked. Counting both
    as one point meant a question about depreciation was answered with the
    third-party liability cap, which is true, cited, and not the answer.
    """
    global _IDF
    if _IDF is None:
        rows = usable_facts()
        df: dict[str, int] = {}
        for r in rows:
            for w in _tokens(r.get("category", ""), r.get("item", ""),
                             r.get("basis", ""), r.get("notes", "")):
                df[w] = df.get(w, 0) + 1
        n = max(1, len(rows))
        _IDF = {w: math.log(1 + n / (1 + c)) for w, c in df.items()}
    return _IDF


_IDF: dict[str, float] | None = None

# Older name, kept for anything that imported it.
INSURANCE_WORDS = FACT_WORDS


def age_days(row: dict) -> int | None:
    try:
        return (date.today()
                - datetime.strptime(row["checked_on"], "%Y-%m-%d").date()).days
    except (ValueError, KeyError, TypeError):
        return None


def usable(row: dict) -> bool:
    """A row the writer is allowed to see.

    Rows may set their own `stale_days`. UAE fuel prices reset on the 1st of
    every month, so quoting September's diesel price in November is exactly as
    wrong as inventing it — those rows expire in 31 days. A registration fee
    barely moves in a year.
    """
    if (row.get("confidence") or "").upper().startswith("CONFLICT"):
        return False
    try:
        limit = int(row.get("stale_days") or STALE_DAYS)
    except ValueError:
        limit = STALE_DAYS
    age = age_days(row)
    return not (age is not None and age > limit)


def describe(row: dict) -> str:
    """One line of fact, phrased so the writer can't mistake a base price for
    the whole range."""
    lo, hi = row.get("price_from_aed"), row.get("price_to_aed")
    bits = [f"{row['brand']} {row['model']} {row['year']}",
            row.get("segment", ""), row.get("powertrain", "")]
    price = f"from AED {int(lo):,}" if lo else ""
    if lo and hi:
        spread = (int(hi) - int(lo)) / int(lo)
        price = f"AED {int(lo):,} to {int(hi):,} across trims"
        if spread > WIDE_SPREAD:
            price += " (WIDE trim range — say 'from' or name the trim)"
    bits.append(price)
    if row.get("notes"):
        bits.append(row["notes"])
    bits.append(f"[source: {row.get('source_url', 'none')}, "
                f"checked {row.get('checked_on', '?')}]")
    return " | ".join(b for b in bits if b)


CHEAP_WORDS = _fold({"cheap", "cheapest", "budget", "affordable", "value",
                     "under", "lowest", "entry"})

# "best first car in uae" is a price question wearing a different hat, and it
# matched nothing at all before: no brand, no model, no segment word in it.
CHEAP_PHRASES = {"first car", "starter car", "for students", "on a budget",
                 "new driver", "learner"}

# People don't search in the vocabulary a spec sheet uses. Someone typing
# "7 seater" will never match a row whose segment says "MPV", so a handful of
# phrase -> segment bridges do more for coverage than another fifty rows.
PHRASE_SEGMENTS = {
    "7 seater": {"mpv", "large", "full", "size", "seat"},
    "seven seater": {"mpv", "large", "full", "size", "seat"},
    "family": {"mpv", "large", "suv", "seat"},
    "first car": {"hatchback", "sedan", "compact"},
    "starter car": {"hatchback", "sedan", "compact"},
    "new driver": {"hatchback", "sedan", "compact"},
    "off road": {"large", "full", "size", "pickup"},
    "truck": {"pickup"},
    "ev": {"electric"},
    "electric": {"electric"},
    "hybrid": {"hybrid", "phev"},
    "plug in": {"phev"},
    "diesel": {"diesel"},
    "4x4": {"pickup", "large", "full"},
}


def facts_for(query: str, limit: int = 12) -> str:
    """Rows relevant to a search query, as text for the writer's prompt.

    Scoring is per-field rather than a flat word count: naming one model is
    enough to surface it, because a query like "rav4 worth it" contains exactly
    one word that appears anywhere in this file. Segment and powertrain matches
    score lower, so "cheapest electric suv uae" still returns a sensible set.
    """
    from .sources import tier_of

    lowered = query.lower()
    vocab = _model_vocab()

    # `direct` is what the viewer actually typed; `implied` is what a phrase
    # rule inferred from it. Scoring them alike is what put a MINI Cooper
    # ELECTRIC above the Jetour T1 on "jetour t1 uae review": the implied
    # term `electric` matched the MINI's model NAME. An implied term
    # describes a category, so it may only ever score against a category.
    direct = {w for w in _tokens(query)
              if (len(w) > 2 or w in vocab) and w not in STOPWORDS}
    implied: set[str] = set()
    for phrase, segs in PHRASE_SEGMENTS.items():
        if _phrase_in(lowered, phrase):
            implied |= _fold(segs)
    for phrase, extra in PHRASE_TERMS.items():
        if _phrase_in(lowered, phrase):
            implied |= _fold(extra)
    # STOPWORDS filters `direct`, but PHRASE_TERMS was putting the same words
    # straight back: "tint percentage" expands to {tint, maximum}, and
    # `maximum` then matched "Maximum total repayments", "Maximum loan to
    # value" and "Maximum in a calendar year" — so a tint question answered
    # with a car loan even though "maximum" had been blacklisted. A phrase
    # rule exists to add the SUBJECT a file uses, so the quantifiers it drags
    # along go the same way as the ones the viewer typed.
    implied -= STOPWORDS
    terms = direct | implied

    # The same constraints again, as GROUPS rather than a flat word set, for
    # the cheapest-first ranking below. A phrase rule expands to alternatives
    # — "7 seater" means mpv OR large OR full-size — so counting matched
    # WORDS rewards a Full Size SUV, which matches "full" and "size", over an
    # MPV, which matches "mpv", on a question where the two are equal. A
    # group is satisfied or it isn't.
    groups: list[frozenset[str]] = []
    for phrase, segs in PHRASE_SEGMENTS.items():
        if _phrase_in(lowered, phrase):
            groups.append(frozenset(_fold(segs) - STOPWORDS))
    for phrase, extra in PHRASE_TERMS.items():
        if _phrase_in(lowered, phrase):
            groups.append(frozenset(_fold(extra) - STOPWORDS))
    groups += [frozenset({w}) for w in direct]   # a typed word is its own group
    groups = [g for g in dict.fromkeys(groups) if g]
    if not terms:
        return ""

    wants_cheap = bool(terms & CHEAP_WORDS) or any(
        _phrase_in(lowered, ph) for ph in CHEAP_PHRASES)
    hits: list[tuple[int, int, int, str]] = []

    for row in load():
        if not usable(row):
            continue
        brand_tok = _tokens(row.get("brand", ""))
        # The squashed spelling joins the model's own tokens, so "crv",
        # "cr-v" and "cr v" all reach the same row.
        model_tok = _tokens(row.get("model", ""))
        squashed = _squash(row.get("model", ""))
        if len(squashed) > 2:
            model_tok = model_tok | {squashed}
        category = _tokens(row.get("segment", ""), row.get("powertrain", ""))

        score = 3 * len(direct & (brand_tok | model_tok)) \
            + len(terms & category)
        # Naming the brand AND the model is not a near-miss — it is the
        # subject of the video. Without this the T1 sat seventh in its own
        # query, behind six other Jetours ordered only by price.
        if (direct & brand_tok) and (direct & model_tok):
            score += 10
        if score:
            price = int(row.get("price_from_aed") or 0)
            # 0 sorts first: a manufacturer's own figure leads, everything
            # else follows.
            mfr = 0 if tier_of(row.get("source_url", "")) == "manufacturer" else 1
            met = sum(1 for g in groups if g & category)
            hits.append((score, mfr, price, describe(row), met))

    # A price-ranked question with nothing else in it scored zero against
    # every row, because "car", "cars", "best" and "which" are all stopwords
    # and the query names no brand, model or segment. Six of the fifty
    # highest-demand topics in the queue are this exact shape — "cheapest
    # cars in uae", "budget cars in uae", "best budget car in dubai",
    # "cheapest cars in dubai", "budget car in uae", "budget cars in uae" —
    # and every one of them returned nothing while this file held 465 rows
    # with prices in them.
    #
    # The guard matters as much as the fallback. It fires only when the cheap
    # words are ALL the query had to say: "cheapest ferrari in uae" keeps the
    # term `ferrari`, finds no row, and is left empty on purpose, because the
    # cheapest rows in this file are not an answer to that question.
    if not hits and wants_cheap and not (direct - CHEAP_WORDS):
        for row in load():
            price = int(row.get("price_from_aed") or 0)
            if not usable(row) or not price:
                continue
            mfr = 0 if tier_of(row.get("source_url", "")) == "manufacturer" else 1
            hits.append((1, mfr, price, describe(row), 0))

    # Best match first either way; price is the TIE-BREAK when the query asks
    # for cheap, not the primary key. Sorting on price first looked right and
    # was not: "cheapest electric suv in uae" came back led by four petrol
    # SUVs, because a row matching only `suv` at AED 50,000 outranked an
    # electric one at AED 79,900 — so the title promised electric and the
    # script read out petrol. Ranking by score first puts the rows that match
    # BOTH words on top, and sorts those by price, which is what the question
    # actually asked. Source tier breaks the remaining ties.
    hits.sort(key=lambda t: (-t[4], t[2], t[1]) if wants_cheap
              else (-t[0], t[1], t[2]))
    out = [t[3] for t in hits[:limit]]

    # Cost rows (insurance, registration, Salik, fuel) live in their own files
    # with their own shape. When the query is about running a car rather than
    # buying one, they lead — but they have to be RANKED, not just listed.
    # Taking them in file order meant "salik charges dubai" returned
    # third-party liability tables, because insurance.csv loads first.
    if (terms & FACT_WORDS) or (_tokens(query) & ROUTE_ONLY) or \
            any(_phrase_in(lowered, ph) for ph in FACT_PHRASES):
        scored = []
        for r in usable_facts():
            if not usable(r):
                continue
            # Weighted the same way car rows are, and for the same reason.
            # A flat word count let "dubai" appearing in a note tie with
            # "impound" appearing in the item name, so "car impound rules in
            # dubai" answered with the registration fee.
            name = _tokens(r.get("category", ""), r.get("item", ""))
            body = _tokens(r.get("basis", ""), r.get("notes", ""))
            idf = _idf()
            score = (3 * sum(idf.get(w, 1.0) for w in terms & name)
                     + sum(idf.get(w, 1.0) for w in terms & body))
            if score:
                scored.append((score, describe_fact(r)))
        scored.sort(key=lambda t: -t[0])
        cost = [text for _, text in scored[:limit]]
        out = cost + out[:max(0, limit - len(cost))] if cost else out
    return "\n".join(out)


def explain(query: str) -> str:
    """Why this query matched what it matched — or why it matched nothing.

    `facts_for` is four scoring rules, two vocabulary bridges and a stopword
    list, and when it returns nothing the only way to find out which of them
    dropped the query was to read it. This prints the working.
    """
    lowered = query.lower()
    vocab = _model_vocab()
    raw = _tokens(query)
    direct = {w for w in raw
              if (len(w) > 2 or w in vocab) and w not in STOPWORDS}
    dropped = raw - direct
    implied: set[str] = set()
    fired = []
    for table, name in ((PHRASE_SEGMENTS, "segment"), (PHRASE_TERMS, "term")):
        for phrase, extra in table.items():
            if _phrase_in(lowered, phrase):
                implied |= _fold(extra)
                fired.append(f"{phrase!r} -> {sorted(_fold(extra) - STOPWORDS)} ({name})")
    implied -= STOPWORDS

    cheap = bool((direct | implied) & CHEAP_WORDS) or any(
        _phrase_in(lowered, ph) for ph in CHEAP_PHRASES)
    facts = bool(((direct | implied) & FACT_WORDS) or (raw & ROUTE_ONLY)
                 or any(_phrase_in(lowered, ph) for ph in FACT_PHRASES))

    out = [f"query      {query!r}",
           f"searching  {sorted(direct) or '(nothing — see dropped)'}",
           f"dropped    {sorted(dropped)}  (too common or too short to rank on)"]
    if fired:
        out.append("bridges    " + "\n           ".join(fired))
    else:
        out.append("bridges    none fired")
    out.append(f"ranking    {'cheapest first' if cheap else 'best match first'}")
    out.append(f"files      cars.csv" + (" + the cost and law files" if facts else " only"))

    rows = facts_for(query)
    n = len(rows.splitlines()) if rows else 0
    out.append(f"result     {n} row(s)")
    if not n:
        out.append("")
        out.append("Nothing matched. Either no row uses these words, or every")
        out.append("word that could have matched is in STOPWORDS — the list of")
        out.append("words too common to rank on. The `searching` line above is")
        out.append("what the scorer actually had to work with.")
    return "\n".join(out)


def known_source_urls() -> set[str]:
    """Every source URL you have personally put in cars.csv.

    This is the whitelist. A model asked to cite its figures will invent
    citations that look entirely correct — "https://www.rta.ae/insurance-costs"
    has a real domain, a plausible path, and does not exist. Checking that a
    citation *is* a URL catches nothing; checking that it is a URL **you
    already vouched for** catches everything.

    The consequence is deliberate: the pipeline can only make videos about
    subjects you have curated data for. Insurance topics stay blocked until
    there are insurance rows in the file.
    """
    return {row["source_url"].strip()
            for row in load() + usable_facts()
            if row.get("source_url", "").strip()}


# Minimum IDF-weighted overlap between the citation context and the candidate
# row before a numeric match counts as a trace. Raw word counts do not work:
# "car" and "maximum" appear everywhere and carry no information, so a single
# generic hit would let any number claim any row's source. Rare words clear
# this floor on their own; common ones cannot.
MIN_CONTEXT_OVERLAP = 3.0


def source_for(value, context: str = "") -> str | None:
    """Trace a number back to the row it came from.

    The writer is told to cite its figures, but a small local model forgets.
    Rather than bin the script for that, we check whether the number actually
    matches something in your data — if it does, the citation is ours to supply
    and the model's compliance stops mattering. A figure that matches nothing
    still has no source, which is exactly the case worth blocking.

    `context` is the surrounding label ("Nissan Patrol, starting price"), used
    to break ties. It matters more than it sounds: the Patrol and the Land
    Cruiser both start at AED 239,900, so matching on price alone will happily
    cite the wrong car.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    ctx = set(re.findall(r"[a-z0-9]+", context.lower()))
    # Compared against the fact rows below after stopword removal — _tokens
    # keeps every word for other callers, so the filtering happens here.
    fact_ctx = _tokens(context) - STOPWORDS
    best, best_score = None, -1

    for row in load():
        if not usable(row):
            continue
        matched = any(
            raw and abs(float(raw) - v) < 1
            for key in ("price_from_aed", "price_to_aed")
            for raw in [row.get(key)]
            if raw and raw.replace(".", "", 1).isdigit()
        )
        if not matched:
            continue

        identity = _tokens(row.get("brand", ""), row.get("model", ""))
        score = len(ctx & identity)
        if score > best_score:
            best, best_score = row, score

    if best is not None:
        return (f"{best['brand']} {best['model']} — {best['source_url']} "
                f"(checked {best['checked_on']})")

    # Not a car price — try the cost and rule tables, the other place a number
    # in a script can legitimately have come from. Context decides here too,
    # and it matters more than in cars.csv: 400 is the seat-belt fine, the
    # phone fine and the child-seat fine, and citing the wrong one is a
    # mistake a viewer will catch.
    best, best_score = None, -1
    for row in usable_facts():
        if not usable(row):
            continue
        matched = False
        for key in ("value_from", "value_to"):
            raw = row.get(key)
            if not raw:
                continue
            try:
                matched = matched or abs(float(raw) - v) < 0.01
            except ValueError:
                continue
        if not matched:
            continue
        # Weight by rarity, and weight the item twice. Counting raw overlap
        # made "maximum tint private cars percent" match "Maximum total
        # repayments" on the word "maximum", and let an incidental word in a
        # notes field outrank the row's own name.
        idf = _idf()
        # Identity is the item AND its category — "After 3 claim-free years"
        # is only identifiable as a no-claims figure via the category. Basis
        # and notes are prose and stay out of it.
        item_tok = _tokens(row.get("item", ""),
                           row.get("category", "")) - STOPWORDS
        rest_tok = _tokens(row.get("basis", ""), row.get("notes", "")) - STOPWORDS
        # The row's own NAME must be part of why it matched. A hit that comes
        # only from a category or a notes field is coincidence: "maximum tint
        # ... percent" reached "Maximum total repayments" through the word
        # percent sitting in its notes, and cited a loan cap as a tint law.
        if not (fact_ctx & item_tok):
            continue
        score = sum(idf.get(w, 1.0) * 2 for w in fact_ctx & item_tok) \
            + sum(idf.get(w, 1.0) for w in fact_ctx & (rest_tok - item_tok))
        if score > best_score:
            best, best_score = row, score

    # A bare numeric match is not evidence. Without this floor, a figure whose
    # own row is missing — withheld by the source gate, or never in the file —
    # silently binds to whatever unrelated row happens to share the number: a
    # five-year tyre age cites a depreciation table, a 50% tint limit cites a
    # loan cap. That is a worse failure than no citation, because it reads as
    # sourced. Demand that the context and the row have something in common.
    if best is not None and best_score >= MIN_CONTEXT_OVERLAP:
        return (f"{best['category']}: {best['item']} — "
                f"{best['source_url']} (checked {best['checked_on']})")
    return None


def report() -> int:
    rows = load()
    if not rows:
        print(f"No data at {CSV_PATH}")
        return 1

    conflicts = [r for r in rows
                 if (r.get("confidence") or "").upper().startswith("CONFLICT")]
    stale = [r for r in rows
             if (a := age_days(r)) is not None and a > STALE_DAYS]
    single = [r for r in rows if r.get("confidence") == "single-source"]
    checked = [r for r in rows if r.get("confidence") == "cross-checked"]
    no_source = [r for r in rows if not r.get("source_url")]

    facts = usable_facts()
    fresh = sum(1 for r in facts if usable(r))
    print(f"\n{len(rows)} rows in {CSV_PATH.name}"
          f"  +  {len(facts)} cost/rule rows ({fresh} in date)")
    for path in FACT_PATHS:
        if path.exists():
            with open(path, newline="", encoding="utf-8") as fh:
                n = sum(1 for r in csv.DictReader(fh) if r.get("item"))
            print(f"      {path.name:<16} {n:>4} rows")
    print(f"  cross-checked (2+ sources agree) : {len(checked)}")
    print(f"  single-source                    : {len(single)}")
    print(f"  CONFLICT (withheld from writer)  : {len(conflicts)}")
    print(f"  stale (>{STALE_DAYS}d, withheld)         : {len(stale)}")
    print(f"  missing a source url             : {len(no_source)}")
    print(f"  → {sum(1 for r in rows if usable(r))} usable")

    if conflicts:
        print("\nConflicts to resolve — check the manufacturer's UAE site:")
        for r in conflicts:
            print(f"  · {r['brand']} {r['model']}: {r['notes']}")

    if stale:
        print(f"\nStale, re-check before these can be used again:")
        for r in stale[:10]:
            print(f"  · {r['brand']} {r['model']} (checked {r['checked_on']})")

    print()
    return 0


if __name__ == "__main__":
    if "--why" in sys.argv:
        q = " ".join(a for a in sys.argv[1:] if a != "--why")
        if not q:
            print('Give it a query: python -m autoedits.cars --why "cheap suv uae"')
            raise SystemExit(2)
        print()
        print(explain(q))
        print()
        raise SystemExit(0)
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"\nWhat the writer sees for {query!r}:\n")
        print(facts_for(query) or "  (nothing matched)")
        print()
    else:
        raise SystemExit(report())
