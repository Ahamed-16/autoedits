# The Auto Edits — how a script becomes a safe video

Updated 21 Oct 2026. Companion to `auto-edits-sourcing-policy.md`, which
covers *where* a legal figure may come from. This covers everything between
a queued topic and a rendered draft: what is checked, why, and the measured
numbers behind every threshold.

**The principle that runs through all of it:** a gate that warns and hands
the work over anyway is not a gate. Each check below either blocks or
repairs. Several of them used to print a warning and carry on, and every one
of those eventually shipped something broken.

## Day-to-day commands

```
python -m autoedits.topics --check "phrase"    can this be built? queues nothing
python -m autoedits.topics --add "phrase" ...  queue at top priority, with a report
python -m autoedits.cars --why "phrase"        why a phrase matched no rows
python -m autoedits.script --probe --save "phrase"   write one script, save the spec
python -m autoedits.pipeline --from-spec <slug>      render a saved spec
python -m autoedits.pipeline                         the nightly run
```

`--add` tells you before you spend a render whether a topic has data, whether
the dedupe guard would block it, and which past videos it overlaps. Topics you
add by hand skip the dedupe guards entirely — you have already made the
judgement the guard exists to make — and the overlap is shown as advice.

## The narration checks

Every script runs through eight checks. If any fail, the repair pass gets the
specific complaint for each broken line and is told to leave the rest alone.
A rewritten line is kept only if it is actually clean; anything the repair
makes worse is reverted. If faults remain after that, the build is refused.

| Check | Catches | Why it exists |
|---|---|---|
| `leans_on_screen` | "That's the price", "It offers..." | A listener never saw the screen. |
| `unspeakable` | AED, %, km, hp, 90k | A voice reads abbreviations as letters. |
| `spells_out_a_price` | "one hundred thirty-nine thousand" | The writer drops the leading group when spelling. |
| `misquotes_a_figure` | a number that disagrees with its own scene | |
| `invents_a_figure` | a figure in no file the writer was given | Bullets once invented 6,500 / 9,200 / 12,000. |
| `compare_says_nothing` | a compare line stating fewer than two figures | Every one saved at the time failed it. |
| `bullets_say_nothing` | a bullets line naming no amount | Ditto. "Prices can differ, so compare quotes." |
| `too_long_to_speak` | a line longer than its scene can hold | See length, below. |

A **gap** counts as a figure in a compare scene. "The FJ undercuts the 70 by
38,000 and the Prado by 60,000" is usually a better line than listing prices,
and it is faster to say.

Only hook, verdict and question are required scenes. A bullets or compare
scene with nothing real to say should be dropped, and `SYSTEM` says so.

## Numbers and the voice

**The voice engine never sees a digit.** `voice.speakable()` rewrites every
number into words immediately before synthesis. Chatterbox read "162,900" as
"sixty-two thousand nine hundred" in a rendered draft — the leading
hundred-thousand silently gone. Spelled-out numbers had already failed a
different way, so neither form can be trusted to the engine. The spec keeps
its numerals and the screen still shows `AED 162,900`; only the synthesiser's
input changes. "B8" becomes "B eight", "4x4" becomes "four by four", and
"12.3" becomes "twelve point three".

**A short clip is refused.** If a clip comes back under 70% of its expected
length after two retries, the engine has dropped words mid-sentence. That
raises; the nightly run catches it and moves to the next topic. It used to
print a warning and keep the clip.

## Length: the measured numbers

All of these were fitted on real clips in `work/`. **If re-rolls start
clustering on one scene type, re-fit from the newer clips rather than nudging
by feel.**

| Constant | Value | What it is |
|---|---|---|
| `SPEAK_RATE` | 5.0 | spoken syllables per second, fitted on 31 clips |
| `voice.TAIL` | 0.45 s | silence padded onto every clip by `narrate()` |
| `SPEAK_TOLERANCE` | 1.15 | how far over budget a prediction must be to fail |
| `TRUNCATION_SLACK` | 3.0 s | how far a scene may stretch so accepted audio is never cut |
| `voice.SYL_PER_SEC` | 4.4 | rate used by the short-clip detector |

| Scene | Budget | Measured range |
|---|---|---|
| hook | 4.5 s | 2.35 – 3.61 |
| stat | 5.5 s | 3.57 – 4.17 |
| compare | 9.0 s | 4.33 – 10.17 |
| bullets | 6.0 s | 4.69 |
| verdict | 6.5 s | 3.43 – 5.65 |
| question | 3.5 s | 2.17 – 2.81 |

Three facts shaped this:

- **Digits must be counted as spoken.** "139,900" is four characters and
  eleven syllables. The old rate of 5.6 under-counted exactly the lines this
  project wants.
- **The trailing pad was never counted.** 0.45 s × six scenes = 2.7 s missing
  from every estimate. Acronyms were also under-counted — "UAE" scored one
  syllable against three spoken.
- **The estimate's spread is irreducible.** The same text runs anywhere from
  2.4 to 5.5 syllables per second. So the check governs how long lines are
  *written*, and the clamp is deliberately generous: holding a visual two
  seconds longer is cheap, cutting the end of a sentence is not.

The **compare budget must hold two spoken prices**, or the compare check and
the length check contradict each other and no script can pass both. The
tersest honest two-price line is 9.2 s; a test enforces this.

**The backstop:** before rendering, the pipeline computes how much audio the
clamped visuals would discard and refuses if it is more than 0.25 s. Draft
#106 rendered 20.2 s of video over 26.0 s of narration and ended mid-sentence;
that cannot happen silently any more.

## The Groq budget

Free tier: 8,000 tokens per minute, and `max_completion_tokens` is charged
up front as a reservation, not a ceiling.

- The writing call sends `SYSTEM` (10,410 characters) and reserves what fits.
  The reply budget is about 2,900 against a floor of 2,200; successful runs
  use roughly 2,400. **This is tight.** The next rule added to `SYSTEM`
  should come with dropping `facts_for`'s limit from 12 rows to 8.
- The repair call sends its own 348-character brief, *not* `SYSTEM`, and
  reserves 2,200. Sending the full writing brief cost 2,602 tokens per repair
  and left 900 for the answer — too few for this reasoning model to finish a
  valid JSON document, which killed two of three topics in one night.
- A 429 straight after the writing call is normal; the retry waits it out.

## The topic queue

`db._similarity` decides whether a topic repeats a past video. It divides by
the *shorter* subject, which correctly catches a rephrasing. But when the
shorter subject is one word, containment is automatic: "cheapest cars in uae"
reduces to `{cheapest}` and scored 1.00 against "Toyota GR prices in UAE –
which one is cheapest". At 120 videos that blocked **305 of the top 400
topics** while 1,186 of 1,498 queued topics had data, and the nightly run
built nothing for two days. A one-word subject now has to clear the larger
denominator.

| Guard | Threshold |
|---|---|
| `SAME_TOPIC` | 0.50 against every video ever made |
| `TOO_SOON` | 0.28 against the last 10 |

**Known gap:** the batch guard cannot see that "cheapest cars in uae" and
"budget car in uae" are the same video, because their only subject words
differ. Drafts #124 and #125 were built the same night for this reason.

## Retrieval fixes in `cars.facts_for`

- `"percentage"` and other shape words are stopwords, and phrase-rule
  expansions are filtered through the stopword list too. Previously "tint
  percentage" expanded to `{tint, maximum}` and found "Maximum total
  repayments" — about 50 lead rows corrected.
- A price-ranked query with nothing else in it ("cheapest cars in uae")
  falls back to the cheapest rows, unless it names a brand the data lacks.
- Cheap queries rank by **how many constraints a row meets**, then price.
  Price first led "cheapest electric suv" with four petrol SUVs.
- "expenses", "running cost" and "cost of owning" route to the running-cost
  files. "car expenses in dubai" was the highest-demand phrase in the queue
  and returned nothing.
- `"fine"` deliberately does **not** route. "traffic fine check online uae"
  asks how to use the RTA portal, which no row answers.

## Data added this month

| Rows | Source | Confidence |
|---|---|---|
| Hilux 2027, five trims 120,900–164,900 | toyota.ae | cross-checked |
| Land Cruiser, nine trims 239,900–409,900 | toyota.ae | cross-checked |
| Denza B5 Deluxe / Flagship, B8 Flagship / Executive | denza-uae.ae + Al-Futtaim spec sheets | cross-checked |

Two source lessons, both written into `data/sources.csv`:

- **Denza's UAE site is `denza-uae.ae`, not `denza.ae`.** The latter exists,
  blocks crawlers, and was briefly a wrong guess.
- **`byduae.ae` carries no Denza at all** — its sitemap has no B5 or B8.

The Land Cruiser hybrid costs exactly 10,000 more than the matching 3.5 L
petrol trim at GXR, VXR and GR-Sport. Two hybrid labels were truncated in the
configurator; they are identified from their feature lists, flagged CAUTION in
the notes.

The registry is now 33 domains; the sourcing policy's count of 17 predates
this month.

## Tests

```
python tests/test_narration.py && python tests/test_retrieval.py && python tests/test_queue.py
```

39 tests across three suites, nearly all covering a bug that actually
shipped. The ones guarding the worst failures — the spelled-out price in the
prompt examples, the unmapped complaint, the one-word subject, the mis-bound
`else` — were verified by **putting the bug back and confirming the test
fails**. One first attempt at that was not faithful to the original bug and
the test passed against it, which would have proved nothing; reverting has to
reproduce the bug exactly.

Run the suites before trusting any change to the scoring, the checks or the
timing constants.

## Open

- Near-duplicate topics in one batch (above).
- Autocomplete junk at the head of the queue — "best car to buy in uae
  jailbreak / kannada / zakat". Mostly harmless because it has no data, but
  "car maintenance cost dubai india" did, and became draft #126.
- `SYSTEM` is close to its token budget.
- **The December cliff.** `STALE_DAYS` is 90 and stale rows are withheld
  from retrieval, so **324 car rows stop being usable before the year ends —
  293 of them on 5 December** and 31 the day before. Most of the September
  data was gathered in one sweep, so it expires in one go. Unless those rows
  are re-checked, coverage collapses overnight and the nightly run goes back
  to building nothing. `python -m autoedits.cars` reports what is stale.
