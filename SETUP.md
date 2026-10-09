# Setup, step by step

## Start here

```bash
tar xzf autoedits.tar.gz && cd autoedits
bash install.sh
```

That installs everything, then runs a pre-flight check that prints exactly
what's still missing and the command to fix each one. Re-run it any time:

```bash
source .venv/bin/activate
python -m autoedits.doctor
```

Work down its list until it's green. The rest of this document is the detail
behind each item.

**You need nothing downloaded in advance** — no accounts, no API keys, no
credit card. The default config uses Ollama (already on your machine) and
Kokoro (installed by the script), so the first videos cost nothing. Paid
services are opt-in later.

---

Four areas, in the order they're worth doing:

1. [Voice](#1-voice) — free options, including using your own
2. [config.yaml](#2-configyaml) — what actually needs changing
3. [The writer](#3-the-writer-anthropic-or-ollama) — Ollama or Anthropic
4. [YouTube upload](#4-youtube-oauth) — OAuth, and the two gotchas

---

## 1. Voice

### First, a correction

**Ollama cannot do text-to-speech.** Ollama runs language models — it turns a
prompt into text. Speech is a completely separate kind of model. So there are
two independent choices in this system:

| | What it does | Free option |
|---|---|---|
| **Writer** | topic → script | Ollama (already on your machine) |
| **Voice** | script → speech | Kokoro / Chatterbox / Piper |

They're configured separately and neither knows the other exists.

### A licensing warning worth 60 seconds

Almost every "local voice cloning" tutorial points at **XTTS-v2** or
**F5-TTS**. Both are non-commercial licences — XTTS-v2 is under Coqui's CPML,
and since Coqui shut down in January 2024 there is nobody left who can sell you
a commercial licence for it. F5-TTS is CC-BY-NC.

A monetised YouTube channel is commercial use. Since monetisation is plausibly
where you're heading, use one of the permissive ones instead:

| Model | Licence | Clones your voice? | CPU-only |
|---|---|---|---|
| **Kokoro** (82M) | Apache-2.0 | No, preset voices | Comfortably real-time |
| **Chatterbox** | MIT | Yes, from ~15s | Slow but usable overnight |
| **Piper** | MIT | Only if you train it | ~10× real-time |
| XTTS-v2 | CPML | Yes | ⚠️ non-commercial |
| F5-TTS | CC-BY-NC | Yes | ⚠️ non-commercial, needs 24GB VRAM |

### Option A — Kokoro (start here)

Free, good, and running in five minutes. Not your voice, but a long way from
robotic.

```bash
sudo apt install espeak-ng
pip install kokoro soundfile
```

In `config.yaml`: `voice.engine: kokoro`. Then test:

```bash
python -m autoedits.voice     # writes work/voice_test.mp3
```

Try a few `kokoro_voice` values and pick one: `bm_george`, `bm_lewis`,
`am_michael`, `am_adam`, `af_heart`, `bf_emma`.

### Option B — Chatterbox, your actual voice

MIT licensed, clones from a short sample, free forever.

```bash
pip install chatterbox-tts torchaudio
```

**Record your reference.** This is the part that determines quality, so it's
worth ten minutes:

- 15–20 seconds, reading something ordinary at your natural pace
- Quiet room, no music, no echo — a phone held 20cm away is fine
- Don't perform it. Read like you're explaining something to a friend
- Trim silence off both ends

```bash
# convert whatever your phone produced into what Chatterbox wants
ffmpeg -i voice_memo.m4a -ac 1 -ar 24000 data/my_voice.wav
```

In `config.yaml`: `voice.engine: chatterbox` and
`reference_audio: data/my_voice.wav`. Then `python -m autoedits.voice`.

**On speed:** first run downloads about 1GB. Your M710t has no GPU, so expect a
few minutes per line — maybe 15–25 minutes for a full video. That sounds bad
until you remember the pipeline runs at 3am on a cron. You are asleep. Only the
review app needs to be fast, and that just plays a finished file.

If it's genuinely too slow, run Kokoro on weeknights and Chatterbox on a
weekend batch, or train a Piper voice (below) for permanent speed.

### Option C — Piper with your own trained voice

Fastest of all and MIT, but training needs ~30–60 minutes of clean recordings
and a few GPU-hours (rent one for a couple of dollars, or use a free Colab).
Worth doing once if you settle on this format long-term — after that it's
instant and free forever. Ready-made voices work immediately:

```bash
# grab a prebuilt voice
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
# download en_GB-alba-medium.onnx + .onnx.json from
# https://github.com/rhasspy/piper/releases
```

---

## 2. config.yaml

Only three lines need a decision. Everything else has a working default.

```yaml
models:
  writer: anthropic        # <-- "anthropic" (paid, better) or "ollama" (free)

voice:
  engine: kokoro           # <-- kokoro | chatterbox | piper | elevenlabs

topics:
  seeds:                   # <-- eventually: replace with your real niche
    - best car to buy in uae
    ...
```

The rest, in the order you'll care about them:

**`pipeline.drafts_per_night: 3`** — how many videos to build each night. Leave
it at 3. Your old pipeline's problem was never that it made too few.

**`pipeline.require_sources: true`** — if the writer can't cite where a number
came from, the script is discarded instead of built. Leave this on. It is the
main thing separating this from what you were running before.

**`topics.seeds`** — the phrases that get alphabet-expanded against YouTube
autocomplete. Write them as the *opening* of a search, not a finished question.
`"is it worth buying"` is a good seed; `"is the Model Y worth buying in Dubai?"`
is a bad one, because nothing expands from it.

**`topics.must_contain_any`** — a phrase needs one of these words to enter the
queue. This is what keeps the system in your lane instead of drifting to
generic global car content.

**`topics.exclude`** — kill-list. Add to it whenever you see a bad topic get
queued.

**`voice.kokoro_voice`** / **`reference_audio`** / **`piper_model`** — only the
one matching your chosen engine matters; the others are ignored.

To change how everything *looks* rather than how it works, that's
`autoedits/theme.py` — colours, fonts and the safe margins, all in one place.

---

## 3. The writer: Anthropic or Ollama

### Using Ollama (free)

You already have it. Just:

```bash
ollama pull llama3.1:8b
```

`config.yaml` → `models.writer: ollama`. Done. No API key, no billing, works
offline.

Be aware of what you're trading: an 8B model writes noticeably flatter hooks
and hedges instead of taking a position. Since the verdict scene is the thing
that earns comments, that hedging is expensive. A reasonable compromise is
Ollama for drafting and rewrites, Anthropic for the nightly batch — at 3
scripts a night the paid path costs roughly **$3/month**, which is less than
the voice would have.

If you want a stronger local model and have the RAM,
`ollama pull qwen2.5:14b` is a real step up on instruction-following. Check
free RAM with `free -h` first; a 14B quantised model wants ~10GB.

### Using Anthropic (paid)

1. Go to **console.anthropic.com** and sign in.
2. **Settings → Billing** → add a payment method and buy credit. Start with $5.
   *This is separate from a Claude Pro subscription — a Pro plan does not
   include API access, they're billed independently.*
3. **Settings → API keys → Create key.** Copy it; it's shown once.
4. Paste into `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

5. `config.yaml` → `models.writer: anthropic`.

Test it:

```bash
python -c "
from autoedits import script
s = script.generate('is the tesla model y worth it in dubai')
print(s['title']); print(len(s['scenes']), 'scenes')"
```

---

## 4. YouTube OAuth

The fiddliest part, but it's a one-time 20 minutes.

1. **console.cloud.google.com** → create a project (call it anything).
2. **APIs & Services → Library** → search *YouTube Data API v3* → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External**
   - App name, your email for support and developer contact — the rest can stay
     blank
   - Scopes: skip, the app requests them at runtime
   - Test users: add your own Google address
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app**
   - Create, then **Download JSON**
5. Save that file in the project folder as **`client_secret.json`**.
6. First run opens a browser once:

```bash
python -c "from autoedits import publish; publish.service(); print('authorised')"
```

You'll see an "unverified app" warning. That's expected — it's your own app,
click through *Advanced → Go to (app name)*. A `token.json` gets written and
you won't be asked again.

### Two gotchas that will bite you later

**Refresh tokens expire after 7 days while the consent screen is in "Testing".**
Your cron will work for a week and then silently start failing. Fix it before
it happens: OAuth consent screen → **Publish app** → confirm. You do *not* need
Google's verification review for this — you're the only user. Once published,
the token stops expiring.

**Quota.** You get 10,000 units/day and an upload costs 1,600, so about
**6 uploads per day** maximum. At 3/night you're fine, but that's the ceiling if
you ever think about scaling up.

---

## Putting it together

```bash
python -m autoedits.voice                  # 1. voice works?
python -c "from autoedits import script; print(script.generate('best suv uae')['title'])"
python -m autoedits.topics                 # 2. queue fills up?
python -m autoedits.pipeline               # 3. builds drafts
streamlit run review_app.py                # 4. approve one, hit Upload
```

Then the cron:

```cron
0 3 * * *  cd ~/autoedits && .venv/bin/python -m autoedits.pipeline
0 4 * * 1  cd ~/autoedits && .venv/bin/python -m autoedits.topics
```

Nothing uploads without you pressing the button.
