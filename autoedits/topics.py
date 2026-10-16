"""
Topic discovery from real search demand.

Your analytics said 91.4% of views arrive via YouTube search and only 3.8% via
the Shorts feed. Rather than fight that, this module leans into it: it harvests
YouTube's own autocomplete — the literal phrases people type — and ranks them
by demand against how contested they already are.

The alphabet-expansion trick ("best suv uae a", "... b", ...) is how you pull
hundreds of real suggestions out of an endpoint that returns ten at a time.

    python -m autoedits.topics            # fill the queue
    python -m autoedits.topics --evergreen  # load the curated list only
    python -m autoedits.topics --probe    # just test the endpoint

Autocomplete has one blind spot worth naming: it reports what is being
searched *now*, which is why the queue kept filling with fuel prices and
model-year pricing. Those are real questions, but the answers expire, and a
channel you do not have time to maintain cannot afford content that rots. So
the queue has a second source — data/evergreen_topics.txt, a hand-written list
of questions about UAE law and regulation, which loads at a score high enough
to sit above anything harvested.
"""

from __future__ import annotations

import json
import re
import string
import sys
import time
from collections import Counter

import requests

from . import db
from .config import CFG, REGION, ROOT, YT_API_KEY

EVERGREEN_PATH = ROOT / "data" / "evergreen_topics.txt"

# Comfortably above anything autocomplete produces. Demand there is a sum of
# rank weights across 27 prefixes; in practice the best phrases land near 150,
# and score is demand discounted by competition. Starting at 1000 and stepping
# down keeps the curated list in file order at the top of the queue, which
# makes the text file the running order for the channel.
EVERGREEN_TOP = 1000.0

# Tried in order. The youtube-branded host 404s/400s depending on params, so
# the plain Google ones are the reliable path.
SUGGEST_HOSTS = [
    "https://suggestqueries.google.com/complete/search",
    "https://clients1.google.com/complete/search",
]
SEARCH = "https://www.googleapis.com/youtube/v3/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) autoedits/1.0"}

# Failures are counted rather than swallowed, so a dead endpoint is visible
# instead of looking identical to "no results".
STATS = Counter()


def suggest(query: str, region: str = REGION, lang: str = "en") -> list[str]:
    """Ask YouTube what people actually type after this prefix."""
    params = {"client": "youtube", "ds": "yt", "hl": lang,
              "gl": region.lower(), "q": query}

    for host in SUGGEST_HOSTS:
        try:
            r = requests.get(host, headers=HEADERS, timeout=10, params=params)
        except requests.RequestException as exc:
            STATS[f"network error: {type(exc).__name__}"] += 1
            continue
        if r.status_code != 200:
            STATS[f"HTTP {r.status_code} from {host.split('/')[2]}"] += 1
            continue

        # JSONP: window.google.ac.h([...])
        body = r.text.strip()
        m = re.search(r"\((.*)\)\s*;?\s*$", body, re.S)
        try:
            data = json.loads(m.group(1) if m else body)
        except (json.JSONDecodeError, AttributeError):
            STATS["unparseable response"] += 1
            continue

        rows = data[1] if isinstance(data, list) and len(data) > 1 else []
        out = [row[0] for row in rows
               if isinstance(row, list) and row and isinstance(row[0], str)]
        STATS["ok"] += 1
        return out

    STATS["all hosts failed"] += 1
    return []


def expand(seed: str, deep: bool = True, pause: float = 0.3) -> dict[str, float]:
    """Harvest suggestions for a seed. Returns {phrase: demand_score}.

    Demand comes from rank — YouTube returns suggestions roughly in popularity
    order, so position 1 is worth more than position 9. A phrase surfacing
    under several prefixes accumulates score, which is a decent proxy for
    "lots of people search around this".
    """
    found: dict[str, float] = {}

    def harvest(q: str) -> None:
        for rank, phrase in enumerate(suggest(q)):
            key = phrase.lower()
            found[key] = found.get(key, 0.0) + max(1.0, 10.0 - rank)
        time.sleep(pause)   # be polite; undocumented public endpoint

    harvest(seed)
    if deep:
        for ch in string.ascii_lowercase:
            harvest(f"{seed} {ch}")
    return found


def load_evergreen() -> list[str]:
    """The curated list, in file order. Blank lines and # comments ignored."""
    if not EVERGREEN_PATH.exists():
        return []
    out = []
    for line in EVERGREEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            out.append(line)
    return out


def seed_evergreen(verbose: bool = True) -> int:
    """Load the curated list into the queue above the harvested topics.

    These bypass why_rejected() on purpose — a phrase you wrote by hand does
    not need to prove it contains a region word. Anything the filter *would*
    have dropped is still reported, because that usually means the line is a
    typo rather than a considered exception.
    """
    db.init()
    phrases = load_evergreen()
    for i, phrase in enumerate(phrases):
        db.promote_topic(phrase, "evergreen", EVERGREEN_TOP - i)

    if verbose and phrases:
        print(f"{len(phrases)} evergreen topic(s) loaded from "
              f"{EVERGREEN_PATH.name}, top of the queue.")
        odd = [(p, r) for p in phrases if (r := why_rejected(p))]
        if odd:
            print("  These would not have survived the autocomplete filter — "
                  "fine if deliberate, worth a look if not:")
            for phrase, reason in odd:
                print(f"    · {phrase}  ({reason})")
    elif verbose:
        print(f"No curated topics found at {EVERGREEN_PATH}")
    return len(phrases)


# A phrase you typed yourself outranks both the curated list and anything
# harvested. You asked for it by name; the queue should not make you wait.
ADDED_TOP = 2000.0


def coverage(query: str) -> tuple[int, list[str]]:
    """How many rows the writer would get for this phrase, and the first few."""
    from .cars import facts_for
    rows = [r for r in facts_for(query).splitlines() if r.strip()]
    return len(rows), rows


def check(query: str, indent: str = "  ", queued: bool = True) -> bool:
    """Report whether this phrase can become a video. True if it can.

    Four separate things decide that, and before this they were spread across
    three modules and announced by nothing: retrieval has to find rows, the
    dedupe guards have to let the phrase through, and the pipeline has to be
    willing to build it. A phrase that fails any of them used to just never
    appear, which is indistinguishable from a queue that has not got to it.
    """
    query = query.strip().lower()
    n, rows = coverage(query)
    ok = True

    if n:
        print(f"{indent}data      {n} row(s) your files can support this with")
        for row in rows[:3]:
            print(f"{indent}          · {row.split(' | [source:')[0][:96]}")
        if n > 3:
            print(f"{indent}          … and {n - 3} more")
    else:
        ok = False
        print(f"{indent}data      NOTHING — the writer would have no figures, so "
              f"the run skips this")
        print(f"{indent}          Fix it by adding rows to data/cars.csv (or the "
              f"cost/law files) that")
        print(f"{indent}          use the words this phrase uses. Check what it "
              f"matched on with:")
        print(f"{indent}            python -m autoedits.cars --why "
              f"{query!r}")

    for sim, title in db.near_misses(query):
        print(f"{indent}overlap   {sim:.0%} with a video you made: {title!r}")

    reason = db.why_blocked(query)
    if reason and not queued and reason.startswith("not in the queue"):
        # --check is asking "could this be built", not "is it queued".
        print(f"{indent}queue     not queued yet — --add would put it on top")
    elif reason:
        ok = False
        print(f"{indent}queue     BLOCKED: {reason}")
    else:
        print(f"{indent}queue     clear")

    print(f"{indent}verdict   {'the next run can build this' if ok else 'the next run will NOT build this'}")
    return ok


def add(phrases: list[str]) -> int:
    """Queue phrases at the top and say, for each, whether it can be built."""
    db.init()
    buildable = 0
    for i, phrase in enumerate(phrases):
        phrase = phrase.strip().lower()
        if not phrase:
            continue
        db.promote_topic(phrase, "added", ADDED_TOP - i)
        print(f"\nqueued {phrase!r} at the top of the queue")
        if (r := why_rejected(phrase)):
            # Not fatal — a phrase you typed does not have to look like
            # something autocomplete would have produced. Worth saying out
            # loud, because it usually means a typo.
            print(f"  note      autocomplete would have dropped this ({r})")
        buildable += check(phrase)
    print(f"\n{buildable} of {len(phrases)} ready to build."
          + ("  Next: python -m autoedits.pipeline" if buildable else ""))
    return 0 if buildable else 1


def competition(query: str) -> float | None:
    """Rough contest score, 0-1, lower is easier. Needs a YouTube API key.

    Counts how many of the top ten results already have the whole phrase in
    their title. A query whose first page is all exact-match titles is one you
    will not win from 212 subscribers.
    """
    if not YT_API_KEY:
        return None
    try:
        r = requests.get(SEARCH, timeout=10, params={
            "part": "snippet", "q": query, "type": "video",
            "maxResults": 10, "regionCode": REGION, "key": YT_API_KEY})
        r.raise_for_status()
        items = r.json().get("items", [])
    except (requests.RequestException, ValueError):
        STATS["competition lookup failed"] += 1
        return None
    if not items:
        return 0.0
    q = query.lower()
    return min(1.0, sum(1 for it in items
                        if q in it["snippet"]["title"].lower()) / len(items))


# ------------------------------------------------------------------ filter --

def why_rejected(phrase: str) -> str | None:
    """None if the phrase is keepable, else the reason. Reasons get counted so
    you can see whether your filters are too tight."""
    t = CFG["topics"]
    for b in t.get("exclude", []):
        if b in phrase:
            return f"excluded word: {b}"
    if len(phrase) < 12:
        return "too short"
    if len(phrase.split()) > 9:
        return "too long"
    must = t.get("must_contain_any", [])
    if must and not any(m in phrase for m in must):
        return "no region word"
    return None


def refresh(limit_per_seed: int = 40, check_competition: bool = True,
            verbose: bool = True) -> int:
    """Rebuild the topic queue from the seeds in config.yaml."""
    db.init()
    STATS.clear()
    rejects = Counter()
    kept_total = seed_evergreen(verbose=verbose)

    seeds = CFG["topics"]["seeds"]
    for n, seed in enumerate(seeds, 1):
        if verbose:
            print(f"[{n}/{len(seeds)}] {seed!r} …", end="", flush=True)

        raw = expand(seed)
        kept = 0
        for phrase, demand in sorted(raw.items(), key=lambda kv: -kv[1]):
            if kept >= limit_per_seed:
                break
            reason = why_rejected(phrase)
            if reason:
                rejects[reason] += 1
                continue
            comp = competition(phrase) if check_competition else None
            db.add_topic(phrase, "autocomplete", demand, comp)
            kept += 1
            if check_competition:
                time.sleep(0.2)

        kept_total += kept
        if verbose:
            print(f" {len(raw)} suggestions → {kept} kept")

    if verbose:
        print(f"\nEndpoint: {dict(STATS)}")
        if rejects:
            print("Filtered out:")
            for reason, count in rejects.most_common():
                print(f"  {count:5d}  {reason}")
        if STATS.get("ok", 0) == 0:
            print("\n!! No successful requests. The suggest endpoint is "
                  "unreachable from here — check your connection or proxy.")
    return kept_total


def probe() -> int:
    """Test the endpoint without touching the database."""
    for q in ["best suv uae", "is the tesla model y worth it in dubai"]:
        out = suggest(q)
        print(f"\n{q!r} → {len(out)} suggestions")
        for s in out[:8]:
            print(f"   {s}")
    print(f"\n{dict(STATS)}")
    return 0 if STATS.get("ok") else 1


USAGE = """Topic queue.

    python -m autoedits.topics                     harvest autocomplete, refill
    python -m autoedits.topics --evergreen         reload data/evergreen_topics.txt
    python -m autoedits.topics --add "phrase" ...  queue your own, top priority
    python -m autoedits.topics --check "phrase"    can this be built? (queues nothing)
    python -m autoedits.topics --probe             test the suggest endpoint
"""


def _phrases(flag: str) -> list[str]:
    """Everything after the flag that is not itself a flag."""
    rest = sys.argv[sys.argv.index(flag) + 1:]
    out = []
    for a in rest:
        if a.startswith("--"):
            break
        out.append(a)
    return out


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(USAGE)
        raise SystemExit(0)

    if "--probe" in sys.argv:
        raise SystemExit(probe())

    if "--add" in sys.argv:
        if not (ps := _phrases("--add")):
            print('Give it a phrase: --add "cheapest electric suv in uae"')
            raise SystemExit(2)
        raise SystemExit(add(ps))

    if "--check" in sys.argv:
        if not (ps := _phrases("--check")):
            print('Give it a phrase: --check "cheapest electric suv in uae"')
            raise SystemExit(2)
        db.init()
        bad = 0
        for ph in ps:
            print(f"\n{ph!r}")
            bad += not check(ph, queued=False)
        raise SystemExit(1 if bad else 0)

    if "--evergreen" in sys.argv:
        # No network, no autocomplete — just reload the curated list. Useful
        # after editing the file, and the one command that still works when
        # the suggest endpoint is down.
        seed_evergreen()
        print("\nTop of the queue:\n")
        for t in db.next_topics(20):
            print(f"  {t['score']:7.1f}  {t['source']:<12} {t['query']}")
        raise SystemExit(0)

    total = refresh()
    print(f"\n{total} phrase(s) queued. Top of the list:\n")
    for t in db.next_topics(25):
        comp = "" if t["competition"] is None else f"  comp {t['competition']:.1f}"
        print(f"  {t['score']:7.1f}{comp}  {t['query']}")
