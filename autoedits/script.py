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
- A NUMBER COSTS TIME. "139,900" is four characters and eleven syllables
  spoken, about three seconds. Two six-figure prices in one line is ten
  seconds of audio, longer than any scene holds, and the end of the script
  gets cut. So in a compare line prefer the GAPS: "undercuts the 70 by
  38,000 and the Prado by 60,000" says more than listing three prices and
  takes four seconds less. Count 12-20 words as the ceiling, not the target,
  and spend fewer words the more digits a line carries.
- EVERY LINE MUST STAND ALONE WITH THE SCREEN OFF. A listener who only hears
  the audio must still get the fact. Name the subject and say the figure,
  phrased the way a person would speak it.
- Never open a line with "that", "those", "these", "this" or "it" pointing at
  something only the screen shows. "That's the sticker price" is a caption,
  not narration: the listener never heard a price. Write "The cheapest Jetour
  starts at 69,500 dirhams" instead.
- Do not read the on-screen text back word for word either. Say the same fact
  differently, with the subject named. Standing alone and being a verbatim
  reading are two different things — you need the first, not the second.
- The stat scene's narration MUST contain the stat's own number. A stat scene
  whose voiceover never says the figure is a failed scene.
- The compare scene's narration MUST carry at least TWO real figures: two of
  its own row values, or two exact GAPS between them, or one of each. The
  screen draws the bars; the listener gets one sentence. "All three start
  under 90,000" and "SUVs start higher but can vary" are not comparisons,
  because the difference between two numbers IS the story and nobody can
  hear a difference from one number. Both of these are right:
    "The FJ starts at 139,900 against the 70's 177,900."
    "The FJ undercuts the 70 by 38,000 and the Prado by 60,000."
  The second is usually the better line. Prefer it when the gaps are clean.
- The bullets scene's narration MUST name at least one amount from the facts.
  "Insurance prices can differ, so always compare quotes" and "Toyota's
  configurator shows monthly payments" have the shape of a fact and none of
  the content. This scene exists to say what the price hides, which is only
  worth 5 seconds if it says how much. If the facts hold no second figure
  worth naming, LEAVE THIS SCENE OUT — only hook, verdict and question are
  required.
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
    # bike_rules.csv
    "lanes":   ("", " lanes"),
    "lane":    ("", " lane"),
    "hours":   ("", " hours"),
    "lectures": ("", " lectures"),
    "km/h":    ("", " km/h"),
    "black points": ("", " points"),
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
              for r in cars.load() + cars.load_bikes()} - {""}
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


def _fit_completion(prompt: str, want: int | None = None,
                    floor: int | None = None, system: str | None = None) -> int:
    """How many completion tokens we may reserve without a 413.

    max_completion_tokens is not a free ceiling: Groq charges it against
    tokens-per-minute up front. A 4000 reservation on top of a fact-rich
    prompt asked for 8114 of an 8000 limit and the request was rejected
    outright, so the reservation has to shrink to fit the prompt.

    `want` is for calls that KNOW they need less than a full script. The
    repair pass returns six one-sentence lines — about 200 tokens — and was
    reserving 3,316 of the same 8,000-per-minute budget the generate call
    had just spent 4,269 of. That is why every repair hit three 429s in a
    row: not too fast, just a reservation eleven times the size of the
    answer.
    """
    est = int((len(system if system is not None else SYSTEM) + len(prompt))
              / 4 * TOKEN_FUDGE)
    room = GROQ_TPM - TPM_RESERVE - est
    if want is not None:
        return max(1, min(want, room))
    if room < (floor or MIN_COMPLETION):
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


def _groq_json(prompt: str, schema: dict, schema_name: str,
               want: int | None = None, system: str | None = None) -> str:
    """Free-tier Groq. Uses strict structured outputs, so the schema is
    enforced by constrained decoding exactly as Ollama's grammar is — the
    model cannot return a script with a field missing.

    The free tier's ceiling is tokens-per-minute, not per-day, so a 429 here
    means "you went too fast", not "you ran out". Wait and retry.
    """
    require(GROQ_KEY, "GROQ_API_KEY")
    # SYSTEM is the script-WRITING brief: scene types, the schema, sourcing
    # rules. A call that does not write a script has no use for it, and
    # sending it anyway cost 2,602 tokens of an 8,000-per-minute budget on
    # every repair — which is what left the repair with 900 completion
    # tokens, too few for this model to finish a valid JSON document, and
    # what produced the 429s before it.
    system = SYSTEM if system is None else system
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        # Lower than default: structure beats flair here.
        "temperature": 0.6,
        "max_completion_tokens": _fit_completion(prompt, want, system=system),
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
                f"  prompt was {len(system) + len(prompt)} chars "
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
        # Same hazard, same fix.
    "tags": {"type": "array", "minItems": 3, "maxItems": 10,
             "items": {"type": "string"}},

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
        # Bounded deliberately. An unbounded array gives the constrained decoder
    # no reason to ever close it: on 2026-10-10 the model tried, could not
    # emit a bare "]", wrote it as a STRING element instead, and then poured
    # bullets_narration, verdict_text and question_text into the array as
    # further items. Groq rejected the whole script for missing properties.
    # compare_rows has carried bounds from the start and has never done this.
    "bullets": {"type": "array", "minItems": 2, "maxItems": 4,
                "items": {"type": "string"}},
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

# Everything this call needs, and nothing about writing a script. The one
# rule carried over from SYSTEM is the abbreviation rule, because unspeakable()
# still checks repaired lines and a rewrite that reintroduces "AED" fails it.
REPAIR_SYSTEM = (
    "You rewrite voiceover lines for a short video. You return only JSON "
    "matching the schema you are given, with no commentary.\n"
    "The lines are read aloud by a speech engine, so spell abbreviations out: "
    "\"dirhams\", never \"AED\"; \"per cent\", never \"%\"; \"kilometres\", never "
    "\"km\"; \"horsepower\", never \"hp\".\n"
    "You never introduce a number that you were not given."
)

REPAIR_SCHEMA = _strict({
    "type": "object",
    "properties": {"narrations": {"type": "array",
                                  "items": {"type": "string"}}},
    "required": ["narrations"],
})


_SUPERLATIVE = re.compile(
    r"(?i)\b(cheapest|least expensive|most affordable|lowest[- ]priced|"
    r"lowest (?:entry )?price)\b")
# What the title's category words mean in the data's own vocabulary.
_CATEGORY_ALIAS = {"ev": "electric", "evs": "electric", "suvs": "suv",
                   "hybrids": "hybrid", "sedans": "sedan", "pickups": "pickup",
                   "hatchbacks": "hatchback", "superbike": "sport",
                   "tourer": "touring", "retro": "classic", "adv": "adventure",
                   "dirt": "off", "offroad": "off", "enduro": "off",
                   "motocross": "off"}


def false_superlative(spec: dict) -> list[str]:
    """"The cheapest X" has to BE the cheapest X — in the whole file.

    The writer can only see the twelve rows retrieval hands it, and it calls
    the cheapest of those "the cheapest in Dubai". Two drafts on one night
    named two different cheapest electric cars, 74,900 and 109,900, because
    they were handed two different twelve — and the second was false by this
    project's own data, with seven EVs below it. The check reads the claim
    against every usable row, not against what the writer happened to see.

    Scoped to market-wide claims. A title naming a brand ("Toyota GR prices -
    which one is cheapest") is a claim about that brand's own range, which
    retrieval does fetch in full, so it is left alone.
    """
    from .cars import (load, load_bikes, usable, _tokens, _phrase_in,
                       CATEGORY_WORDS, BIKE_CATEGORY_WORDS, is_bike_query,
                       wants_offroad, road_bike)

    scenes = spec.get("scenes") or []
    title = spec.get("title") or ""
    texts = [title] + [f"{sc.get('label', '')} {sc.get('narration', '')}"
                       for sc in scenes]
    if not any(_SUPERLATIVE.search(t) for t in texts):
        return []

    # A motorcycle title is checked against motorcycles. "The cheapest
    # motorbike in the UAE" at 4,990 must not fail because cars.csv has
    # nothing under 35,000 — nor pass because it does.
    bike = is_bike_query(title)
    rows = load_bikes() if bike else load()
    if bike and not wants_offroad(title):
        rows = [r for r in rows if road_bike(r)]
    words = CATEGORY_WORDS | BIKE_CATEGORY_WORDS if bike else CATEGORY_WORDS
    lowered = title.lower()
    if any(_phrase_in(lowered, r["brand"].lower()) for r in rows if r.get("brand")):
        return []
    # A full multi-word model name scopes the claim the same way a brand
    # does: "Land Cruiser FJ price compared to other UAE models" was refused
    # for calling the FJ the cheapest car in the UAE. One-word model names
    # are ordinary English ("city", "patrol") and do not count.
    if any(len(r["model"].split()) >= 2 and _phrase_in(lowered, r["model"].lower())
           for r in rows if r.get("model")):
        return []

    want = {_CATEGORY_ALIAS.get(w, w) for w in _tokens(title) & words}

    # The figure the script presents as the cheapest: its stat, or failing
    # that the lowest bar in its comparison.
    anchor, claimed = None, None
    for sc in scenes:
        if sc.get("type") == "stat" and sc.get("value") is not None:
            anchor, claimed = sc, float(sc["value"])
            break
    if claimed is None:
        for sc in scenes:
            vals = [float(r["value"]) for r in sc.get("rows") or []
                    if r.get("value") is not None]
            if sc.get("type") == "compare" and vals:
                anchor, claimed = sc, min(vals)
                break
    if claimed is None:
        return []

    pool = []
    for r in rows:
        if not usable(r) or not r.get("price_from_aed"):
            continue
        kinds = _tokens(r.get("segment", ""), r.get("powertrain", ""))
        if want <= kinds:
            pool.append(r)
    if not pool:
        return []
    cheaper = sorted((r for r in pool if int(r["price_from_aed"]) < claimed),
                     key=lambda r: int(r["price_from_aed"]))
    if not cheaper:
        return []

    best = cheaper[0]
    noun = "motorcycle" if bike else "car"
    what = " ".join(sorted(want)) + f" {noun}" if want else noun
    return [f"{_norm(anchor.get('narration') or title)}   -> calls "
            f"{int(claimed):,} the cheapest {what}, but this project's data has "
            f"the {best['brand']} {best['model']} at "
            f"{int(best['price_from_aed']):,}"
            + (f" and {len(cheaper) - 1} more below {int(claimed):,}"
               if len(cheaper) > 1 else "")
            + ". Either drop 'cheapest' or use the real cheapest"]


# What the writer was told, which must never be what the viewer hears. Six
# published videos read template text aloud — "Answer in four words." (#30,
# #37, #81), "Quickly address the hook with facts." and "Ask viewers for
# their current situation." (#63), "Here's what the price hides." (#5) — and
# #3 and #23 showed "What the price hides" as an on-screen heading. The
# CANARIES caught the template's placeholder NUMBERS; nothing caught its words.
def _template_phrases() -> tuple[set[str], set[str]]:
    """(long, short): long ones match anywhere; short ones only a whole field."""
    long_, short = set(), set()
    for ph in re.findall(r"<([^<>]+)>", SCHEMA_HINT):
        ph = re.sub(r"\s+", " ", ph.lower().replace("\u2019", "'")).strip(" .")
        if "|" in ph or "url" in ph or ph in ("angle brackets",):
            continue
        # "what the number is" reads like ordinary English, so it only
        # counts as a leak when it is the whole field.
        natural = ph in ("what the number is",)
        (long_ if len(ph.split()) >= 4 and not natural else short).add(ph)
    long_ |= {"answer in four words", "answer in 4 words", "ask viewers",
              "ask the viewer", "address the hook", "quickly address",
              "in four words or less", "one sentence only"}
    return long_, short


_TEMPLATE_LONG, _TEMPLATE_SHORT = _template_phrases()


def reads_the_template(spec: dict) -> list[str]:
    """Lines that repeat the writing template instead of saying something."""
    bad = []
    fields = [("title", spec.get("title")), ("kicker", spec.get("kicker"))]
    for sc in spec.get("scenes") or []:
        for f in ("title", "label", "text", "narration"):
            fields.append((f, sc.get(f)))
        fields += [("bullet", b) for b in sc.get("bullets") or []]
        fields += [("row", r.get("name")) for r in sc.get("rows") or []]
        fields += [("note", r.get("note")) for r in sc.get("rows") or []]
    for name, text in fields:
        if not text or not isinstance(text, str):
            continue
        low = re.sub(r"\s+", " ", text.lower().replace("\u2019", "'")).replace("*", "")
        whole = low.strip(" .!?")
        hit = next((p for p in _TEMPLATE_LONG if p in low), None) or \
            (whole if whole in _TEMPLATE_SHORT else None)
        if hit:
            bad.append(f"{_norm(text)[:80]}   -> repeats the writing template "
                       f"({hit!r}); say the actual thing instead")
    return bad


def scenes_of(spec: dict) -> list[dict]:
    return spec.get("scenes") or []


def _narration_faults(spec: dict, facts: str = "") -> list[str]:
    """Every narration check, in one place.

    They were listed out twice — once before the repair and once after — and
    a check added to one list and not the other would have silently stopped
    applying to repaired scripts.
    """
    return (leans_on_screen(spec) + unspeakable(spec)
            + misquotes_a_figure(spec) + spells_out_a_price(spec)
            + invents_a_figure(spec, facts)
            + compare_says_nothing(spec) + bullets_say_nothing(spec, facts)
            + too_long_to_speak(spec) + false_superlative(spec)
            + reads_the_template(spec))


# How much of a complaint string to match a narration against. The checks
# report either the whole line or its first 80 characters, so comparing a
# prefix is the only thing that works for both.
_MATCH = 60


def _complaints_by_line(spec: dict,
                        bad: list[str]) -> tuple[dict[int, list[str]], int]:
    """Which scene each complaint is about, and how many did not map.

    The checks report the offending narration and the fix. Mapping that back
    to a scene index is what lets the repair prompt mark the lines that are
    actually wrong — without it the model was handed six lines, told some
    were broken, and rewrote all six.

    Both sides go through _norm(). The checks report the NORMALISED line and
    this compared it against the raw one, so any narration containing a
    non-breaking hyphen failed to map — "thirty\u2011nine" against
    "thirty-nine", a mismatch 44 characters in. The line was then labelled
    "OK: return this line unchanged", the model obeyed, and the same
    spelled-out price survived every repair on every re-roll. It looked like
    the model ignoring an instruction and was the instruction being wrong.

    The unmapped count is the caller's cue to stop trusting the OK labels.
    """
    out: dict[int, list[str]] = {}
    unmapped = 0
    for entry in bad:
        text, _, reason = entry.partition("   -> ")
        head = _norm(text).strip()[:_MATCH]
        for i, sc in enumerate(spec.get("scenes") or []):
            if head and _norm(sc.get("narration") or "").strip()[:_MATCH] == head:
                out.setdefault(i, []).append(reason.strip() or
                                             "does not stand alone without the screen")
                break
        else:
            unmapped += 1
    return out, unmapped


def rewrite_narration(spec: dict, bad: list[str] | None = None,
                      facts: str = "") -> dict:
    """Second pass: fix the voiceover without touching anything else.

    The first pass juggles structure, facts and phrasing at once and drops
    the phrasing. This call has one job, so it does it. Cheap: a few hundred
    tokens against the free tier's 200k/day.

    `bad` is the output of the narration checks. Passing it is what makes the
    difference between a repair and a re-roll: without it this call got no
    feedback at all, rewrote every line including the five that were already
    fine, and reliably came back with MORE failures than it started with.
    """
    scenes = spec.get("scenes") or []
    flagged, unmapped = _complaints_by_line(spec, bad or [])
    # A complaint we could not place means the OK labels are incomplete, and
    # an incomplete OK label is worse than none: it tells the model to keep a
    # line that is broken. Fall back to rewriting everything, which the
    # revert-on-regression merge in generate() now makes safe.
    if unmapped:
        print(f"    {unmapped} complaint(s) could not be matched to a scene; "
              f"rewriting every line")
        flagged = {i: ["see the rules above"] for i in range(len(scenes))}
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
        block = (f"{i}. [{sc.get('type')}] on screen: {on_screen}{extra}\n"
                 f"   current narration: {sc.get('narration','')}")
        for c in flagged.get(i - 1, []):
            block += f"\n   PROBLEM: {c}"
        if i - 1 not in flagged:
            block += "\n   OK: return this line unchanged."
        lines.append(block)

    # Every figure the rewrite is allowed to use. The repair pass had no idea
    # what was sourced and filled a gap with "registration of around 5,000
    # dirhams" — a number that exists in no file in this project.
    allowed = sorted(_structured_values(spec) |
                     {int(m.replace(",", ""))
                      for m in re.findall(r"\d[\d,]{2,}", facts or "")})

    prompt = (
        "Fix the narration for this video. Return exactly "
        f"{len(scenes)} lines, one per scene, in order.\n\n"
        "Lines marked OK are already correct — copy them back word for word. "
        "Rewrite ONLY the lines marked PROBLEM, and change nothing else.\n\n"
        "Rules for a line you rewrite:\n"
        "- It must stand alone with the screen off: name the subject and say "
        "the figure. Never begin with 'that', 'those', 'these', 'this' or "
        "'it' pointing at the screen.\n"
        "- Write every number in digits with comma groups: 139,900 — never "
        "in words. Spelled-out numbers get truncated by the voice and "
        "\"one hundred thirty-nine thousand nine hundred\" came out as "
        "thirty-nine thousand nine hundred.\n"
        "- Use ONLY these figures. Do not introduce any other number, and do "
        "not estimate, round or add fees, taxes or extras:\n  "
        + (", ".join(f"{v:,}" for v in allowed) or "(none)") + "\n"
        "- Do not read the on-screen text back word for word. 12-20 words, "
        "one sentence.\n\n"
        "BAD:   That's the sticker price before any fees.\n"
        "BAD:   It starts at sixty-nine thousand five hundred dirhams.\n"
        "GOOD:  The cheapest Jetour starts at 69,500 dirhams before fees.\n\n"
        + "\n".join(lines))

    # Six one-sentence lines, not a script — but this model spends
    # completion tokens reasoning before it answers, so the budget has to
    # cover that too. 900 did not: two of three topics in one night died on
    # "max completion tokens reached before generating a valid document".
    # The room comes from not shipping SYSTEM with a call that cannot use it.
    raw = _groq_json(prompt, REPAIR_SCHEMA, "narration_repair",
                     want=2200, system=REPAIR_SYSTEM)
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
    """Write a script for a search query, then check its description.

    The narration has nine checks; the writer's description paragraph had
    none, and it publishes under the video just the same. Draft #134's said
    "the cheapest BYD model we found costs 109,900" two lines above its own
    89,900 Sealion 5. Failing sentences are dropped rather than the whole
    build: the rest of the description is assembled from scenes that have
    already passed every check, so it stays honest without them.
    """
    spec = _generate(query, facts, writer)
    dropped = clean_description(spec, facts)
    if dropped:
        print(f"    description: dropped {len(dropped)} sentence(s) that failed "
              f"the figure checks")
        for d in dropped:
            print(f"      {d[:150]}")
    return spec


REPLY_TARGET = 2500        # successful scripts use about 2,400 tokens
MIN_FACT_ROWS = 4


def _reply_room(prompt: str) -> int:
    return GROQ_TPM - TPM_RESERVE - int((len(SYSTEM) + len(prompt)) / 4 * TOKEN_FUDGE)


def fit_facts(facts: str, build) -> str:
    """Drop the lowest-ranked fact rows until the reply has room.

    The writer call reserves its reply against the same 8,000 tokens a minute
    as the prompt. Rows with long notes (Ducati's price lists, the Land
    Cruiser trims) pushed 19 of 173 buildable topics under the 2,200 floor
    on 29 Oct, and _fit_completion refuses those outright. facts_for ranks
    best first, so the rows cut are the ones least likely to be used.
    """
    rows = facts.splitlines()
    before = len(rows)
    while len(rows) > MIN_FACT_ROWS and _reply_room(build("\n".join(rows))) < REPLY_TARGET:
        rows.pop()
    if len(rows) < before:
        print(f"    facts trimmed {before} -> {len(rows)} rows so the reply "
              f"fits the {GROQ_TPM}/min budget")
    return "\n".join(rows)


def _generate(query: str, facts: str = "", writer: str | None = None) -> dict:
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

    from .cars import is_bike_query
    # SYSTEM is written for cars and is near its token budget, so the bike
    # brief rides in the user turn, only on the nights that need it.
    bike_brief = (
        "This video is about MOTORCYCLES in the UAE, not cars. Every price "
        "below is a motorcycle or scooter. Say motorcycle, bike or scooter, "
        "never car. Speeds in narration are \"kilometres an hour\".\n\n"
        if is_bike_query(query) else "")
    def build(facts: str) -> str:
        return (
            f"{bike_brief}"
            f"Search query to answer: \"{query}\"\n\n"
            f"{'Verified facts you may use (prefer these over anything else):' if facts else ''}\n"
            f"{facts}\n\n"
            f"Return JSON in exactly this shape:\n{SCHEMA_HINT}"
        )
    if name == "groq":
        facts = fit_facts(facts, build)
    prompt = build(facts)
    raw = WRITERS[name](prompt)
    spec = _drop_nulls(_extract_json(raw))
    if "scenes" not in spec:          # flat shape from the constrained schema
        spec = from_flat(spec)
    tidy(spec)
    validate(spec)

    # The voiceover is the one thing the first pass reliably gets wrong, and
    # it is cheap to fix in isolation. Only groq can do this — ollama has no
    # second-call budget on a CPU box.
    bad = _narration_faults(spec, facts)
    if bad and name == "groq":
        print(f"    narration needs work ({len(bad)} line(s)); rewriting")
        for b in bad:
            print(f"      {b[:96]}")
        try:
            repaired = rewrite_narration(spec, bad, facts)
            tidy(repaired)
            validate(repaired)
            still = _narration_faults(repaired, facts)
            if not still:
                return repaired

            # Keep a rewritten line only if it is actually clean. The repair
            # pass used to be allowed to hand back anything: on the FJ script
            # it fixed one demonstrative and returned two spelled-out prices
            # and an invented 5,000 for registration, so one fault became
            # three. Reverting the lines it got wrong makes a repair unable
            # to lose ground — the worst it can now do is nothing.
            broken = set(_complaints_by_line(repaired, still)[0])
            merged = json.loads(json.dumps(repaired))
            reverted = 0
            for i, (sc, orig) in enumerate(zip(merged["scenes"],
                                               spec["scenes"])):
                if i in broken and sc["narration"] != orig["narration"]:
                    sc["narration"] = orig["narration"]
                    reverted += 1
            if reverted:
                print(f"    kept {len(scenes_of(spec)) - reverted} rewritten "
                      f"line(s); {reverted} came back worse and were reverted")
            merged_bad = _narration_faults(merged, facts)
            if not merged_bad:
                return merged
            spec, bad = merged, merged_bad
        except RuntimeError as exc:
            print(f"    repair call failed ({exc})")

    # A gate that warns and hands the script over anyway is not a gate. This
    # printed "repair left 3 line(s) unfixed" and then saved a script whose
    # bullets invented 6,500 for alloy wheels, 9,200 for safety tech and
    # 12,000 in finance fees — none of which exist in cars.csv. Binning the
    # topic costs a draft; publishing invented prices costs the channel.
    if bad:
        raise RuntimeError(
            "narration still fails its checks after a rewrite, so this "
            "script is not safe to build:\n  "
            + "\n  ".join(b[:160] for b in bad)
            + "\nRe-run to roll again, or add the missing figures to "
              "data/cars.csv so the writer has them.")
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
        # The tracer now needs the car NAMED before it will cite a price, and
        # a stat label rarely names it ("Cheapest BYD EV price"). The line
        # spoken over the scene and the video's title usually do.
        title = spec.get("title", "")
        if s["type"] == "stat":
            pairs = [(s.get("value"),
                      f"{s.get('label', '')} {s.get('narration', '')} {title}")]
        else:
            # Rows named by trim alone ("GXR petrol") need the title to say
            # which car the trims belong to.
            pairs = [(r.get("value"),
                      f"{s.get('title','')} {r.get('name','')} {title}")
                     for r in s.get("rows", [])]

        label = s.get("label", "") if s["type"] == "stat" else s.get("title", "")
        found = {src for src in
                 (cars.source_for(v, ctx, fact_context=f"{label} {ctx}"
                                  if s["type"] == "compare" else label)
                  for v, ctx in pairs) if src}
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

# But a single ceiling for every scene silently truncated the audio. The
# clamp below caps the VISUAL; ffmpeg's -shortest then cuts the voice to
# match, and draft #106 lost the last 5.8 seconds of its narration — it ends
# mid-sentence — because one compare line was 10.2 seconds of speech in a
# 5-second scene. Nothing warned about it. A clamp that looks like a safety
# feature was a truncation.
#
# The fix is to cap the WORDS, not the playback: a line that cannot be spoken
# in its scene's budget fails too_long_to_speak() and gets rewritten shorter.
# That only works if the budget matches the scene's job. Two six-figure
# prices take 10 seconds to say at any honest rate, so a 5-second compare
# scene is not a tight brief, it is an impossible one — and compare scenes
# are required to state two figures.
#
# These come from the 14 measured clips in work/, rounded up from the longest
# of each type. The retention problem MAX_SCENE was added for was a chart
# sitting silent for 12 seconds; eight seconds while two prices are actually
# being spoken is a different thing.
SCENE_BUDGET = {
    "hook":     4.5,     # measured 2.35 - 3.61
    "stat":     5.5,     # measured 3.57 - 4.17
    # 8.0 was wrong by 0.01s, which a test caught: the tersest honest way to
    # say two six-figure prices, "The FJ starts at 139,900 against the 70's
    # 177,900", is 9.21s of speech. A compare scene is REQUIRED to state two
    # figures, so a budget that cannot hold two figures makes the two checks
    # contradict each other and no script can satisfy both.
    "compare":  9.0,     # measured 4.33 - 10.17; two spoken prices need 9.2
    "bullets":  6.0,     # measured 4.69
    "verdict":  6.5,     # measured 3.43 - 5.65
    "question": 3.5,     # measured 2.17 - 2.81
}

# Estimating a clip's length from its text is noisy — the measured clips run
# 2.4 to 5.5 spoken syllables per second, a 2.3x spread — so no single rate
# both avoids failing lines that fit and catches every line that does not.
#
# The two errors do not cost the same. A false failure costs one re-roll. A
# missed overrun used to cost a published video that stops mid-sentence, and
# now costs a refused render after the voice has already been generated. So
# the pre-check is tuned to catch the clear cases and truncation_seconds() is
# the thing that actually guarantees nothing ships cut.
#
# Rate 3.8 with a 1.15 tolerance classifies all 14 measured clips correctly:
# no false failures, no missed overruns. Fourteen is not many — if re-rolls
# start clustering on one scene type, re-fit from the newer clips in work/
# rather than nudging these by feel.
# Refitted on 31 measured clips once two systematic errors were removed:
# narrate() pads every clip with voice.TAIL of silence and the estimate never
# counted it (0.45s x 6 scenes is 2.7s), and acronyms were counted by vowel
# group, so "UAE" scored one syllable against three spoken. With both fixed
# the median error is near zero at 5.0.
SPEAK_RATE = 5.0         # spoken syllables per second
SPEAK_TOLERANCE = 1.15   # how far over budget a prediction must be to fail

# What a scene may stretch to beyond the check's ceiling, purely so that a
# line the check ACCEPTED is never cut.
#
# The estimate's spread is irreducible: across those 31 clips the same text
# ran anywhere from 2.4 to 5.5 spoken syllables per second, and the worst
# under-prediction was 2.6 seconds. Clamping exactly at the check's ceiling
# meant any line that came back slower than predicted lost its tail — which
# is what refused the Denza render after five minutes of voice generation.
#
# Holding a visual two seconds longer than intended is a small cost. Cutting
# the end off a sentence is not, so the slack goes to the audio.
TRUNCATION_SLACK = 3.0


def budget_for(kind: str) -> float:
    """The intended length of this scene — the editorial target."""
    return SCENE_BUDGET.get(kind, MAX_SCENE)


def hard_budget_for(kind: str) -> float:
    """The length this scene may actually reach.

    The check and the clamp have to use the SAME ceiling or they contradict
    each other: too_long_to_speak() allowed a line up to budget x tolerance
    because the estimate is noisy, while to_scenes() clamped at the budget
    itself, so a line that passed the check could still have its audio cut.
    The tolerance is headroom for a bad estimate, and headroom the renderer
    refuses to honour is not headroom.
    """
    return budget_for(kind) * SPEAK_TOLERANCE


def speaking_seconds(text: str) -> float:
    """How long this line's clip will be, trailing pad included.

    narrate() pads every clip with TAIL seconds of silence and to_scenes()
    consumes those padded lengths, so an estimate that leaves it out is
    short by TAIL on every single scene.
    """
    from .voice import spoken_syllables, TAIL   # late: avoids an import cycle
    return spoken_syllables(text) / SPEAK_RATE + TAIL


def truncation_seconds(scenes, durations) -> float:
    """How much voiceover the clamped visuals would throw away.

    render() passes -shortest, so the output is as long as the VIDEO and the
    audio is cut to fit. That is silent data loss: draft #106 shipped 20.2
    seconds of video over 26.0 seconds of narration and ended mid-sentence,
    and the only hint was a muxer warning about something else entirely.
    """
    return max(0.0, sum(durations or []) - sum(s.duration for s in scenes))


def too_long_to_speak(spec: dict) -> list[str]:
    """Narration that will not fit the scene it belongs to.

    Caught here it costs a rewrite. Caught at render time it costs nothing,
    because nothing catches it at render time — the audio is simply cut.
    """
    bad = []
    for sc in spec.get("scenes") or []:
        n = (sc.get("narration") or "").strip()
        if not n:
            continue
        budget = budget_for(sc.get("type"))
        need = speaking_seconds(n)
        if need > hard_budget_for(sc.get("type")):
            words = max(4, int(len(n.split()) * budget / need))
            bad.append(
                f"{_norm(n)}   -> about {need:.0f} seconds to speak, and this "
                f"scene holds {budget:.0f}. Say the same thing in roughly "
                f"{words} words, or drop a figure")
    return bad


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
            sc.duration = min(hard_budget_for(kind) + TRUNCATION_SLACK,
                              max(MIN_SCENE, d))
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
    # Motorcycle rules and specs. "100 km/h" is read "kay-em slash aitch".
    (re.compile(r"\bkm/h\b|\bkmh\b|\bkph\b", re.I), 'say "kilometres an hour"'),
    (re.compile(r"\d\s*cc\b", re.I), 'write the engine size as "150 C C"'),
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


# unsourced() inspects structured fields — a stat's "value", a compare row's
# "value". It never reads prose. So when the writer filled an empty bullets
# scene with "trim upgrades cost up to 30,000 dirhams, off-road accessories
# start at 12,000", _numbers() saw none of it, unsourced() returned [] and the
# pipeline would have rendered three invented prices.
#
# A figure spoken in a sentence is a claim like any other. It has to come from
# somewhere: a figure this spec actually holds, or honest arithmetic between
# two of them (a price gap, a total).
PROSE_FLOOR = 1000             # below this it is seats, speeds, years, words


# Only the stat scene's narration was ever required to say its own figure.
# compare and bullets had no equivalent, so both could pass every check while
# carrying nothing: a compare scene narrated "The FJ is the cheapest Land
# Cruiser variant at launch" without naming either price, under a hook that
# promised "the FJ or the 70 model" — with 139,900 and 177,900 both sitting in
# the facts it was handed. And when inventing figures started being blocked,
# the bullets scene did not start finding real ones; it started saying
# "Toyota's configurator shows monthly payments for each trim", which is a
# sentence with the shape of a fact and none of the content.
#
# Blocking these is safe because validate() requires only hook, verdict and
# question. A scene with no figures to speak has an escape hatch SYSTEM
# already names: leave it out.

def compare_says_nothing(spec: dict) -> list[str]:
    """A compare scene whose voiceover carries fewer than two real figures.

    The screen draws the bars; the listener hears one sentence. One figure is
    a stat, not a comparison — the gap is the whole point, and you cannot
    hear a gap from one number.

    A GAP counts as a figure, which is the correction to how this check first
    shipped. It demanded the row values specifically, and so rejected "The FJ
    starts 38,000 dirhams cheaper than the 70 and 60,000 cheaper than the
    Prado" — a line stating two exact differences between three prices in the
    scene, which is the comparison expressed better than listing the prices
    would. It is also the only arithmetic a viewer could check against the
    bars. The replacement the repair pass produced was longer and said less.
    """
    bad = []
    for sc in spec.get("scenes") or []:
        if sc.get("type") != "compare":
            continue
        values = [float(r["value"]) for r in (sc.get("rows") or [])
                  if r.get("value") is not None]
        if len(values) < 2:
            continue
        gaps = {abs(a - b) for i, a in enumerate(values)
                for b in values[i + 1:] if a != b}
        n = sc.get("narration") or ""
        spoken = {v for v in set(values) | gaps if _says_number(n, v)}
        if len(spoken) < 2:
            shown = ", ".join(
                f"{r.get('name')} {int(float(r['value'])):,}"
                for r in (sc.get("rows") or [])[:3] if r.get("value") is not None)
            bad.append(
                f"{_norm(n)}   -> a comparison the listener cannot hear. Say "
                f"two of these prices ({shown}), or two of the gaps between "
                f"them ({', '.join(f'{int(g):,}' for g in sorted(gaps)[:3])})")
    return bad


def bullets_say_nothing(spec: dict, facts: str = "") -> list[str]:
    """A bullets scene whose voiceover carries no figure at all.

    This scene exists to name what the sticker price hides, which is only
    worth a scene if it names an amount. invents_a_figure() already proves
    any figure here is real, so this only has to insist there is one.
    """
    sourced = _structured_values(spec) | {
        int(m.replace(",", "")) for m in re.findall(r"\d[\d,]{2,}", facts or "")}
    bad = []
    for sc in spec.get("scenes") or []:
        if sc.get("type") != "bullets":
            continue
        n = sc.get("narration") or ""
        if any(_says_number(n, v) for v in sourced):
            continue
        bad.append(
            f"{_norm(n)}   -> this scene is here to name what the price hides, "
            f"and names no amount. Say one of the figures from the facts, or "
            f"drop the scene")
    return bad


def _fact_numbers(facts: str) -> set:
    """Every number in the facts block, small ones included: "4 black points"
    is a figure the writer may quote."""
    out = set()
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", facts or ""):
        try:
            n = float(m.replace(",", ""))
        except ValueError:
            continue
        out.add(int(n) if n == int(n) else n)
    return out


def _structured_values(spec: dict) -> set:
    out = set()
    for sc in spec.get("scenes") or []:
        if sc.get("value") is not None:
            out.add(int(float(sc["value"])))
        for row in sc.get("rows") or []:
            if row.get("value") is not None:
                out.add(int(float(row["value"])))
    return out


def _rounds_to(said, sourced: set, shown: set) -> bool:
    """Is `said` an honest rounding of a sourced figure or an on-screen gap?"""
    gaps = {abs(a - b) for a in shown for b in sourced} | {a + b for a in shown
                                                           for b in sourced}
    for k in (sourced | gaps):
        if not k:
            continue
        if abs(said - k) <= abs(k) * ROUND_TOLERANCE:
            return True
        # A round number (200, 1,500) within 5% of the real one.
        if said % 50 == 0 and abs(said - k) <= abs(k) * 0.05:
            return True
    return False


def _derivable(said: int, shown: set, sourced: set | None = None) -> bool:
    """Is this an honest gap or sum, with at least one figure on screen?

    Requiring BOTH operands to be on screen rejected "the GXR adds 15,000",
    where 154,900 is in the data but only 139,900 is displayed. Allowing both
    operands to come from anywhere in the facts accepted an invented 12,000,
    because 76,900 - 64,900 happens to equal it. So: one operand must be a
    figure the video actually shows, which is also the only arithmetic a
    viewer could check.
    """
    pool = sourced if sourced is not None else shown
    for a in shown:
        for b in pool:
            if a - b == said or b - a == said or a + b == said:
                return True
    return False


ROUND_TOLERANCE = 0.02         # "under 140,000" for a 139,900 car is honest


# Small numbers are mostly not claims — seats, minutes, model years, speeds —
# which is why PROSE_FLOOR exists. But fines, black points and impound days
# are small numbers too, and skipping all of them let an invented "600 dirham
# impound fee" through every check. So a number under the floor is checked
# when it is attached to money, points or a percentage, or to days, months
# or years in a sentence about enforcement.
_UNIT_AFTER = re.compile(
    r"\s*(?:-\s*)?(dirhams?|aed|black points?|points?|percent|per cent|%"
    r"|days?|months?|years?)\b", re.I)
_AED_BEFORE = re.compile(r"(?:aed|dhs?)\s*$", re.I)
_ENFORCEMENT = re.compile(
    r"(?i)\b(impound\w*|confiscat\w*|seiz\w*|suspen\w*|jail|prison"
    r"|ban(?:ned)?|valid\w*|expir\w*|licen[cs]e|fine[sd]?|penalt\w*)\b")
_WORD_NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_WORD_NUM.update({w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1})
_SPELLED = re.compile(
    r"(?i)\b((?:(?:%s)[\s-]*(?:hundred)?[\s-]*(?:and\s+)?)+)" %
    "|".join(sorted(_WORD_NUM, key=len, reverse=True)))


def _spelled_value(words: str) -> int | None:
    total, cur = 0, 0
    for w in re.findall(r"[a-z]+", words.lower()):
        if w == "and":
            continue
        if w == "hundred":
            cur = max(cur, 1) * 100
        elif w in _WORD_NUM:
            cur += _WORD_NUM[w]
        else:
            return None
    total += cur
    return total


def _claimed_figures(text: str) -> list[int]:
    """Every number in prose that a viewer would take as a stated figure."""
    text = re.sub(r"https?://\S+", " ", text or "")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for sent in sentences:
        enforce = bool(_ENFORCEMENT.search(sent))
        found = [(m.start(), m.end(), m.group(1), m.group(2)) for m in
                 re.finditer(r"(\d[\d,]*(?:\.\d+)?)(k\b)?", sent, re.I)]
        for m in _SPELLED.finditer(sent):
            # Part of a spelled price: "two hundred thirty-nine thousand NINE
            # HUNDRED dirhams" is 239,900, not 900. spells_out_a_price()
            # owns those; this only reads numbers that stand alone.
            near = sent[max(0, m.start() - 12):m.end() + 12].lower()
            if "thousand" in near or "million" in near:
                continue
            found.append((m.start(), m.end(), m.group(1), None))
        for start, end, raw, k in found:
            if raw[0].isdigit():
                try:
                    n = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if k:                        # "AED 20k" is 20,000
                    n *= 1000
            else:
                v = _spelled_value(raw)
                if v is None:
                    continue
                n = float(v)
            if n >= PROSE_FLOOR:
                if raw[0].isdigit() and (k or not 1990 <= n <= 2035):
                    out.append(int(n) if n == int(n) else n)
                continue
            unit = _UNIT_AFTER.match(sent, end)
            money_before = _AED_BEFORE.search(sent[:start])
            if not unit and not money_before:
                continue
            kind = (unit.group(1).lower() if unit else "aed")
            if kind.startswith(("day", "month", "year")) and not enforce:
                continue
            out.append(int(n) if n == int(n) else n)
    return out


def invents_a_figure(spec: dict, facts: str = "") -> list[str]:
    """Prose figures that trace to nothing the writer was given.

    First version compared only against the spec's own structured values and
    was wrong in both directions: it flagged the real GXR delta (15,000), the
    real monthly instalment (2,192) and an honest rounding (140,000), while
    missing an invented "five percent" that sits below the floor. The repair
    pass then rewrote those true figures into spelled-out words — the form
    that caused the truncated prices in the first place.

    So the comparison set is everything the writer could legitimately know:
    the spec's own figures, arithmetic between them, and every number in the
    facts block it was handed.
    """
    # Two different permissions, deliberately kept apart.
    #   shown    - figures the video puts on screen. Arithmetic BETWEEN these
    #              is honest, because a viewer can check it.
    #   sourced  - everything the writer was handed. Quoting one is fine.
    # Allowing arithmetic across the whole facts block was far too loose: 24
    # numbers give ~570 pairwise differences, and 76,900 - 64,900 happens to
    # equal 12,000, which let an invented accessory price through.
    shown = _structured_values(spec)
    sourced = shown | _fact_numbers(facts)
    if not sourced:
        return []
    bad = []
    for sc in spec.get("scenes") or []:
        prose = [_norm(sc.get("narration") or "")]
        prose += [_norm(b) for b in (sc.get("bullets") or [])]
        for text in prose:
            if not text:
                continue
            for said in _claimed_figures(text):
                if said in sourced or _derivable(said, shown, sourced):
                    continue
                # A rounded figure is not an invented one — including a
                # rounded GAP: "undercuts it by at least 200" for a 205
                # difference (36,000 - 35,795) is honest.
                if _rounds_to(said, sourced, shown):
                    continue
                bad.append(f"{text[:80]}   -> {said:,} is not in the "
                           f"script or the facts it was given")
    return bad


# ------------------------------------------------------------ description --

def _sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking "109,900" or "12.3"."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


def _prose_numbers(text: str) -> list[int]:
    """Figures a reader would take as claims. A link is a citation, not a
    claim. Check-dates need no handling: 2026 is a year and 10 and 07 sit
    below PROSE_FLOOR."""
    text = re.sub(r"https?://\S+", " ", text)
    out = []
    for m in re.findall(r"\d[\d,]*", text):
        n = int(m.replace(",", "") or 0)
        if n >= PROSE_FLOOR and not 1990 <= n <= 2035:
            out.append(n)
    return out


def _description_superlative(sentence: str, title: str) -> str | None:
    """Why a "cheapest ... N" sentence is false, or None.

    Unlike false_superlative(), a claim inside a named brand is checked too —
    against that brand's own rows, and that model family's when one is named
    ("the cheapest GR"). The exemption for branded titles assumed retrieval
    fetches the whole brand; #134 showed the writer contradicting the rows it
    was handed.
    """
    from .cars import (load, load_bikes, usable, _tokens, CATEGORY_WORDS,
                       BIKE_CATEGORY_WORDS, is_bike_query, wants_offroad,
                       road_bike, STOPWORDS)
    if not _SUPERLATIVE.search(sentence):
        return None
    # "the cheapest new sedan under 40,000" names a ceiling, not a price.
    # Draft #138 was flagged for calling 40,000 the cheapest until bounds
    # were taken out of the claim.
    claim = re.sub(r"(?i)\b(?:under|below|less than|up to|within|over|above"
                   r"|more than)\s+(?:aed\s+|dhs?\s+)?\d[\d,]*", " ", sentence)
    nums = _prose_numbers(claim)
    if not nums:
        return None
    claimed = min(nums)
    bike = is_bike_query(f"{title} {sentence}")
    rows = [r for r in (load_bikes() if bike else load())
            if usable(r) and r.get("price_from_aed")]
    if bike and not wants_offroad(f"{title} {sentence}"):
        rows = [r for r in rows if road_bike(r)]
    words = CATEGORY_WORDS | BIKE_CATEGORY_WORDS if bike else CATEGORY_WORDS

    toks = _tokens(sentence)
    brands = {r["brand"] for r in rows if _tokens(r["brand"]) <= toks}
    if not brands:                          # "the cheapest model we found ..."
        brands = {r["brand"] for r in rows if _tokens(r["brand"]) <= _tokens(title)}
    if brands:
        rows = [r for r in rows if r["brand"] in brands]
        family = set()
        for r in rows:
            family |= _tokens(r["model"])
        named = (toks & family) - words - STOPWORDS
        named = {w for w in named if not w.isdigit()}
        if named:
            rows = [r for r in rows if named <= _tokens(r["model"])] or rows

    want = {_CATEGORY_ALIAS.get(w, w) for w in toks & words}
    pool = [r for r in rows
            if want <= _tokens(r.get("segment", ""), r.get("powertrain", ""))]
    cheaper = sorted((r for r in pool if int(r["price_from_aed"]) < claimed),
                     key=lambda r: int(r["price_from_aed"]))
    if not cheaper:
        return None
    b = cheaper[0]
    return (f"calls {claimed:,} the cheapest, but the {b['brand']} {b['model']} "
            f"is {int(b['price_from_aed']):,}")


def description_faults(spec: dict, facts: str = "") -> list[tuple[str, str]]:
    """(sentence, reason) for every sentence of the writer's description
    paragraph that the narration checks would refuse."""
    shown = _structured_values(spec)
    sourced = shown | _fact_numbers(facts)
    title = spec.get("title") or ""
    out = []
    for sent in _sentences(spec.get("description") or ""):
        why = _description_superlative(sent, title)
        if not why and sourced:
            for said in _claimed_figures(sent):
                if said in sourced or _derivable(said, shown, sourced):
                    continue
                if _rounds_to(said, sourced, shown):
                    continue
                why = f"{said:,} is not in the script or the facts it was given"
                break
        if why:
            out.append((sent, why))
    return out


def clean_description(spec: dict, facts: str = "") -> list[str]:
    """Remove failing sentences from spec["description"] in place.

    Returns what was dropped, for the log. Line breaks are kept, because
    describe() treats a line starting with a link as a citation to strip.
    """
    bad = description_faults(spec, facts)
    if not bad:
        return []
    text = spec.get("description") or ""
    for sent, _ in bad:
        text = text.replace(sent, "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    spec["description"] = text
    return [f"{sent}   -> {why}" for sent, why in bad]


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
    #
    # Add --save to keep a script you like and render it:
    #   python -m autoedits.script --probe --save "land cruiser fj uae price"
    #   python -m autoedits.pipeline --from-spec land-cruiser-fj-uae-price
    import sys

    from . import cars

    args = [a for a in sys.argv[1:]
            if a not in ("--compare", "--probe", "--save")]
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

        # A probe you like should be one command away from a video. Without
        # this there was no way to keep a good script except re-rolling the
        # dice in the pipeline and hoping for the same one.
        if "--save" in sys.argv:
            from .config import WORK
            import re as _re
            slug = _re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60]
            d = WORK / slug
            d.mkdir(parents=True, exist_ok=True)
            # --from-spec re-runs every check, and needs to know which facts
            # this script was written against.
            spec["query"] = query
            (d / "spec.json").write_text(
                json.dumps(spec, indent=2, ensure_ascii=False))
            print(f"\n  saved {d / 'spec.json'}")
            print(f"  render it with:  python -m autoedits.pipeline "
                  f"--from-spec {slug}")
        else:
            print("\n  (add --save to keep this one and render it)")
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
