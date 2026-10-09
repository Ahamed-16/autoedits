# Auto Edits — assisted production pipeline

Generates UAE car-buying Shorts on your own machine: topic discovery from real
search demand, script, voiceover, motion-graphics render, and upload. Everything
is automated except one step — you approve each video before it ships.

## Why there's a human step

Your channel is already automated. That pipeline produced, over 28 days:

| | |
|---|---|
| Views from the Shorts feed | **3.8%** |
| Impressions from YouTube recommending you | **2.0%** |
| Likes on 1,574 views | **2** (0.13%) |
| New viewers who came back | **0** |
| Net subscribers | **–1** |

People watched and felt nothing, so the feed stopped serving it. That is a
judgement failure, not a production failure — and judgement is the one part
worth keeping. Everything else here is machinery.

Budget about five minutes a day. It is spent checking that the numbers in the
video are real and that the hook is worth stopping for.

## What it makes

Typographic motion graphics rendered frame-by-frame from Python — no stock
footage and no third-party clips, so there is nothing that can be
copyright-claimed and nothing that looks scraped. Six scene types: hook, stat,
comparison bars, bullets, verdict, closing question.

Rendering a 25-second video takes about 15 seconds on a modern CPU; budget
40–60s on the M710t. That is not the bottleneck.

## Setup

**→ [SETUP.md](SETUP.md)** — voice options, config.yaml line by line,
Anthropic keys, YouTube OAuth.
**→ [TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — every error hit during setup
and its actual fix. Check here first; most of these errors point nowhere near
their real cause.

The short version:

```bash
bash install.sh                    # installs everything, then checks itself
python -m autoedits.doctor         # re-run any time; tells you what's missing
```

Nothing needs downloading in advance and no API key is required to start — the
default config uses Ollama (already on your machine) plus Kokoro for voice, so
the first videos cost nothing.

Note that the **writer** (Ollama or Anthropic — turns a topic into a script)
and the **voice** (Kokoro, Chatterbox or Piper — turns the script into speech)
are entirely separate systems. Ollama does not do text-to-speech.

## Daily use

```bash
source .venv/bin/activate               # first, always

python -m autoedits.photo_short --all --draft   # shorts from your own photos

streamlit run review_app.py             # daily:  approve, then Upload
python -m autoedits.publish             # daily:  ship what you approved
python -m autoedits.publish --check     # weekly: is the YouTube token alive?
python -m autoedits.publish --metrics   # weekly: pull views/likes back in
python -m autoedits.analytics          # weekly: retention + traffic sources
python -m autoedits.audit               # rarely:  list the whole back catalogue
python -m autoedits.topics              # weekly: refresh the topic queue
python -m autoedits.topics --evergreen  # after editing evergreen_topics.txt
python -m autoedits.pipeline            # nightly (cron does this): build drafts
```

Diagnostics, all of which skip the slow parts:

```bash
python -m autoedits.doctor              # is everything installed?
python -m autoedits.topics --probe      # is the search endpoint alive?
python -m autoedits.script "a topic"    # generate a script, render nothing
python -m autoedits.cars                # data health + conflicts
python -m autoedits.cars "a topic"      # what the writer will see
python -m autoedits.pipeline --rebuild <slug>   # re-render, reuse the voice
```

Cron it:

```cron
0  3 * * *  cd ~/autoedits && .venv/bin/python -m autoedits.pipeline >> cron.log 2>&1
0  4 * * 1  cd ~/autoedits && .venv/bin/python -m autoedits.topics   >> cron.log 2>&1
```

Uploading is deliberately **not** in cron. The machine builds; you decide what
ships.

## Shorts from your own photographs

The data shorts are typography on black. That is claim-proof and cheap, but it
gives a viewer very little to look at, which is most of why the first one held
7.7% of its audience. `photo_short.py` fixes that with the one asset no
automation can produce: pictures you took.

    python -m autoedits.photo_short --all --draft

Each file in `data/meets/` is a plain-text manifest — a title, a closing
question, then one photo or clip per line with an optional caption. The build
renders a vertical Short and drops it into the same review queue as everything
else, so it ships through the same Approve → Upload path.

A line ending `@1.2+3.0` takes three seconds of video starting at 1.2s. Mixing
one or two clips into a set of stills is worth doing: motion is what stops a
thumb.

Two rules. Caption only cars you can actually name — a wrong model costs more
than a silent frame. And leave most frames uncaptioned, or it reads as a
slideshow rather than an edit. There is no music; add it in Studio from the
Audio Library with attribution set to "not required".

## How topics are chosen

`topics.py` queries YouTube's own autocomplete — the literal phrases people
type — and alphabet-expands each seed to pull hundreds of suggestions out of an
endpoint that returns ten at a time. Phrases are scored by suggestion rank
(demand) against how many top results already target them exactly
(competition).

This leans into your one working channel. 91.4% of your views arrive via
search, and your best recent Short — *"BMW iX3 vs Tesla Model Y: which should
you actually lease?"*, 708 views — is the one title phrased like a question a
person types. That is the pattern this module industrialises.

### Evergreen first

Autocomplete has one blind spot: it reports what is being searched *now*. That
is how the queue filled with fuel prices and model-year pricing — real demand,
but demand whose answers expire. A video built on September's diesel price is
wrong in October, and re-shooting it is time you do not have.

So the queue has a second source. `data/evergreen_topics.txt` is a hand-written
list of questions about UAE law and regulation — insurance excess caps, black
points, the Central Bank's car-loan limits — loaded at a score above anything
harvested:

    python -m autoedits.topics --evergreen

Those answers have been true for years and will be true next year. The file is
in priority order, so **reordering it reorders the channel**. `python -m
autoedits.topics` loads it first and then harvests, which is the intended
balance: a durable spine, with trending phrasing layered on top.

## The numbers problem

The single way this pipeline fails badly is by confidently publishing a price
that is wrong. Three defences:

1. `data/cars.csv` is yours to curate. Anything you put there is fed to the
   writer as verified fact, so it reaches for your data before its own memory.
2. Every stat and comparison must carry a `source`. With
   `pipeline.require_sources: true`, a script that can't source its numbers is
   discarded rather than published.
3. The review app lists each claim and its source next to the video. **This is
   what your five minutes buys.** A wrong dirham figure on a buying-advice
   channel costs trust you can't rebuild.

Start by adding twenty rows to `cars.csv` for the models you want to cover
first. That one afternoon does more for output quality than any code here.

### Four data files, different shelf lives

| File | Holds | Expires |
|---|---|---|
| `data/cars.csv` | UAE prices by brand and model | 90 days |
| `data/cars_parked.csv` | rows deliberately out of scope | never loaded |
| `data/insurance.csv` | the regulated premium tariff bands | 90 days |
| `data/ownership.csv` | registration, Salik, fuel | per row — fuel is 31 days |
| `data/rules.csv` | the law and the regulations | 730 days |
| `data/heat.csv` | what 50-degree summers do to a car | 730 days |

`rules.csv` is the one that pays rent. "Your insurer may not charge more than
AED 1,000 excess on a car worth AED 200,000" comes from a 2016 regulation and
is still true; a price is true until the next model year. Rows carry their own
`stale_days`, so the pipeline stops using a figure before it becomes a lie
rather than after — but treat that as the safety net, not the content plan.

`cars_parked.csv` is not read by anything. It holds rows that were correct but
out of scope: Ferrari, Lamborghini, Maserati and Bentley, anything from AED
500,000 up, and the one price that could never be resolved. Nobody researching
a 900,000-dirham purchase settles it on a 30-second Short, and every row the
writer can see is a row that can crowd out a better one. Move a line back
across if that ever stops being true.

The file's real weakness is the other end. Only twenty rows start under AED
60,000 — which is exactly where "cheapest car in the UAE" and "best first car"
live, and those are the highest-intent searches on the channel. Twenty more
rows under 100,000 would do more than anything else in this repository.

`heat.csv` is the same idea aimed at the one thing about driving here that no
global car channel has any reason to explain: the RTA's five-year tyre limit,
ESMA's tread depths, what 70 degrees inside a parked car does to a battery, the
tint limit and the fine for exceeding it. The climate is not going to change,
so neither is any of it.

Figures in `rules.csv` are not all money, so every row names its unit, and the
writer must set `stat_unit` / `compare_unit` to match. "4" black points drawn
as "AED 4" is a false statement on screen, not a formatting slip.

## Running cost

| Setup | Monthly |
|---|---|
| Anthropic writer + Kokoro voice | **~$3** |
| Ollama writer + Kokoro voice | **$0** |
| Anthropic writer + ElevenLabs voice | ~$8 |

Kokoro is free, Apache-2.0 and comfortably real-time on your CPU, so there is
no good reason to pay for voice. Chatterbox (MIT) clones your own voice for
free if you'd rather narrate as yourself — slow on a GPU-less box, irrelevant
for a 3am cron.

The one place money buys something real is the writer. An 8B local model hedges
instead of taking a position, and the verdict scene is what earns comments.

## What this does not fix

Automation cannot manufacture a reason to care. What it buys you is the ability
to test twenty real opinions a month instead of three — and the feedback loop
to tell which ones landed.

That loop is the Performance tab. Once ~20 videos are through, sort by like
rate, read your three best hooks, and write the next batch like those. Target
2%. You are at 0.13%.

Also worth knowing: YouTube's inauthentic-content policy targets mass-produced
repetitive uploads for demonetisation. Three sourced, opinionated videos a day
is a different object from four hundred rewritten headlines — but the line is
enforced on what the output looks like, not on your intentions. Keep the volume
low and the sourcing real.

## Layout

```
autoedits/
├── theme.py       colours, fonts, safe areas — rebrand everything here
├── render.py      scene classes + the frame pipe into ffmpeg
├── topics.py      autocomplete demand mining
├── script.py      the writing prompt and JSON→scene conversion
├── voice.py       per-line TTS, durations drive scene timing
├── publish.py     OAuth upload + stats readback
├── pipeline.py    nightly orchestration
└── db.py          SQLite: topics, drafts, published, metrics
review_app.py      the five minutes
config.yaml        seeds, models, knobs
data/cars.csv      your verified figures
```

Scene durations come from the length of each narration clip, so visuals always
change on the sentence rather than drifting out of sync.
