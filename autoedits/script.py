"""
Script generation.

This file is the quality lever of the whole system. The renderer only draws
what this produces; if the writing is generic, the video is generic, and you
have 479 uploads proving what that looks like.

Two rules are enforced structurally rather than hoped for:

  1. Every number carries a `source`. The model is told to leave a number out
     rather than guess it. The review screen shows you the sources — checking
     them is what your five minutes a day is actually for.
  2. The verdict must be arguable. A short nobody can disagree with gets no
     comments, and your channel currently averages zero.
"""

from __future__ import annotations

import json
import re
import time

import requests

from . import render as R
from .config import (GROQ_EFFORT, GROQ_KEY, GROQ_MAX_TOKENS, GROQ_MODEL,
                     GROQ_TPM,
                     OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT, WRITER,
                     require)

SYSTEM = """You write 20-30 second vertical video scripts about buying and \
owning cars in the United Arab Emirates. The audience is someone in Dubai, \
Abu Dhabi or Sharjah deciding what to buy, sitting on YouTube search with a \
specific question.

VOICE
- Direct, specific, a little blunt. A knowledgeable friend, not a brochure.
- Short sentences. No filler openers ("In today's video", "Let's dive in").
- Never hype adjectives: no "insane", "shocking", "huge", "you won't believe".
- Dirhams (AED). Local specifics land: Salik, RTA, Sheikh Zayed Road, agency
  warranty, GCC spec, resale to the used market, summer heat on batteries.

STRUCTURE (this order, always)
1. hook      - The single most important line. 3-8 words, MUST end with "?".
               Put the *asterisks* around ONE phrase only, never the whole
               line — asterisks colour the text, and colouring everything
               emphasises nothing.
               MUST be a question and MUST end with "?". Write it the way the
               viewer would say it out loud, not as the keyword string they
               typed. Wrap the 1-3 word core in *asterisks* for emphasis.
                 WRONG: "*Nissan Patrol vs Land Cruiser* uae"
                 RIGHT: "*Patrol or Land Cruiser* — which one actually holds
                         its value?"
               A search phrase is not a hook. Nobody stops scrolling for a
               label.
               NEVER STATE A LAW YOU WERE NOT GIVEN
                   Fines, black points, impound periods, tint percentages, tread
                   depths, age limits: if the exact figure is not in the evidence
                   above, it does not go in the script. Not approximately, not
                   "around", not "about five years". The evidence is filtered to
                   what an official source states, so a missing number means no
                   official source says it — and viewers act on these. Write the
                   physical effect instead: what the heat does to the tyre, how hot
                   the cabin gets, why the battery dies. That is the better video
                   anyway, and it cannot be wrong.

               TAKE A SIDE. The hooks that travel on this platform carry an
               attitude, not a neutral enquiry — "the dumb design of modern
               cars", "electric cars are not the future", "why are new cars so
               unreliable". Ask the question the way someone who has already
               formed an opinion would ask it, then let the sourced numbers
               settle it. The difference is register, never accuracy: the
               stance goes in the hook, the evidence decides the verdict, and
               if the data does not support the stance you change the stance.
2. stat      - one concrete number that reframes the question.
3. compare   - 2-3 options on one axis (price, 5-year cost, resale%).
               When comparing CARS they must be ones a real buyer would
               cross-shop: closest in price wins. Never put a 140k SUV against
               a 310k one — nobody is deciding between those.
               When the topic is a RULE, compare the rule's own bands instead
               — excess by car value, fine by violation, depreciation by year,
               premium by engine size. Those are meant to be far apart; that
               gap IS the story.
4. bullets   - 2-3 things the sticker price hides. Give SPECIFICS with numbers
               from the facts, not category names. "Insurance and maintenance"
               tells the viewer nothing they didn't know.
5. verdict   - your actual recommendation. Name the specific car and the
               specific circumstance. "Buy it if you prioritise affordability"
               is not a verdict, it is a shrug — it applies to every cheap car
               ever made. Say which one, and what the real trade is.
6. question  - a specific question the viewer can answer in four words.
               Not "what do you think?" — give them something to pick a side on.

FACTS
- Every number you use must have a `source` naming where it comes from.
- If you do not have a real figure, leave that scene out. Do NOT invent
  prices, percentages or dates. A shorter honest script beats a padded one.
- Prefer ranges you are confident in over false precision.

NARRATION
- ONE sentence per scene. 12-20 words. Never two sentences.
- EVERY LINE MUST STAND ALONE WITH THE SCREEN OFF. A listener who only hears
  the audio must still get the fact. Name the subject and say the number out
  loud, in words a person would speak.
- Never open a line with "that", "those", "these", "this" or "it" pointing at
  something only the screen shows. "That's the sticker price" is a caption,
  not narration: the listener never heard a price. Write "The cheapest Jetour
  starts at sixty-nine thousand five hundred dirhams" instead.
- Do not read the on-screen text back word for word either. Say the same fact
  differently, with the subject named. Standing alone and being a verbatim
  reading are two different things — you need the first, not the second.
- The stat scene's narration MUST contain the stat's own number. A stat scene
  whose voiceover never says the figure is a failed scene.
- NARRATION IS READ ALOUD BY A HUMAN VOICE. Spell out ABBREVIATIONS, because
  a voice reads them as letters: "dirhams", never "AED"; "per cent", never
  "%"; "kilometres", never "km"; "horsepower", never "hp".
- But write NUMBERS AS DIGITS: "139,900 dirhams", not "one hundred thirty-nine
  thousand nine hundred dirhams". The speech engine reads digits correctly and
  you do not. Spelling six figures out in words produced "thirty-nine thousand
  nine hundred" for 139,900 — the leading hundred-thousand was dropped from
  three prices in one sentence. Copy the digits exactly as the facts give them.
- Never write "90k" or "1.4M" — those a voice does mangle. Write 90,000.
- The on-screen text keeps AED and the symbols; this rule is only narration.
- Narration length sets how long the scene stays up, so a rambling line means
  the viewer stares at the same frame and swipes away. Be brutal.

RULE AND LAW TOPICS
Many of these questions are about UAE law or regulation rather than which car
to buy: insurance excess caps, black points, loan limits, depreciation
schedules. For those:
- The number is the whole video. Lead with it and do not soften it.
- Say who sets the rule — the Central Bank, the Insurance Authority, the
  federal traffic law. That is what makes it trustworthy rather than an
  opinion.
- The verdict is what the viewer should DO about it, not which car to buy.
  "Check your policy schedule before you sign" is a verdict. So is "if your
  car is past six years old, comprehensive stops being worth it."
- Never make the rule sound like it might change. It has not, for years.

UNITS — get this right or the video is wrong
Every figure needs its unit named, because the renderer prefixes AED by
default. Set stat_unit and compare_unit to one of:
  AED | percent | points | days | months | years | degrees | mm | psi | none
"4" black points rendered as "AED 4" is not a formatting slip, it is a false
statement on screen.

WHAT ACTUALLY HOLDS PEOPLE — measured on this channel, not guessed
The videos that get rewatched are never the ones answering a category
question. They name ONE specific, checkable, slightly surprising thing about
a named subject. From this channel's own analytics, average times watched
through:

    "Volvo's hidden remote headrest control is evil!"      1.10
    "The Alpine A290 has NO CUP HOLDER?!"                  1.35
    "9 Types of Car Clutches: Find Your Perfect Match!"    6.64
    ...against...
    "Best electric car in Dubai"                           0.30

The search phrase is how someone arrives; the hook is what stops them
leaving, and those are different jobs. "Car insurance rules in the UAE" is
the query — the hook is "your insurer owes you AED 300 a day". Always prefer
a single checkable number over a survey of options.

A dense enumerated list is the other shape that works: the clutches video is
rewatched because fifty seconds is not long enough to take in nine things.
Use it when the data supports a real count — "the four things that fail a UAE
inspection" — never as a padded listicle.

LENGTH
- The whole video must land under 30 seconds. That is roughly 6 short lines
  total. A 43-second script is a failed script.

REQUIRED FIELDS — a scene without these cannot be drawn:
- hook, verdict, question : "text"
- stat                    : "label" AND "value"
- compare                 : "title" AND "rows" (two or more)
- bullets                 : "title" AND "bullets"
Every scene also needs "narration".

Return ONLY valid JSON matching the schema. No markdown fence, no commentary."""

# Deliberately absurd placeholder numbers. A small model will copy realistic
# example values straight out of this template and present them as facts —
# llama3 did exactly that, shipping a video built entirely from the old
# example's 189900 and 242000. These values are also checked for on the way
# out (see CANARIES), so if they ever appear in output the script is rejected.
SCHEMA_HINT = """{
  "title": "under 90 chars, plain English, NO asterisks, capitalise UAE/AED",
  "kicker": "2-4 word category label, e.g. 'UAE buying guide'",
  "description": "The YouTube description. Answer the search question in the
                  FIRST sentence with the actual number — that line is what
                  shows in search results. Then a bulleted list of each figure
                  with its source URL and the date it was checked. Then one
                  line noting prices are base trim and exclude registration
                  and insurance. End with the closing question. Say 'the
                  cheapest we found', never 'the cheapest in the UAE' — the
                  data is good but it is not the whole market.",
  "tags": ["8-12 lowercase tags"],

  "hook_text": "<the viewer's question, ending in '?', *core phrase* in asterisks>",
  "hook_narration": "<one sentence>",

  "stat_label": "<what the number is>",
  "stat_value": 111111,
  "stat_unit": "<AED | percent | points | days | months | years | degrees | mm | psi | none>",
  "stat_footnote": "<one line of context>",
  "stat_source": "<the exact URL the figure came from>",
  "stat_narration": "<one sentence>",

  "compare_title": "<the axis being compared>",
  "compare_unit": "<AED | percent | points | days | months | years | degrees | mm | psi | none>",
  "compare_lower_is_better": true,
  "compare_rows": [{"name":"<car A>","value":222222,"note":"<what's included>"},
                   {"name":"<car B>","value":333333,"note":"<what's included>"}],
  "compare_source": "<the exact URL>",
  "compare_narration": "<one sentence>",

  "bullets_title": "<what the price hides>",
  "bullets": ["<point>","<point>","<point>"],
  "bullets_narration": "<one sentence>",

  "verdict_text": "<your actual recommendation, arguable>",
  "verdict_narration": "<one sentence>",

  "question_text": "<question answerable in four words>",
  "question_narration": "<one sentence>"
}

RULES
- Everything in <angle brackets> describes what to write. Never copy it.
- 111111, 222222 and 333333 are placeholders. Never output them.
- title, kicker, hook_text, verdict_text and question_text are MANDATORY.
- Use ONLY figures from the verified facts above, and put the exact source URL
  given there into stat_source / compare_source. A figure you cannot source
  from those facts must be left out entirely.
- If you have no real number, omit stat_value and compare_rows. A shorter
  honest script is better than a padded one.
- compare_rows must have two or three entries, never one.
- stat_unit and compare_unit are MANDATORY whenever you give a figure. Use
  "AED" only for money. A percentage is "percent", black points are "points".
- compare_lower_is_better: true when the smallest bar is the good news (a
  cheaper premium, a smaller excess), false when the biggest is (a larger
  no-claims discount)."""


# If any of these survive into the output, the model copied the template.
CANARIES = {111111, 222222, 333333}

# How a unit is drawn. The renderer prefixes AED unless told otherwise, which
# was fine while every figure in the data was money — data/rules.csv is black
# points, days and percentages, and "AED 4" for a seat-belt penalty is a wrong
# number on screen, not a cosmetic slip.
UNITS = {
    "aed":     ("AED", ""),
    "percent": ("", "%"),
    "points":  ("", " points"),
    "days":    ("", " days"),
    "months":  ("", " months"),
    "years":   ("", " years"),
    "degrees": ("", "\u00b0C"),
    "mm":      ("", "mm"),
    "psi":     ("", " PSI"),
    "none":    ("", ""),
}


def _names_cars(rows: list[dict]) -> bool:
    """True when at least two rows are named after real cars.

    Brands are distinctive enough to test on: "Nissan Patrol" and "Toyota Land
    Cruiser" are cars a buyer chooses between, "Car worth up to AED 50,000"
    and "Car worth over AED 500,000" are two rungs of the same regulation.
    """
    from . import cars

    brands = {(r.get("brand") or "").strip().lower()
              for r in cars.load()} - {""}
    hits = 0
    for row in rows:
        name = str(row.get("name", "")).lower()
        if any(re.search(rf"\b{re.escape(b)}\b", name) for b in brands):
            hits += 1
    return hits >= 2


def _unit(name: str | None) -> tuple[str, str]:
    """(prefix, suffix) for a unit name. Unknown or missing means dirhams,
    which is what the file held before rules.csv existed."""
    return UNITS.get((name or "aed").strip().lower(), ("AED", ""))

# Two cars are only worth comparing if a buyer might genuinely choose between
# them. Beyond this ratio they are in different markets.
COMPARE_MAX_RATIO = 2.0


# ---------------------------------------------------------------- providers --

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_RETRIES = 3            # 429s are a pacing problem, not a failure

# What the most recent Groq call reported. Diagnostics only.
LAST_CALL: dict = {}


def _groq(prompt: str) -> str:
    """The main writer call: the full script schema."""
    return _groq_json(prompt, GROQ_SCHEMA, "short_script")


# Groq's tokenizer counts higher than chars/4 — measured 4114 against an
# estimate of 3480 on 2026-10-10, so budget 25% above the naive estimate.
TOKEN_FUDGE = 1.25
TPM_RESERVE = 200          # leave the minute a little room
MIN_COMPLETION = 2200      # a full script measured 2130; below this is futile


def _fit_completion(prompt: str) -> int:
    """How many completion tokens we may reserve without a 413.

    max_completion_tokens is not a free ceiling: Groq charges it against
    tokens-per-minute up front. A 4000 reservation on top of a fact-rich
    prompt asked for 8114 of an 8000 limit and the request was rejected
    outright, so the reservation has to shrink to fit the prompt.
    """
    est = int((len(SYSTEM) + len(prompt)) / 4 * TOKEN_FUDGE)
    room = GROQ_TPM - TPM_RESERVE - est
    if room < MIN_COMPLETION:
        raise RuntimeError(
            f"The prompt alone is ~{est} tokens, leaving {room} of the "
            f"{GROQ_TPM}/min budget for the reply — under the {MIN_COMPLETION} "
            f"a full script needs. Trim the facts for this topic (cars."
            f"facts_for limit), shorten SYSTEM, or raise models.groq_tpm if "
            f"you are no longer on the free tier.")
    fit = min(GROQ_MAX_TOKENS, room)
    if fit < GROQ_MAX_TOKENS:
        print(f"    prompt ~{est} tok, trimming reply budget "
              f"{GROQ_MAX_TOKENS} -> {fit} to stay under {GROQ_TPM}/min")
    return fit


def _groq_json(prompt: str, schema: dict, schema_name: str) -> str:
    """Free-tier Groq. Uses strict structured outputs, so the schema is
    enforced by constrained decoding exactly as Ollama's grammar is — the
    model cannot return a script with a field missing.

    The free tier's ceiling is tokens-per-minute, not per-day, so a 429 here
    means "you went too fast", not "you ran out". Wait and retry.
    """
    require(GROQ_KEY, "GROQ_API_KEY")
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        # Lower than default: structure beats flair here.
        "temperature": 0.6,
        "max_completion_tokens": _fit_completion(prompt),
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name,
                                            "strict": True,
                                            "schema": schema}},
    }
    if GROQ_EFFORT:
        body["reasoning_effort"] = GROQ_EFFORT
    headers = {"Authorization": f"Bearer {GROQ_KEY}",
               "content-type": "application/json"}

    for attempt in range(GROQ_RETRIES + 1):
        try:
            r = requests.post(GROQ_URL, headers=headers, json=body, timeout=120)
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not reach Groq: {exc}") from exc

        if r.status_code == 429 and attempt < GROQ_RETRIES:
            # Groq tells us exactly how long to wait; fall back to 20s.
            try:
                wait = float(r.headers.get("retry-after", 20))
            except ValueError:
                wait = 20.0
            wait = min(max(wait, 1.0), 90.0) + 1.0
            print(f"    rate limited, waiting {wait:.0f}s "
                  f"(attempt {attempt + 1}/{GROQ_RETRIES})")
            time.sleep(wait)
            continue

        if r.status_code == 413:
            raise RuntimeError(
                f"Groq rejected the request as too large for one minute "
                f"(413). {r.text[:200]}")
        if r.status_code == 401:
            raise RuntimeError(
                "Groq rejected the key (401). Check GROQ_API_KEY in .env — "
                "get one at console.groq.com/keys. Verify it without spending "
                "a run: python -m autoedits.doctor --live")
        if r.status_code == 429:
            raise RuntimeError(
                f"Groq rate limit after {GROQ_RETRIES} retries. The free tier "
                f"allows 8k tokens/minute; a script costs about 4k, so two a "
                f"minute is the ceiling.")

        # Every other failure: show what Groq actually said. raise_for_status()
        # alone reports the URL and throws the body away, which is how two 400s
        # on 2026-10-06 went undiagnosed. The body carries the reason.
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
                detail = "; ".join(
                    f"{k}={v!r}" for k, v in err.items() if v is not None)
            except ValueError:
                detail = r.text[:600]
            raise RuntimeError(
                f"Groq returned HTTP {r.status_code} for model {GROQ_MODEL}.\n"
                f"  {detail or r.text[:600]}\n"
                f"  prompt was {len(SYSTEM) + len(prompt)} chars "
                f"(~{(len(SYSTEM) + len(prompt)) // 4} tokens), "
                f"max_completion_tokens={body['max_completion_tokens']}")

        data = r.json()
        choice = data["choices"][0]
        # A reasoning model spends completion budget on thinking before the
        # JSON starts. If finish_reason is 'length' the JSON is truncated, so
        # record it rather than letting _extract_json fail further downstream.
        fin = choice.get("finish_reason")
        usage = data.get("usage") or {}
        LAST_CALL.update({"finish_reason": fin,
                          "completion_tokens": usage.get("completion_tokens"),
                          "prompt_tokens": usage.get("prompt_tokens"),
                          "budget": body["max_completion_tokens"]})
        if fin == "length":
            raise RuntimeError(
                f"Groq stopped at the token ceiling (finish_reason=length): "
                f"{usage.get('completion_tokens')} of "
                f"{body['max_completion_tokens']} completion tokens used, so "
                f"the JSON is cut off. Raise models.groq_max_tokens in "
                f"config.yaml, or set models.groq_reasoning_effort: low.")
        return choice["message"]["content"]

    raise RuntimeError("unreachable")        # pragma: no cover


# Ollama constrains generation to this schema by compiling it to a grammar.
#
# It is deliberately FLAT rather than a scenes array. A nested array can only
# say "each item needs a type and a narration" — it cannot say "a hook needs
# text but a stat needs a label", so the model was free to emit a hook with no
# text, a comparison with one row, or a script with no closing question. Each
# of those cost six minutes of writing and got binned at validation.
#
# Flattened, the fields that must exist simply sit in `required`, and the
# decoder cannot produce a script without them. compare_rows carries
# minItems: 2, so a one-bar "comparison" is now unrepresentable.
OLLAMA_SCHEMA = {
    "type": "object",
    # A stat is REQUIRED, not optional. Grammar-constrained generation enforces
    # this list literally, which instructions cannot: qwen2.5:7b quietly
    # stopped emitting stat and compare scenes and produced 74 eight-second
    # videos that asserted things and showed nothing. Every other check passed,
    # because a script with no figures has no figures to find fault with.
    # Making the figure structural closes that off for any model.
    "required": ["title", "kicker", "description", "tags",
                 "hook_text", "hook_narration",
                 "stat_label", "stat_value", "stat_unit",
                 "stat_narration", "stat_source",
                 "verdict_text", "verdict_narration",
                 "question_text", "question_narration"],
    "properties": {
        "title": {"type": "string"},
        "kicker": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},

        "hook_text": {"type": "string"},
        "hook_narration": {"type": "string"},

        "stat_label": {"type": "string"},
        "stat_unit": {"type": "string",
                      "enum": ["AED", "percent", "points", "days",
                               "months", "years", "degrees", "mm", "psi",
                               "none"]},
        "stat_value": {"type": "number"},
        "stat_footnote": {"type": "string"},
        "stat_source": {"type": "string"},
        "stat_narration": {"type": "string"},

        "compare_title": {"type": "string"},
        "compare_unit": {"type": "string",
                         "enum": ["AED", "percent", "points", "days",
                                  "months", "years", "degrees", "mm", "psi",
                                  "none"]},
        "compare_lower_is_better": {"type": "boolean"},
        "compare_rows": {
            "type": "array", "minItems": 2, "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["name", "value"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "note": {"type": "string"},
                },
            },
        },
        "compare_source": {"type": "string"},
        "compare_narration": {"type": "string"},

        "bullets_title": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "bullets_narration": {"type": "string"},

        "verdict_text": {"type": "string"},
        "verdict_narration": {"type": "string"},
        "question_text": {"type": "string"},
        "question_narration": {"type": "string"},
    },
}


def _nullable(node: dict) -> dict:
    """Let one schema node also accept null, keeping its other constraints."""
    out = dict(node)
    t = out.get("type")
    if isinstance(t, str):
        out["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        out["type"] = [*t, "null"]
    if "enum" in out and None not in out["enum"]:
        out["enum"] = [*out["enum"], None]
    return out


def _strict(node):
    """Translate the Ollama schema into Groq's strict dialect.

    Groq's constrained decoder refuses a schema unless EVERY property is
    listed in `required` and every object sets additionalProperties: false.
    An optional field is expressed as a nullable one instead — so the model
    emits `"bullets": null` where Ollama would simply omit the key, and
    _drop_nulls puts the two back on the same footing.
    """
    if not isinstance(node, dict):
        return node
    out = dict(node)
    if out.get("type") == "object" or "properties" in out:
        props = {k: _strict(v) for k, v in out.get("properties", {}).items()}
        optional = set(props) - set(out.get("required", []))
        out["properties"] = {k: (_nullable(v) if k in optional else v)
                             for k, v in props.items()}
        out["required"] = list(props)
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = _strict(out["items"])
    return out


GROQ_SCHEMA = _strict(OLLAMA_SCHEMA)


def _drop_nulls(o):
    """Strip the nulls Groq's strict mode forces on optional fields, so a
    Groq spec and an Ollama spec reach from_flat() looking identical."""
    if isinstance(o, dict):
        return {k: _drop_nulls(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [_drop_nulls(v) for v in o]
    return o


def from_flat(o: dict) -> dict:
    """Turn the flat model output into the scene list the renderer wants.

    Optional blocks (stat, compare, bullets) are included only when they
    actually carry content, so a script with no real figure simply has fewer
    scenes rather than an empty one.
    """
    scenes = [{"type": "hook", "text": o.get("hook_text", ""),
               "narration": o.get("hook_narration", "")}]

    if o.get("stat_label") and o.get("stat_value") is not None:
        prefix, suffix = _unit(o.get("stat_unit"))
        scenes.append({"type": "stat", "label": o["stat_label"],
                       "value": o["stat_value"],
                       "prefix": prefix, "suffix": suffix,
                       "footnote": o.get("stat_footnote"),
                       "source": o.get("stat_source", ""),
                       "narration": o.get("stat_narration", "")})

    if len(o.get("compare_rows") or []) >= 2:
        prefix, suffix = _unit(o.get("compare_unit"))
        scenes.append({"type": "compare",
                       "title": o.get("compare_title") or "Compared",
                       "prefix": prefix, "suffix": suffix,
                       "lower_is_better": bool(
                           o.get("compare_lower_is_better", True)),
                       "rows": o["compare_rows"],
                       "source": o.get("compare_source", ""),
                       "narration": o.get("compare_narration", "")})

    if o.get("bullets"):
        scenes.append({"type": "bullets",
                       "title": o.get("bullets_title") or "Worth knowing",
                       "bullets": o["bullets"],
                       "narration": o.get("bullets_narration", "")})

    scenes += [
        {"type": "verdict", "text": o.get("verdict_text", ""),
         "narration": o.get("verdict_narration", "")},
        {"type": "question", "text": o.get("question_text", ""),
         "narration": o.get("question_narration", "")},
    ]
    return {"title": o.get("title", ""), "kicker": o.get("kicker", ""),
            "description": o.get("description", ""),
            "tags": o.get("tags", []), "scenes": scenes}


def _ollama(prompt: str) -> str:
    """Local writer. Free, but slow on a CPU-only box.

    An 8B model generating ~1500 tokens of JSON runs at maybe 3-6 tokens/sec
    without a GPU, so a single script can take five to eight minutes. The
    default timeout is generous on purpose — a script that took seven minutes
    is still a script, and throwing it away at the six-minute mark wastes the
    compute you already spent.

    Generation is grammar-constrained to OLLAMA_SCHEMA, which removes an entire
    class of failure: no markdown fences, no commentary before the JSON, no
    string where a number belongs, no missing "type" field.
    """
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/generate", timeout=OLLAMA_TIMEOUT,
                          json={"model": OLLAMA_MODEL, "stream": False,
                                "system": SYSTEM, "prompt": prompt,
                                "format": OLLAMA_SCHEMA,
                                # Lower than default: structure beats flair here.
                                "options": {"temperature": 0.6}})
    except requests.Timeout as exc:
        raise RuntimeError(
            f"Ollama did not finish within {OLLAMA_TIMEOUT}s. Either raise "
            f"models.ollama_timeout in config.yaml, or use a smaller model."
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_HOST} — is `ollama serve` "
            f"running?") from exc
    r.raise_for_status()
    return r.json().get("response", "")


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {raw[:200]}")
    return json.loads(raw[start:end + 1])


# ----------------------------------------------------------------- generate --

REPAIR_SCHEMA = _strict({
    "type": "object",
    "properties": {"narrations": {"type": "array",
                                  "items": {"type": "string"}}},
    "required": ["narrations"],
})


def rewrite_narration(spec: dict) -> dict:
    """Second pass: fix the voiceover without touching anything else.

    The first pass juggles structure, facts and phrasing at once and drops
    the phrasing. This call has one job, so it does it. Cheap: a few hundred
    tokens against the free tier's 200k/day.
    """
    scenes = spec.get("scenes") or []
    lines = []
    for i, sc in enumerate(scenes, 1):
        on_screen = sc.get("text") or sc.get("label") or sc.get("title") or ""
        extra = ""
        if sc.get("type") == "stat" and sc.get("value") is not None:
            extra = (f" [the figure is {sc.get('prefix','')} "
                     f"{sc['value']:g} {sc.get('suffix','')}".rstrip() + "]")
        elif sc.get("type") == "compare":
            extra = " [rows: " + "; ".join(
                f"{r.get('name')} {r.get('value')}"
                for r in (sc.get("rows") or [])) + "]"
        lines.append(f"{i}. [{sc.get('type')}] on screen: {on_screen}{extra}\n"
                     f"   current narration: {sc.get('narration','')}")

    prompt = (
        "Rewrite the narration for this video. Return exactly "
        f"{len(scenes)} lines, one per scene, in order.\n\n"
        "Each line must stand alone with the screen off: name the subject and "
        "say the number out loud. Never begin with 'that', 'those', 'these', "
        "'this' or 'it' pointing at the screen. Do not read the on-screen "
        "text back word for word. 12-20 words, one sentence.\n\n"
        "BAD:  That's the sticker price before any fees.\n"
        "GOOD: The cheapest Jetour starts at sixty-nine thousand five hundred "
        "dirhams before fees.\n\n"
        + "\n".join(lines))

    raw = _groq_json(prompt, REPAIR_SCHEMA, "narration_repair")
    out = _extract_json(raw).get("narrations") or []
    if len(out) != len(scenes):
        raise RuntimeError(
            f"repair pass returned {len(out)} lines for {len(scenes)} scenes")
    fixed = json.loads(json.dumps(spec))
    for sc, line in zip(fixed["scenes"], out):
        sc["narration"] = line.strip()
    return fixed


WRITERS = {"groq": _groq, "ollama": _ollama}


def generate(query: str, facts: str = "", writer: str | None = None) -> dict:
    """Write a script for a search query.

    `facts` is anything you've already verified — rows from data/cars.csv, a
    pasted price list, notes from a dealer call. The more you put here, the
    less the model has to reach, and the fewer numbers you have to check.

    `writer` overrides config.yaml's models.writer for a single call, which
    is how the --compare harness runs the same topic through both.
    """
    name = writer or WRITER
    if name not in WRITERS:
        raise RuntimeError(
            f"models.writer is {name!r}; must be one of "
            f"{', '.join(sorted(WRITERS))}. Set it in config.yaml.")

    prompt = (
        f"Search query to answer: \"{query}\"\n\n"
        f"{'Verified facts you may use (prefer these over anything else):' if facts else ''}\n"
        f"{facts}\n\n"
        f"Return JSON in exactly this shape:\n{SCHEMA_HINT}"
    )
    raw = WRITERS[name](prompt)
    spec = _drop_nulls(_extract_json(raw))
    if "scenes" not in spec:          # flat shape from the constrained schema
        spec = from_flat(spec)
    tidy(spec)
    validate(spec)

    # The voiceover is the one thing the first pass reliably gets wrong, and
    # it is cheap to fix in isolation. Only groq can do this — ollama has no
    # second-call budget on a CPU box.
    bad = (leans_on_screen(spec) + unspeakable(spec)
           + misquotes_a_figure(spec) + spells_out_a_price(spec))
    if bad and name == "groq":
        print(f"    narration needs work ({len(bad)} line(s)); rewriting")
        for b in bad:
            print(f"      {b[:96]}")
        try:
            repaired = rewrite_narration(spec)
            tidy(repaired)
            validate(repaired)
            still = (leans_on_screen(repaired) + unspeakable(repaired)
                     + misquotes_a_figure(repaired)
                     + spells_out_a_price(repaired))
            if not still:
                return repaired
            print(f"    repair left {len(still)} line(s) unfixed")
            spec = repaired
        except Exception as exc:                      # noqa: BLE001
            print(f"    repair failed ({type(exc).__name__}), keeping original")
    return spec


# Words that must not be sentence-cased in a title.
_ACRONYMS = {"uae": "UAE", "aed": "AED", "suv": "SUV", "gcc": "GCC",
             "rta": "RTA", "ev": "EV", "phev": "PHEV", "mpg": "MPG",
             "bmw": "BMW", "byd": "BYD", "mg": "MG"}


def tidy(spec: dict) -> None:
    """Clean up what the model reliably gets slightly wrong.

    Asterisks are the renderer's emphasis markup for the hook. If they survive
    into the title they publish to YouTube as literal asterisks, which looks
    like a broken template — and a small model copies the hook into the title
    often enough that hoping is not a strategy.
    """
    title = (spec.get("title") or "").replace("*", "").strip()
    title = re.sub(r"\s{2,}", " ", title)
    words = [_ACRONYMS.get(w.lower(), w) for w in title.split()]
    if words:
        words[0] = words[0] if words[0].isupper() else words[0][:1].upper() + words[0][1:]
    spec["title"] = " ".join(words)[:100]

    # Fill in captions the model left out. These are labels, not claims — a
    # stat with a real sourced number and no heading is a formatting gap, and
    # throwing away six minutes of writing over it is the wrong trade. Scenes
    # with no recoverable *content* still get dropped by validate().
    title_text = spec.get("title") or ""
    for sc in spec.get("scenes", []):
        kind = sc.get("type")
        if kind == "hook" and not sc.get("text"):
            sc["text"] = title_text
        elif kind == "stat" and not sc.get("label"):
            sc["label"] = sc.get("title") or "By the numbers"
        elif kind == "compare" and not sc.get("title"):
            sc["title"] = "Compared"
        elif kind == "bullets" and not sc.get("title"):
            sc["title"] = "Worth knowing"

    for s in spec.get("scenes", []):
        if s.get("type") == "hook" and s.get("text"):
            # "…uae" at the end of an echoed search phrase reads as a typo.
            s["text"] = re.sub(r"\buae\b", "UAE", s["text"])


def _numbers(spec: dict):
    for s in spec.get("scenes", []):
        if s.get("type") == "stat" and s.get("value") is not None:
            yield s["value"]
        for r in s.get("rows", []) or []:
            if r.get("value") is not None:
                yield r["value"]


def validate(spec: dict) -> None:
    """Fail loudly on the shapes the renderer can't draw."""
    if not spec.get("scenes"):
        raise ValueError("script has no scenes")
    kinds = [s.get("type") for s in spec["scenes"]]
    if kinds[0] != "hook":
        raise ValueError("first scene must be the hook")
    if "verdict" not in kinds:
        raise ValueError("script has no verdict — it will not earn engagement")
    if "question" not in kinds:
        raise ValueError("script has no closing question")
    if len(spec.get("title", "")) > 100:
        raise ValueError("title over YouTube's 100 character limit")

    copied = {v for v in _numbers(spec) if int(v) in CANARIES} \
        if all(str(v).replace(".", "").isdigit() for v in _numbers(spec)) else set()
    if copied:
        raise ValueError(
            f"model copied placeholder values from the schema: {sorted(copied)}. "
            "It is inventing content from the template rather than the facts.")

    for s in spec["scenes"]:
        if s.get("type") != "compare":
            continue
        rows = s.get("rows") or []
        if len(rows) < 2:
            raise ValueError(
                "a 'compare' scene has fewer than 2 rows — that is not a "
                "comparison and the bar chart will look broken")

        # Cars a buyer would actually cross-shop. The matcher offers anything
        # in the same segment, so a 139,900 Jetour got put up against a
        # 310,300 Porsche Macan — both "Midsize SUV", both useless to compare.
        # Nobody deciding between them exists.
        #
        # This only applies to CARS. A rule's own bands are supposed to be far
        # apart — the excess cap runs 350 to 1,400, the fines 400 to 3,000 —
        # and that four-to-one gap is the entire point of the video. Applying
        # the cross-shopping test to those rejected every good script about
        # the regulations.
        vals = [float(r["value"]) for r in rows if r.get("value")]
        if (vals and _names_cars(rows)
                and max(vals) > min(vals) * COMPARE_MAX_RATIO):
            raise ValueError(
                f"comparison spans {min(vals):,.0f} to {max(vals):,.0f} — "
                f"more than {COMPARE_MAX_RATIO}x apart. These are not "
                f"alternatives to each other")

    # The JSON schema only mandates `type` and `narration`, so a scene can
    # arrive structurally valid but with nothing to draw. Catch it here with a
    # readable message rather than as a KeyError deep inside the renderer.
    needs = {"hook": ["text"], "verdict": ["text"], "question": ["text"],
             "stat": ["label", "value"], "compare": ["title", "rows"],
             "bullets": ["title", "bullets"]}
    for s in spec["scenes"]:
        for field in needs.get(s.get("type"), []):
            if s.get(field) in (None, "", []):
                raise ValueError(
                    f"'{s['type']}' scene is missing '{field}' — nothing to "
                    f"render")


def attach_sources(spec: dict) -> int:
    """Fill in missing citations by tracing figures back to data/cars.csv.

    A small local model will happily produce a good script and forget the
    `source` field on half the scenes. Binning those wastes a usable script for
    a clerical reason — so where a number matches a row in your data, we attach
    that row's citation ourselves. Numbers that match nothing stay unsourced,
    and those are the ones that should be blocked.

    Returns how many scenes were rescued.
    """
    from . import cars

    filled = 0
    for s in spec.get("scenes", []):
        if s.get("type") not in {"stat", "compare"}:
            continue
        # A source the model wrote itself is only trusted if it points
        # somewhere. Free text like "Dubai Used Car Market Analysis" is a
        # plausible-sounding invention, and it sailed through the old check
        # because the field simply wasn't empty. Traceable data wins over it.
        if "http" in (s.get("source") or ""):
            continue

        # Each figure carries its own label as context, so a price shared by
        # two cars is cited to the one the scene is actually talking about.
        if s["type"] == "stat":
            pairs = [(s.get("value"), s.get("label", ""))]
        else:
            pairs = [(r.get("value"), f"{s.get('title','')} {r.get('name','')}")
                     for r in s.get("rows", [])]

        found = {src for src in
                 (cars.source_for(v, ctx) for v, ctx in pairs) if src}
        if found:
            s["source"] = "; ".join(sorted(found))
            filled += 1
    return filled


def unsourced(spec: dict) -> list[str]:
    """Numeric scenes whose citation isn't one you vouched for.

    Three versions of this check, each defeated by the model in turn:

      1. "the field is non-empty" — it wrote "RTA Insurance Costs and
         Maintenance Fees". Sounds like a source, is not one.
      2. "the field is a URL" — it wrote a real domain with an invented path.
         Looks verifiable, 404s.
      3. "the URL is one of yours" — it cannot invent its way past this,
         because the whitelist is data/cars.csv, which only you write to.

    We are on the third. It means the pipeline can only cover subjects you
    have real data for, which is the correct constraint for a channel whose
    whole proposition is accurate local numbers.
    """
    from . import cars

    allowed = cars.known_source_urls()
    out = []
    for s in spec["scenes"]:
        if s.get("type") not in {"stat", "compare"}:
            continue
        src = s.get("source") or ""
        if not any(url in src for url in allowed):
            out.append(s.get("label") or s.get("title") or s["type"])
    return out


# ------------------------------------------------------------ spec -> scenes --

# A scene nobody is reading is a scene they swipe away from. The published
# video gave 12.1 seconds to a two-bar chart because narration length drove
# duration with no ceiling. Shorts are watched at thumb speed.
MAX_SCENE = 5.0
MIN_SCENE = 1.8


def to_scenes(spec: dict, durations: list[float] | None = None) -> list[R.Scene]:
    """Turn the JSON script into renderable scenes. `durations` (seconds, one
    per scene) normally comes from the length of each narration clip so the
    visuals land on the words."""
    scenes: list[R.Scene] = []
    for i, s in enumerate(spec["scenes"]):
        kind = s["type"]
        d = durations[i] if durations and i < len(durations) else None

        # Every field is fetched defensively: a scene with nothing to draw is
        # skipped rather than crashing a run that has already spent minutes on
        # the script and the voice.
        try:
            if kind == "hook":
                if not s.get("text"):
                    continue
                sc = R.HookScene(s["text"],
                                 kicker=s.get("kicker") or spec.get("kicker"))
            elif kind == "stat":
                if not s.get("label") or s.get("value") is None:
                    continue
                sc = R.StatScene(s["label"], float(s["value"]),
                                 prefix=s.get("prefix", "AED"),
                                 suffix=s.get("suffix", ""),
                                 footnote=s.get("footnote"))
            elif kind == "compare":
                rows = [R.CompareRow(r["name"], float(r["value"]), r.get("note"))
                        for r in (s.get("rows") or [])
                        if r.get("name") and r.get("value") is not None]
                if len(rows) < 2:
                    continue
                sc = R.CompareScene(
                    s.get("title") or "Compared",
                    rows,
                    prefix=s.get("prefix", "AED"),
                    suffix=s.get("suffix", ""),
                    lower_is_better=bool(s.get("lower_is_better", True)))
            elif kind == "bullets":
                bullets = [b for b in (s.get("bullets") or []) if b]
                if not bullets:
                    continue
                sc = R.BulletScene(s.get("title") or "Worth knowing", bullets)
            elif kind == "verdict":
                if not s.get("text"):
                    continue
                sc = R.VerdictScene(s["text"],
                                    kicker=s.get("kicker", "The verdict"))
            elif kind == "question":
                if not s.get("text"):
                    continue
                sc = R.QuestionScene(s["text"])
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        if d:
            sc.duration = min(MAX_SCENE, max(MIN_SCENE, d))
        scenes.append(sc)
    return scenes



def describe(spec: dict) -> str:
    """Assemble the YouTube description FROM the scenes, answer first.

    Two problems this solves.

    The description used to be written separately from the script, so the two
    could drift: a figure corrected on screen stayed wrong in the text under
    it. Deriving the description from the scenes means they cannot disagree.

    And it puts the answer at the top. Sixty-two per cent of this channel's
    traffic is search — someone arrives with a question, and the first two
    lines are the only part of a Shorts description visible without a tap.
    Making them re-watch a 20-second video to find the number they already
    asked for is how a search result turns into a bounce.

    It deliberately does NOT list every figure. A comparison scene already IS
    the table, so the stat scenes that dramatise two of its rows are dropped
    rather than repeated; the same numbers three times reads as padding and
    buries the answer it was supposed to surface.
    """
    def plain(t: str) -> str:
        return (t or "").replace("*", "").strip()

    def fmt(v) -> str:
        return f"{v:,.0f}" if float(v) % 1 == 0 else f"{v:,}"

    scenes = spec.get("scenes") or []
    out: list[str] = []

    # 1. The answer. The verdict IS the answer; it goes above everything.
    answer = next((plain(sc.get("text")) for sc in scenes
                   if sc.get("type") == "verdict" and sc.get("text")), "")
    if answer:
        out.append(answer)

    # 2. The writer's paragraph, for context and for the search index. Any
    #    source line it carries is stripped — sources are appended once, below.
    body = plain(spec.get("description"))
    body = re.split(r"\n\s*(?:Source|Sources)\s*:", body)[0].strip()
    body = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("http")).strip()
    if body and body != answer:
        out.append(body)

    # 3. The figures. A compare scene is the table; prefer it and drop the
    #    stat scenes, which are the same rows enlarged for the screen.
    rows = [sc for sc in scenes if sc.get("type") == "compare"]
    figures: list[str] = []
    if rows:
        for sc in rows:
            pre = (sc.get("prefix") or "").strip()
            for r in (sc.get("rows") or []):
                if not r.get("name") or r.get("value") is None:
                    continue
                note = f"  ({plain(r['note'])})" if r.get("note") else ""
                figures.append(f"\u2022 {plain(r['name'])}: "
                               f"{(pre + ' ' if pre else '')}"
                               f"{fmt(r['value'])}{note}")
    else:
        for sc in scenes:
            if sc.get("type") != "stat" or sc.get("value") is None:
                continue
            pre = (sc.get("prefix") or "").strip()
            suf = (sc.get("suffix") or "").strip()
            figures.append(f"\u2022 {plain(sc.get('label'))}: "
                           f"{(pre + ' ' if pre else '')}{fmt(sc['value'])}"
                           f"{(' ' + suf if suf else '')}".rstrip())
        if not figures:
            for sc in scenes:
                if sc.get("type") == "bullets":
                    figures += [f"\u2022 {plain(b)}"
                                for b in (sc.get("bullets") or []) if b]
    if figures:
        out.append("\n".join(figures))

    # 4. Where every one of those numbers came from.
    srcs = sorted({u for sc in scenes
                   for u in [(sc.get("source") or "").strip()]
                   if u.startswith("http")})
    if srcs:
        out.append("Source:\n" + "\n".join(srcs))

    out.append(R.T.END_CTA)
    return "\n\n".join(out)[:4900]



# A narration line opening with one of these is pointing at the screen. The
# listener has heard nothing yet, so the sentence refers to nothing.
_DEICTIC = ("that ", "that's", "thats", "those ", "these ", "this ",
            "it ", "it's", "its ")


# Written forms a speech engine mangles. "AED 30,000" becomes "ay-ee-dee
# thirty thousand"; "90k" becomes "ninety kay". The on-screen text wants
# these; the voiceover never does.
_UNSPEAKABLE = (
    (re.compile(r"\bAED\b"), 'say "dirhams"'),
    (re.compile(r"\bDhs?\b", re.I), 'say "dirhams"'),
    (re.compile(r"\d\s*k\b"), 'spell the thousands out'),
    (re.compile(r"%"), 'say "per cent"'),
    (re.compile(r"\bkm/l\b", re.I), 'say "kilometres per litre"'),
    (re.compile(r"\bhp\b"), 'say "horsepower"'),
)


def unspeakable(spec: dict) -> list[str]:
    """Narration a human voice cannot read cleanly."""
    bad = []
    for sc in spec.get("scenes") or []:
        n = (sc.get("narration") or "").strip()
        for pat, fix in _UNSPEAKABLE:
            if pat.search(n):
                bad.append(f"{n}   -> {fix}")
                break
    return bad


# The writer said "39,900" for a 139,900 car, "77,900" for 177,900 and
# "99,900" for 199,900 — three prices in one sentence, each exactly 100,000
# light. That is a dropped leading digit group, and it has a signature: the
# spoken figure differs from a real one by a clean power of ten.
#
# Checking instead that EVERY spoken number appears in the data would flag
# model years, seat counts and honest arithmetic like "the GXR adds 15,000",
# so this looks only for the truncation pattern.
_DROPPED_GROUPS = (10_000, 100_000, 1_000_000)


# A price written in words defeats misquotes_a_figure(), which finds digit
# strings. "thirty-nine thousand nine hundred" for a 139,900 car contains no
# digits at all, so the truncation that produced it would pass unseen. Force
# the figure into digits and the detector can do its job.
_SPELLED_BIG = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"[\w\s-]{0,40}?\b(?:thousand|million)\b", re.I)


def spells_out_a_price(spec: dict) -> list[str]:
    """Narration that writes a large figure in words instead of digits."""
    bad = []
    for sc in spec.get("scenes") or []:
        n = _norm(sc.get("narration") or "")
        m = _SPELLED_BIG.search(n)
        if m:
            bad.append(f"{n}   -> write \"{m.group(0)}\" as digits so the "
                       f"figure can be checked against the data")
    return bad


def misquotes_a_figure(spec: dict) -> list[str]:
    """Spoken prices that look like a real figure with a digit group lost."""
    bad = []
    for sc in spec.get("scenes") or []:
        n = _norm(sc.get("narration") or "")
        if not n:
            continue
        known = set()
        if sc.get("value") is not None:
            known.add(int(float(sc["value"])))
        for row in sc.get("rows") or []:
            if row.get("value") is not None:
                known.add(int(float(row["value"])))
        if not known:
            continue
        for m in re.findall(r"\d[\d,]{2,}", n):
            said = int(m.replace(",", ""))
            if said in known or 1990 <= said <= 2035:
                continue                      # exact, or a model year
            hits = [k for k in known
                    if any(k - said == g for g in _DROPPED_GROUPS)]
            if hits:
                bad.append(f"{n}   -> says {said:,}, but the scene holds "
                           f"{hits[0]:,} - a digit group was dropped")
    return bad


def leans_on_screen(spec: dict) -> list[str]:
    """Narration lines that only make sense while looking at the frame.

    SYSTEM used to ask for narration that "complements the on-screen text",
    and the writer obliged with "That's the sticker price before any fees" —
    six scenes of pointing at numbers the viewer never heard. Prompts are
    advisory; this is not.
    """
    bad = []
    for sc in spec.get("scenes") or []:
        n = (sc.get("narration") or "").strip()
        if not n:
            continue
        low = n.lower()
        if any(low.startswith(d) for d in _DEICTIC):
            bad.append(n)
            continue
        # A stat scene has to speak its own figure.
        if sc.get("type") == "stat" and sc.get("value") is not None:
            v = float(sc["value"])
            digits = f"{int(v):,}"
            spoken = {digits, digits.replace(",", ""), str(int(v)),
                      f"{v:g}"}
            if not any(t in n for t in spoken) and not _says_number(n, v):
                bad.append(n)
    return bad


# A price read aloud is spelled out — "sixty-nine thousand five hundred" —
# so searching the narration for the digits 69500 finds nothing. Spell the
# figure the way a person would say it and look for that instead.
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety")


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + (f"-{_ONES[o]}" if o else "")


def _spell(n: int) -> str:
    """English for a whole number up to the millions. Good enough for prices."""
    if n < 100:
        return _under_hundred(n)
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{_ONES[h]} hundred" + (f" {_under_hundred(r)}" if r else "")
    for scale, word in ((1_000_000, "million"), (1_000, "thousand")):
        if n >= scale:
            head, rest = divmod(n, scale)
            out = f"{_spell(head)} {word}"
            return out + (f" {_spell(rest)}" if rest else "")
    return str(n)


# Models emit U+2011/2013/2014 where we write "-", so "thirty\u2011nine" never
# matched the ASCII "thirty-nine" we generate. That flagged correct lines.
_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-",
                         "\u2013": "-", "\u2014": "-", "\u2212": "-",
                         "\u00a0": " "})


def _norm(text: str) -> str:
    return text.translate(_DASHES)


def _says_number(text: str, value: float) -> bool:
    """Does this line actually state the figure, in digits or in words?"""
    low = _norm(text).lower().replace(",", "")
    n = int(value)
    if str(n) in low:
        return True
    spoken = _norm(_spell(n))
    if spoken in low:
        return True
    # "sixty-nine thousand five hundred" may be shortened to "sixty-nine
    # thousand" or "under seventy thousand" in natural speech. Accept the
    # leading group plus the right scale word.
    head = spoken.split(" thousand")[0].split(" million")[0]
    for word in ("million", "thousand"):
        if word in spoken and word in low and head in low:
            return True
    return False


def has_evidence(spec: dict) -> bool:
    """Does this script actually contain a fact, or only an assertion?

    unsourced() checks that every figure can be traced. It cannot catch the
    opposite failure: a script with NO figures at all. A spec of hook, verdict
    and question passes the sourcing gate perfectly — there is nothing to
    source — and renders an eight-second video that claims something and shows
    no evidence for it.

    That is the shape 74 drafts quietly took, because every individual check
    passed. A data short with no data is not a draft.
    """
    for sc in spec.get("scenes") or []:
        if sc.get("type") == "stat" and sc.get("value") is not None:
            return True
        if sc.get("type") == "compare" and len(sc.get("rows") or []) >= 2:
            return True
    return False

def narrations(spec: dict) -> list[str]:
    return [s.get("narration", "") for s in spec["scenes"]]


def compare(query: str, facts: str = "") -> dict:
    """Write the same topic with both writers and report the difference.

    This exists because "is the bigger model actually better" is not a
    question to settle from benchmarks. The things that matter here are
    whether all six scenes get built, whether the numbers survive sourcing,
    and how long you wait — so measure those, on a real topic, with the real
    schema and the real facts.
    """
    out = {}
    for name in ("ollama", "groq"):
        row = {"writer": name}
        started = time.monotonic()
        try:
            spec = generate(query, facts=facts, writer=name)
            row["seconds"] = time.monotonic() - started
            row["spec"] = spec
            row["scenes"] = [sc["type"] for sc in spec["scenes"]]
            row["evidence"] = has_evidence(spec)
            row["cited"] = attach_sources(spec)
            row["unsourced"] = unsourced(spec)
            row["words"] = sum(len(n.split()) for n in narrations(spec))
        except Exception as exc:                      # noqa: BLE001
            row["seconds"] = time.monotonic() - started
            row["error"] = f"{type(exc).__name__}: {exc}"
        out[name] = row
    return out


def _print_comparison(res: dict) -> None:
    print("\n" + "=" * 68)
    for name, row in res.items():
        print(f"\n{name.upper()}  ({row['seconds']:.1f}s)")
        print("-" * 68)
        if "error" in row:
            print(f"  FAILED  {row['error']}")
            continue
        print(f"  title      : {row['spec'].get('title')}")
        print(f"  scenes     : {len(row['scenes'])}  {row['scenes']}")
        print(f"  evidence   : {'yes' if row['evidence'] else 'NO — would be binned'}")
        print(f"  auto-cited : {row['cited']} scene(s)")
        print(f"  unsourced  : {row['unsourced'] or 'none'}")
        print(f"  narration  : {row['words']} words")
        print()
        for line in narrations(row["spec"]):
            print(f"    {line}")

    print("\n" + "=" * 68)
    ok = {n: r for n, r in res.items() if "error" not in r}
    if len(ok) == 2:
        o, g = ok["ollama"], ok["groq"]
        print(f"  scenes    ollama {len(o['scenes'])}  vs  groq {len(g['scenes'])}")
        print(f"  evidence  ollama {o['evidence']}  vs  groq {g['evidence']}")
        print(f"  words     ollama {o['words']}  vs  groq {g['words']}")
        print(f"  seconds   ollama {o['seconds']:.1f}  vs  groq {g['seconds']:.1f}"
              f"   ({o['seconds'] / max(g['seconds'], 0.1):.0f}x)")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    # Debug a single topic without rendering anything:
    #   python -m autoedits.script "nissan patrol vs land cruiser uae"
    #
    # Or write it with BOTH writers and compare them:
    #   python -m autoedits.script --compare "salik tolls dubai"
    #
    # Or just hit the writer once and see exactly what came back:
    #   python -m autoedits.script --probe "car expenses in dubai"
    import sys

    from . import cars

    args = [a for a in sys.argv[1:] if a not in ("--compare", "--probe")]
    query = " ".join(args) or "nissan patrol vs land cruiser uae"
    facts = cars.facts_for(query)
    print(f"query : {query}")
    print(f"facts : {len(facts.splitlines())} row(s) from cars.csv\n")

    if "--probe" in sys.argv:
        # Writer only. No voice, no render — so a failing topic costs one API
        # call instead of a ten-minute Chatterbox run.
        print(f"writer : {WRITER}")
        try:
            spec = generate(query, facts=facts)
        except Exception as exc:                      # noqa: BLE001
            print(f"\nFAILED  {type(exc).__name__}")
            print(f"{exc}")
            if LAST_CALL:
                print(f"\nlast call: {LAST_CALL}")
            sys.exit(1)
        if LAST_CALL:
            print(f"groq   : {LAST_CALL}")
        print(f"scenes : {len(spec['scenes'])}  "
              f"{[x['type'] for x in spec['scenes']]}")
        print(f"evidence: {has_evidence(spec)}")
        lines = narrations(spec)
        from .voice import syllables as _syl
        total = sum(_syl(n) for n in lines) / 5.6
        print(f"spoken : {sum(len(n.split()) for n in lines)} words across "
              f"{len(lines)} lines, ~{total:.0f}s at 5.6 syl/sec")
        for n in lines:
            print(f"    {n}")
        sys.exit(0)

    if "--compare" in sys.argv:
        # Both writers, same topic, same facts, same schema.
        from .config import WORK
        res = compare(query, facts=facts)
        _print_comparison(res)
        for name, row in res.items():
            if "spec" in row:
                path = WORK / f"compare-{name}.json"
                path.write_text(json.dumps(row["spec"], indent=2,
                                           ensure_ascii=False))
                print(f"  saved {path}")
        sys.exit(0)

    spec = generate(query, facts=facts)
    rescued = attach_sources(spec)
    missing = unsourced(spec)

    print(json.dumps(spec, indent=2, ensure_ascii=False))
    print(f"\ntitle      : {spec.get('title')}")
    print(f"scenes     : {[s['type'] for s in spec['scenes']]}")
    print(f"auto-cited : {rescued} scene(s) matched to cars.csv")
    print(f"unsourced  : {missing or 'none — this script would build'}")
