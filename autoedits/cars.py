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
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import ROOT

CSV_PATH = ROOT / "data" / "cars.csv"
INSURANCE_PATH = ROOT / "data" / "insurance.csv"
OWNERSHIP_PATH = ROOT / "data" / "ownership.csv"
RULES_PATH = ROOT / "data" / "rules.csv"
HEAT_PATH = ROOT / "data" / "heat.csv"
BIKES_PATH = ROOT / "data" / "bikes.csv"
BIKE_RULES_PATH = ROOT / "data" / "bike_rules.csv"

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


def load_bikes() -> list[dict]:
    """Motorcycle prices. Same price columns as cars.csv, plus engine_cc.

    Kept in their own file and their own retrieval pool. A car query handed a
    Sharmax at 4,990 would call it "the cheapest car in the UAE"; a bike query
    handed a Kia would read a car price out as a motorcycle's. Neither file
    ever answers the other's questions.
    """
    if not BIKES_PATH.exists():
        return []
    with open(BIKES_PATH, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("model")]


def _read_facts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("item")]


# Car-file rows a motorcycle question may also use: fuel costs the same per
# litre whatever burns it. Everything else shared is picked up by the word
# "motorcycle" in the row (the TPL bands, the 200 AED registration fee).
BIKE_SHARED_CATEGORIES = {"Fuel price"}


def load_facts(pool: str = "car") -> list[dict]:
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

    `pool` picks the audience: "car" (the four files above), "bike"
    (bike_rules.csv plus the car-file rows that are about motorcycles), or
    "all" for audits and citation tracing.
    """
    rows = []
    for path in FACT_PATHS:
        rows += _read_facts(path)
    if pool == "car":
        return rows
    bike = _read_facts(BIKE_RULES_PATH)
    if pool == "all":
        return rows + bike
    shared = [r for r in rows
              if "motorcycle" in " ".join((r.get("category", ""), r.get("item", ""),
                                           r.get("basis", ""), r.get("notes", ""))).lower()
              or r.get("category", "") in BIKE_SHARED_CATEGORIES]
    return bike + shared


def usable_facts(pool: str = "car") -> list[dict]:
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
    for r in load_facts(pool):
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
    # Fils are always two digits: "6,152.5" reads as a typo for 6,152.50.
    return f"{f:,.2f}" if f % 1 else f"{int(f):,}"


def _stem(w: str) -> str:
    """Fold a trailing plural. Applied to queries and to rows alike, so it only
    has to be *consistent*, not linguistically correct — "lexus" becoming
    "lexu" on both sides costs nothing.

    Without this, "how old can car tyres be" matched no row that says "tyre",
    and answered a question about the age limit with the fine instead.
    """
    w = w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
    return _SPELLING.get(w, w)


# American spellings the files never use. "motorcycle license cost dubai"
# matched no row, because every licence row says "licence".
_SPELLING = {"license": "licence", "tire": "tyre", "liter": "litre"}


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


@lru_cache(maxsize=2)
def _model_vocab(bike: bool = False) -> frozenset[str]:
    """Short model codes that must survive the length filter.

    Terms shorter than three characters are dropped as noise, which quietly
    deleted the subject of any query naming a T1, X7, Q6, U5 — or the CR in
    CR-V. 160 rows in this file have such a token. A bare "3" from "BMW 3
    Series" stays excluded: it would match "top 3 cars in uae".
    """
    out = set()
    for row in (load_bikes() if bike else load()):
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

# Words that say what KIND of car, not WHICH car. They may score against a
# row's segment and powertrain, never against its brand or model name.
#
# "electric car in dubai in kannada" led with a MINI Cooper Electric at
# 235,000 and a Porsche Macan Electric at 310,300, because "electric" counted
# three times over against those model NAMES. The 74,900 and 79,900 EVs never
# made the twelve rows at all, the writer called the cheapest car it was
# handed "the cheapest electric car in Dubai", and the draft said 109,900 when
# seven EVs in this file cost less. "ev" did the same through "Captiva EV",
# "Qin Plus EV" and "Hummer EV". A model name that contains its own
# powertrain is restating the category, not identifying the car.
CATEGORY_WORDS = _fold({
    "electric", "ev", "evs", "hybrid", "hybrids", "phev", "diesel", "petrol",
    "suv", "suvs", "sedan", "sedans", "hatchback", "hatchbacks", "coupe",
    "convertible", "pickup", "pickups", "mpv", "van", "crossover", "wagon",
})

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
                   "that", "this", "they", "will", "have", "has", "any",
                   # Say WHICH pool to search, then nothing. "motorcycle" is
                   # in nearly every bike rule; left in, it outranks the
                   # word the viewer actually asked about.
                   "bike", "bikes", "motorbike", "motorbikes", "motorcycle",
                   "motorcycles", "motorcyclist", "motorcyclists", "biker",
                   "bikers"})


def _idf(pool: str = "car") -> dict[str, float]:
    """How much a matched word is worth, by how rare it is in the data.

    "insurance" appears in half the rows and separates nothing; "depreciation"
    appears in six and identifies exactly what the viewer asked. Counting both
    as one point meant a question about depreciation was answered with the
    third-party liability cap, which is true, cited, and not the answer.
    """
    if pool not in _IDF:
        rows = usable_facts(pool)
        df: dict[str, int] = {}
        for r in rows:
            for w in _tokens(r.get("category", ""), r.get("item", ""),
                             r.get("basis", ""), r.get("notes", "")):
                df[w] = df.get(w, 0) + 1
        n = max(1, len(rows))
        _IDF[pool] = {w: math.log(1 + n / (1 + c)) for w, c in df.items()}
    return _IDF[pool]


# One table per pool: "motorcycle" is in nearly every bike rule and almost no
# car rule, so a shared table would score it as rare on exactly the queries
# where it separates nothing.
_IDF: dict[str, dict[str, float]] = {}

# Older name, kept for anything that imported it.
INSURANCE_WORDS = FACT_WORDS


def age_days(row: dict) -> int | None:
    try:
        return (date.today()
                - datetime.strptime(row["checked_on"], "%Y-%m-%d").date()).days
    except (ValueError, KeyError, TypeError):
        return None


_MONTHS = {m: i for i, m in enumerate(
    ("january february march april may june july august september october "
     "november december").split(), 1)}


def for_month(row: dict) -> tuple[int, int] | None:
    """(year, month) when a row's basis is a single month, like "October 2026"."""
    m = re.fullmatch(r"([A-Za-z]+) (\d{4})", (row.get("basis") or "").strip())
    if m and m.group(1).lower() in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1).lower()]
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
    month = for_month(row)
    if month is not None and month != (date.today().year, date.today().month):
        # A price set for one month is wrong on the 1st of the next,
        # however recently it was checked. Age alone let September's fuel
        # prices through until 8 October.
        return False
    try:
        limit = int(row.get("stale_days") or STALE_DAYS)
    except ValueError:
        limit = STALE_DAYS
    age = age_days(row)
    return not (age is not None and age > limit)


def expires_on(row: dict) -> date | None:
    """The first day a row is no longer handed to the writer."""
    month = for_month(row)
    if month is not None:
        y, m = month
        return date(y + (m == 12), m % 12 + 1, 1)
    try:
        checked = datetime.strptime(row["checked_on"], "%Y-%m-%d").date()
        limit = int(row.get("stale_days") or STALE_DAYS)
    except (ValueError, KeyError, TypeError):
        return None
    return checked + timedelta(days=limit + 1)


def expiring(within_days: int = 21) -> list[tuple[date, str, dict]]:
    """(expiry date, file, row) for usable rows that expire soon, earliest first.

    Most rows were gathered in sweeps, so they expire in blocks: on 25 Jan 2027
    the buildable queue drops from 165 topics to 41 unless the October rows
    are re-checked first. This is the warning, three weeks ahead.
    """
    today = date.today()
    out = []
    for name, rows in (("cars.csv", load()), ("bikes.csv", load_bikes()),
                       ("facts", usable_facts("all"))):
        for r in rows:
            if not usable(r):
                continue
            d = expires_on(r)
            if d is not None and (d - today).days <= within_days:
                out.append((d, name, r))
    return sorted(out, key=lambda x: x[0])


def expiry_warning(within_days: int = 21) -> str | None:
    soon = expiring(within_days)
    if not soon:
        return None
    by: dict[str, int] = {}
    for _, name, _ in soon:
        by[name] = by.get(name, 0) + 1
    first = soon[0][0]
    return (f"{len(soon)} rows expire by {soon[-1][0]:%d %b} (first on {first:%d %b}): "
            + ", ".join(f"{n} in {f}" for f, n in by.items())
            + ". Re-check them and update checked_on, or the topics they back "
              "stop being buildable."
            + (" Monthly prices (fuel) need next month's figures: wam.ae "
               "publishes them on the last day of the month."
               if any(for_month(r) for _, _, r in soon) else ""))


def describe(row: dict) -> str:
    """One line of fact, phrased so the writer can't mistake a base price for
    the whole range."""
    lo, hi = row.get("price_from_aed"), row.get("price_to_aed")
    segment = row.get("segment", "")
    if "engine_cc" in row:
        # Say what it is: "naked" alone reads as nothing to the writer.
        segment = {"scooter": "scooter", "trike": "three-wheel trike"}.get(
            segment, f"{segment} motorcycle".strip())
    bits = [f"{row['brand']} {row['model']} {row.get('year', '')}".strip(),
            segment, row.get("powertrain", "")]
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


NEW_CAR_WORDS = _fold({"new", "latest", "price", "prices", "pricing", "cost",
                       "model", "models"})

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


# ------------------------------------------------------------- motorcycles --
#
# Which pool a query searches is decided by its vocabulary, before any
# scoring. Words that can only mean a motorcycle route it; nothing else does.
BIKE_WORDS = _fold({
    "bike", "bikes", "motorbike", "motorbikes", "motorcycle", "motorcycles",
    "motorcyclist", "motorcyclists", "biker", "bikers", "scooter", "scooters",
    "moped", "mopeds", "superbike", "superbikes", "pillion", "helmet",
    "helmets", "motocross",
})
BIKE_PHRASES = {"delivery rider", "delivery riders", "two wheeler",
                "two-wheeler", "dirt bike", "quad bike", "gold wing",
                "africa twin", "x-adv"}

# Brands with no cars in this project. Brands that make both (Honda, BMW,
# Suzuki) route only with a bike word or a bike model name — "honda price uae"
# is a car question until it says otherwise. Many of these publish no UAE
# prices at all (data/sources.csv says which); routing them still matters, so
# "cheapest yamaha bike" finds nothing instead of finding a Yaris.
BIKE_BRANDS = _fold({
    "sharmax", "ducati", "enfield", "cfmoto", "yamaha", "kawasaki", "ktm",
    "harley", "davidson", "triumph", "aprilia", "vespa", "husqvarna",
    "benelli", "agusta", "bajaj", "tvs", "zontes", "voge", "kymco", "gasgas",
})
# Model names distinctive enough to route alone. A bike model that shares a
# word with a car ("Continental GT", "Sport", "Classic") must not.
BIKE_MODEL_WORDS = _fold({
    "panigale", "multistrada", "diavel", "xdiavel", "hypermotard",
    "streetfighter", "desertx", "scrambler", "fireblade", "goldwing",
    "himalayan", "interceptor", "hayabusa", "ninja", "xadv",
})

# Micromobility is not motorcycling. "e scooter rules dubai" is about rental
# kick-scooters and cycle tracks; handing it motorcycle fines would produce a
# confidently wrong video, so these find nothing at all.
NOT_MOTORCYCLE = ("bicycle", "bicycles", "cycling", "cyclist", "cycle track",
                  "ebike", "e bike", "e-bike", "e scooter", "e-scooter",
                  "escooter", "electric scooter", "kick scooter",
                  "bike rack", "bike carrier", "mountain bike")

# What KIND of bike, never WHICH bike — scored against segment only.
BIKE_CATEGORY_WORDS = _fold({
    "scooter", "scooters", "naked", "cruiser", "cruisers", "sport", "sports",
    "touring", "tourer", "adventure", "adv", "classic", "retro", "commuter",
    "trike", "superbike", "superbikes", "supermoto", "enduro", "dirt",
    "offroad", "motocross",
})
BIKE_PHRASE_SEGMENTS = {
    "off road": {"off", "road"}, "off-road": {"off", "road"},
    "offroad": {"off", "road"}, "dirt": {"off", "road"},
    "enduro": {"off", "road"}, "motocross": {"off", "road"},
    "superbike": {"sport"}, "sports bike": {"sport"},
    "sport bike": {"sport"}, "retro": {"classic"}, "cafe racer": {"classic"},
    "tourer": {"touring"}, "adv": {"adventure"},
}
# Off-road bikes cannot be registered for the road, and a pit bike at 3,590
# is not "the cheapest motorcycle in the UAE" in any sense a buyer means. They
# appear only when the query asks for them.
OFFROAD_PHRASES = ("off road", "off-road", "offroad", "dirt", "enduro",
                   "motocross", "pit bike", "pitbike", "trail", "mx")
BIKE_CHEAP_PHRASES = {"first bike", "beginner bike", "for beginners",
                      "for beginner", "learner", "on a budget",
                      "for delivery"}
BIKE_FACT_WORDS = _fold({
    "helmet", "helmets", "pillion", "passenger", "course", "courses",
    "training", "lesson", "lessons", "test", "school", "lane", "lanes",
    "delivery", "gear", "glove", "gloves", "jacket", "noise", "noisy", "loud",
    "exhaust", "modified", "modification", "stunt", "stunts", "wheelie",
    "quad", "atv", "headlight", "lights", "fee", "fees", "permit", "age",
})
BIKE_FACT_PHRASES = {"red light", "eye test", "road test", "traffic file",
                     "learning permit", "how to get", "get a licence",
                     "get a license"}
# What a licence-cost question means in the files' own vocabulary. Only
# multi-word phrases: a bare "cost" or "price" must not drag twelve course
# fee rows in front of a question about what a CB300R costs.
BIKE_PHRASE_TERMS = {
    "licence cost": {"fee", "course"}, "license cost": {"fee", "course"},
    "licence fee": {"fee", "course"}, "license fee": {"fee", "course"},
    "licence price": {"fee", "course"}, "license price": {"fee", "course"},
    "course fee": {"fee", "course"}, "course cost": {"fee", "course"},
    "training cost": {"fee", "course"}, "how to get": {"step"},
    "get a licence": {"step"}, "get a license": {"step"},
    "age limit": {"age"}, "loud exhaust": {"noisy", "exhaust"},
    "red light": {"red", "light"},
    # The motorcycle premium bands are filed as "Third-party liability" and
    # never use the word insurance, so "motorcycle insurance cost in uae"
    # found only the no-insurance FINE and led with that.
    "insurance": {"third", "party", "liability"},
}


@lru_cache(maxsize=1)
def _bike_identity_words() -> frozenset[str]:
    """Bike model codes no car shares: "cb300r", "450sr", "crf450r".

    Only tokens with a digit and a letter, so "Classic 350" contributes
    nothing and "350" never routes a car query.
    """
    car = set()
    for r in load():
        car |= _tokens(r.get("brand", ""), r.get("model", ""))
    out = set()
    for r in load_bikes():
        for tok in _tokens(r.get("model", "")):
            if (len(tok) >= 4 and re.search(r"\d", tok)
                    and re.search(r"[a-z]", tok) and tok not in car):
                out.add(tok)
    return frozenset(out)


def is_bike_query(query: str) -> bool:
    lowered = f" {query.lower()} "
    raw = _tokens(query)
    return bool(raw & BIKE_WORDS or raw & BIKE_BRANDS or raw & BIKE_MODEL_WORDS
                or raw & _bike_identity_words()
                or any(_phrase_in(lowered, ph) for ph in BIKE_PHRASES)
                or any(_phrase_in(lowered, ph.strip()) for ph in NOT_MOTORCYCLE))


def not_motorcycle(query: str) -> bool:
    lowered = query.lower()
    return any(_phrase_in(lowered, ph) for ph in NOT_MOTORCYCLE)


def wants_offroad(query: str) -> bool:
    # Word boundaries: "trail" must not fire inside "trailer".
    lowered = query.lower()
    return any(_phrase_in(lowered, ph) for ph in OFFROAD_PHRASES)


def road_bike(row: dict) -> bool:
    return "off" not in _tokens(row.get("segment", ""))


# Words that may follow a brand without naming a model: "byd price in uae",
# "toyota 2026 lineup". Anything else in that slot is taken as a model name.
AFTER_BRAND_OK = _fold({
    "price", "prices", "pricing", "cost", "review", "reviews", "new", "used",
    "model", "models", "lineup", "range", "offer", "offers", "deal", "deals",
    "dealer", "dealers", "showroom", "spec", "specs", "latest", "all",
    "vs", "or", "and", "versus", "truck", "trucks",
})


def missing_model(query: str, rows: list[dict]) -> str | None:
    """The model a query names that no row in its pool has, or None.

    "byd seagull uae" matched on the brand alone, so the writer was handed a
    page of OTHER BYDs under a Seagull title. Draft #134 went out as "BYD
    Seagull price in UAE" and never said what a Seagull costs. The word
    straight after a brand is the model slot; when it holds a word none of
    that brand's... none of this pool's models use, the query is about a car
    this project has no data for, and the honest answer is nothing.

    Measured on the 1,499-topic queue before adding it: the only words in
    that slot that are neither a model nor generic were "leopard" (3 topics)
    and "yangwang" (1) — both BYD models with no rows.
    """
    brands, models = set(), set()
    for r in rows:
        brands |= set(re.findall(r"[a-z0-9]+", r.get("brand", "").lower()))
        models |= _tokens(r.get("model", "")) | {_squash(r.get("model", ""))}
    words = re.findall(r"[a-z0-9]+", query.lower())
    for here, nxt in zip(words, words[1:]):
        if here not in brands or nxt in brands:
            continue
        w = _stem(nxt)
        if (w in models or w in STOPWORDS or w in AFTER_BRAND_OK
                or w in CATEGORY_WORDS or w in BIKE_CATEGORY_WORDS
                or w in FACT_WORDS or w in CHEAP_WORDS
                or re.fullmatch(r"(19|20)\d\d", w)):
            continue
        return nxt
    return None


# Words a viewer uses to ask, not to name a subject. They appear in no row
# and should not count against a phrase.
INTENT_WORDS = _fold({
    "which", "cheap", "price", "prices", "cost", "costs", "review", "new",
    "used", "family", "first", "worth", "good", "top", "budget", "affordable",
    "expensive", "luxury", "fast", "reliable", "compare", "comparison",
    "difference", "between", "list", "model", "models", "near", "me",
    "should", "need", "rules", "rule", "law", "laws", "guide", "explained",
    "food",
})


@lru_cache(maxsize=2)
def _subject_vocab(pool: str) -> frozenset[str]:
    """Every word that names something in this pool's data.

    Names only: brand, model, segment, powertrain, and a fact's category,
    item and basis. The free-text notes are left out on purpose, because they
    mention markets, governments and websites in passing, and a phrase about
    one of those is still not something the data can answer.
    """
    v: set[str] = set()
    for r in (load_bikes() if pool == "bike" else load()):
        v |= _tokens(r.get("brand", ""), r.get("model", ""),
                     r.get("segment", ""), r.get("powertrain", ""))
    for r in usable_facts(pool):
        v |= _tokens(r.get("category", ""), r.get("item", ""),
                     r.get("basis", ""))
    return frozenset(v)


def junk_reason(query: str) -> str | None:
    """Why a harvested phrase should not become a video, or None.

    The harvester asks autocomplete for "<seed> a" ... "<seed> z", so it
    collects the seed plus whatever word people type next: "car insurance uae
    login", "best family car in uae kannada", "car maintenance cost dubai
    airlines", "car tyres uae uae". Each still has data, because the seed
    matches, so the rows say nothing about the word that made it a different
    question. Once the queue window was fixed (28 Oct) these were most of what
    the nightly run would pick.

    The rule: every word must be one the data names, a word for asking, or a
    stopword. On the queue that day it kept 168 of 495 buildable topics, and
    the 327 it skipped were languages, countries, "vlog", "yacht", "app" and
    the like. Topics you add by hand or list as evergreen are not filtered.
    """
    words = re.findall(r"[a-z0-9]+", query.lower())
    for a, b in zip(words, words[1:]):
        if a == b:
            return f"repeats the word {a!r}"
    pool = "bike" if is_bike_query(query) else "car"
    vocab = _subject_vocab(pool)
    unknown = [w for w in words
               if not re.fullmatch(r"\d+", w)
               and (t := _stem(w)) not in vocab
               and t not in STOPWORDS and t not in CATEGORY_WORDS
               and t not in FACT_WORDS and t not in AFTER_BRAND_OK
               and t not in CHEAP_WORDS and t not in BIKE_CATEGORY_WORDS
               and t not in INTENT_WORDS]
    if unknown:
        return f"the data says nothing about {', '.join(repr(w) for w in unknown)}"
    return None


def facts_for(query: str, limit: int = 12) -> str:
    """Rows relevant to a search query, as text for the writer's prompt.

    Scoring is per-field rather than a flat word count: naming one model is
    enough to surface it, because a query like "rav4 worth it" contains exactly
    one word that appears anywhere in this file. Segment and powertrain matches
    score lower, so "cheapest electric suv uae" still returns a sensible set.
    """
    from .sources import tier_of

    lowered = query.lower()
    bike = is_bike_query(query)
    if bike and not_motorcycle(query):
        return ""
    vocab = _model_vocab(bike)
    pool = "bike" if bike else "car"
    seg_table = BIKE_PHRASE_SEGMENTS if bike else PHRASE_SEGMENTS
    term_table = {**PHRASE_TERMS, **BIKE_PHRASE_TERMS} if bike else PHRASE_TERMS
    cheap_phrases = CHEAP_PHRASES | BIKE_CHEAP_PHRASES if bike else CHEAP_PHRASES
    category_words = CATEGORY_WORDS | BIKE_CATEGORY_WORDS if bike else CATEGORY_WORDS
    fact_words = FACT_WORDS | BIKE_FACT_WORDS if bike else FACT_WORDS
    fact_phrases = FACT_PHRASES | BIKE_FACT_PHRASES if bike else FACT_PHRASES
    rows = load_bikes() if bike else load()
    if missing_model(query, rows):
        return ""
    if bike and not wants_offroad(query):
        rows = [r for r in rows if road_bike(r)]

    # `direct` is what the viewer actually typed; `implied` is what a phrase
    # rule inferred from it. Scoring them alike is what put a MINI Cooper
    # ELECTRIC above the Jetour T1 on "jetour t1 uae review": the implied
    # term `electric` matched the MINI's model NAME. An implied term
    # describes a category, so it may only ever score against a category.
    direct = {w for w in _tokens(query)
              if (len(w) > 2 or w in vocab) and w not in STOPWORDS}
    implied: set[str] = set()
    for phrase, segs in seg_table.items():
        if _phrase_in(lowered, phrase):
            implied |= _fold(segs)
    for phrase, extra in term_table.items():
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
    for phrase, segs in seg_table.items():
        if _phrase_in(lowered, phrase):
            groups.append(frozenset(_fold(segs) - STOPWORDS))
    for phrase, extra in term_table.items():
        if _phrase_in(lowered, phrase):
            groups.append(frozenset(_fold(extra) - STOPWORDS))
    groups += [frozenset({w}) for w in direct]   # a typed word is its own group
    groups = [g for g in dict.fromkeys(groups) if g]
    if not terms:
        return ""

    wants_cheap = bool(terms & CHEAP_WORDS) or any(
        _phrase_in(lowered, ph) for ph in cheap_phrases)
    identity = direct - category_words
    named = False                 # did the query pick out any brand or model?
    hits: list[tuple[int, int, int, str]] = []

    for row in rows:
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

        matched = identity & (brand_tok | model_tok)
        named = named or bool(matched)
        # Once the query HAS named a family, a category word in a model name
        # stops restating the category and starts telling variants apart:
        # "land cruiser hybrid" must still lead with the Land Cruiser Hybrid,
        # not the FJ. So it counts — but only on top of a real identity
        # match, never in place of one.
        if matched:
            matched = matched | (direct & category_words & model_tok)
        score = 3 * len(matched) + len(terms & category)
        # Naming the brand AND the model is not a near-miss — it is the
        # subject of the video. Without this the T1 sat seventh in its own
        # query, behind six other Jetours ordered only by price.
        if (identity & brand_tok) and (identity & model_tok):
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
    #
    # Every row is a new car, so "new", a model year or "price" adds nothing
    # to a cheap question. "cheapest new car in uae" found nothing until
    # 29 Oct because "new" counted as something more to say. "used" is not
    # neutral: no row is a used car.
    leftover = {w for w in direct - CHEAP_WORDS
                if w not in NEW_CAR_WORDS and not re.fullmatch(r"20\d\d", w)}
    if not hits and wants_cheap and not leftover:
        for row in rows:
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
    #
    # A query that names no brand or model is asking about a CATEGORY —
    # "electric car in dubai", "ev car in dubai" — and every row in it scores
    # alike, so the old ordering fell back to source tier and then price
    # inside each tier: a pick of the category, but not its cheapest end. This
    # channel's writer reliably frames these as "the cheapest X", so it has to
    # be handed the cheapest X to say that truthfully. false_superlative() in
    # script.py is the check; this is what lets the check pass.
    if not named and groups:
        wants_cheap = True
    hits.sort(key=lambda t: (-t[4], t[2], t[1]) if wants_cheap
              else (-t[0], t[1], t[2]))
    out = [t[3] for t in hits[:limit]]

    # Cost rows (insurance, registration, Salik, fuel) live in their own files
    # with their own shape. When the query is about running a car rather than
    # buying one, they lead — but they have to be RANKED, not just listed.
    # Taking them in file order meant "salik charges dubai" returned
    # third-party liability tables, because insurance.csv loads first.
    if (terms & fact_words) or (_tokens(query) & ROUTE_ONLY) or \
            any(_phrase_in(lowered, ph) for ph in fact_phrases):
        scored = []
        for r in usable_facts(pool):
            if not usable(r):
                continue
            # Weighted the same way car rows are, and for the same reason.
            # A flat word count let "dubai" appearing in a note tie with
            # "impound" appearing in the item name, so "car impound rules in
            # dubai" answered with the registration fee.
            name = _tokens(r.get("category", ""), r.get("item", ""))
            body = _tokens(r.get("basis", ""), r.get("notes", ""))
            idf = _idf(pool)
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
    bike = is_bike_query(query)
    vocab = _model_vocab(bike)
    raw = _tokens(query)
    direct = {w for w in raw
              if (len(w) > 2 or w in vocab) and w not in STOPWORDS}
    dropped = raw - direct
    implied: set[str] = set()
    fired = []
    tables = (((BIKE_PHRASE_SEGMENTS, "segment"),
               ({**PHRASE_TERMS, **BIKE_PHRASE_TERMS}, "term")) if bike else
              ((PHRASE_SEGMENTS, "segment"), (PHRASE_TERMS, "term")))
    for table, name in tables:
        for phrase, extra in table.items():
            if _phrase_in(lowered, phrase):
                implied |= _fold(extra)
                fired.append(f"{phrase!r} -> {sorted(_fold(extra) - STOPWORDS)} ({name})")
    implied -= STOPWORDS

    cheap = bool((direct | implied) & CHEAP_WORDS) or any(
        _phrase_in(lowered, ph) for ph in CHEAP_PHRASES)
    fw = FACT_WORDS | BIKE_FACT_WORDS if bike else FACT_WORDS
    fp = FACT_PHRASES | BIKE_FACT_PHRASES if bike else FACT_PHRASES
    facts = bool(((direct | implied) & fw) or (raw & ROUTE_ONLY)
                 or any(_phrase_in(lowered, ph) for ph in fp))

    out = [f"query      {query!r}",
           f"searching  {sorted(direct) or '(nothing — see dropped)'}",
           f"dropped    {sorted(dropped)}  (too common or too short to rank on)"]
    if fired:
        out.append("bridges    " + "\n           ".join(fired))
    else:
        out.append("bridges    none fired")
    out.append(f"ranking    {'cheapest first' if cheap else 'best match first'}")
    gone = missing_model(query, load_bikes() if bike else load())
    if gone:
        out.append(f"files      none — {gone!r} sits where a model name goes, and no "
                   f"row has that model. Add its rows to "
                   f"{'bikes.csv' if bike else 'cars.csv'} to cover it")
    elif bike and not_motorcycle(query):
        out.append("files      none — bicycles and e-scooters are not motorcycles")
    elif bike:
        out.append("files      bikes.csv" + (" + bike_rules.csv and the motorcycle rows"
                                              " of the cost files" if facts else " only")
                   + ("" if wants_offroad(query) else "; off-road bikes left out"))
    else:
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
            for row in load() + load_bikes() + usable_facts("all")
            if row.get("source_url", "").strip()}


# Minimum IDF-weighted overlap between the citation context and the candidate
# row before a numeric match counts as a trace. Raw word counts do not work:
# "car" and "maximum" appear everywhere and carry no information, so a single
# generic hit would let any number claim any row's source. Rare words clear
# this floor on their own; common ones cannot.
MIN_CONTEXT_OVERLAP = 3.0


def source_for(value, context: str = "", fact_context: str | None = None) -> str | None:
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

    ctx_tok = _tokens(context) - STOPWORDS
    # Compared against the fact rows below after stopword removal — _tokens
    # keeps every word for other callers, so the filtering happens here.
    # The fact tables match on words, so they get the narrow context: the
    # scene's own label. Handed the whole narration, "AED 1,000 is the
    # average annual cost" of insurance matched the 1,000 EXCESS cap.
    fact_ctx = _tokens(context if fact_context is None else fact_context) - STOPWORDS
    best, best_score = None, -1

    # A price belongs to a car, so the car has to be named. Matching on the
    # number alone cited the Qin Plus EV's 74,900 to a Dongfeng AX7 at the
    # same price, and attach_sources() hands that citation out unchecked.
    # The model name counts double: "Toyota" alone does not tell the Hilux
    # from the Land Cruiser.
    pool = [r for r in load() + load_bikes() if usable(r)]

    def _model_words(r):
        brand = _tokens(r.get("brand", "")) - STOPWORDS
        # "3" and "7" sit in dozens of model names; alone they name nothing.
        return {w for w in _tokens(r.get("model", "")) - STOPWORDS - brand
                - CATEGORY_WORDS - BIKE_CATEGORY_WORDS
                # one letter is an apostrophe, not a model: "That's" left an
                # "s" that matched the S-Class
                if len(w) >= 2 and any(c.isalpha() for c in w)}

    # Once the context names a model, the brand alone is not enough. "BYD
    # Seal 7 price" matched the Atto 3, another BYD at the same 109,900.
    names_a_model = any(ctx_tok & _model_words(r) for r in pool)
    for row in pool:
        brand = _tokens(row.get("brand", "")) - STOPWORDS
        model_hit = ctx_tok & _model_words(row)
        if names_a_model and not model_hit:
            continue
        # Category words score nothing: "Cheapest BYD EV price" cited a
        # Chevrolet Captiva EV on the word "ev" outweighing the brand.
        score = 2 * len(model_hit) + len(ctx_tok & brand)
        if not score:
            continue
        prices = [row.get(k) for k in ("price_from_aed", "price_to_aed")]
        matched = any(raw and abs(float(raw) - v) < 1 for raw in prices
                      if raw and raw.replace(".", "", 1).isdigit())
        # Trim prices are written in the notes ("AT GLX 2.7 petrol 137,900").
        # The notes also keep figures that were REJECTED ("was 109,900 from an
        # aggregator; official site says 135,900"), so a notes figure counts
        # only when it sits inside this row's own from-to range.
        lo, hi = (float(p) if p else None for p in prices)
        if not matched and lo and hi and lo <= v <= hi:
            matched = any(abs(float(n.replace(",", "")) - v) < 1
                          for n in re.findall(r"\d{1,3}(?:,\d{3})+|\d{4,}",
                                              row.get("notes", "")))
        if matched and score > best_score:
            best, best_score = row, score

    # A line that names no car at all ("the cheapest new car starts at
    # 35,795") can still be traced, but only when exactly one row has that
    # price AND that row is the kind of car the line says. Otherwise "the
    # cheapest EV at 74,900" would be pinned on a petrol car that costs it.
    if best is None and not names_a_model and not any(
            ctx_tok & (_tokens(r.get("brand", "")) - STOPWORDS) for r in pool):
        kinds = ctx_tok & (CATEGORY_WORDS | BIKE_CATEGORY_WORDS)
        same = [r for r in pool
                if any(r.get(k) and abs(float(r[k]) - v) < 1
                       for k in ("price_from_aed", "price_to_aed"))
                and kinds <= _tokens(r.get("segment", ""), r.get("powertrain", ""))]
        if len(same) == 1:
            best = same[0]

    if best is not None:
        return (f"{best['brand']} {best['model']} — {best['source_url']} "
                f"(checked {best['checked_on']})")

    # Not a car price — try the cost and rule tables, the other place a number
    # in a script can legitimately have come from. Context decides here too,
    # and it matters more than in cars.csv: 400 is the seat-belt fine, the
    # phone fine and the child-seat fine, and citing the wrong one is a
    # mistake a viewer will catch.
    best, best_score = None, -1
    for row in usable_facts("all"):
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
        idf = _idf("all")
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

    if (warn := expiry_warning()):
        print(f"\n  EXPIRING SOON: {warn}")

    old_month = [r for r in facts if for_month(r) and not usable(r)]
    if old_month:
        print("\nMonthly prices for another month, withheld (UAE fuel prices "
              "change on the 1st):")
        for r in old_month:
            print(f"  · {r['item']}: {r['basis']} in {r.get('_file', 'the data')}")

    bikes = load_bikes()
    if bikes:
        rules = usable_facts("bike")
        print(f"{len(bikes)} rows in {BIKES_PATH.name} "
              f"({sum(1 for r in bikes if usable(r))} usable, "
              f"{sum(1 for r in bikes if not road_bike(r))} off-road)  +  "
              f"{len(rules)} motorcycle rule/cost rows "
              f"({sum(1 for r in rules if usable(r))} usable)")
        by = {}
        for r in bikes:
            by[r["brand"]] = by.get(r["brand"], 0) + 1
        print("  " + ", ".join(f"{b} {n}" for b, n in by.items()))

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
