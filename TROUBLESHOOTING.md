# Troubleshooting

Every problem hit during setup, with the actual fix. Written down because most
of these produce error messages that point nowhere near the real cause.

---

## `TypeError: 'NoneType' object is not callable` at `perth.PerthImplicitWatermarker()`

Chatterbox won't load. The cause is buried two libraries deep.

`resemble-perth` ships with an **empty dependency list**, so pip installs it
without the things it imports. Its watermarker then fails to import, perth's
`__init__` swallows the `ImportError` and leaves the class as `None`, and
Chatterbox calls it.

Find the hidden error:

```bash
python -c "from perth.perth_net.perth_net_implicit.perth_watermarker import PerthImplicitWatermarker"
```

Usually it's `No module named 'pkg_resources'`, which means:

```bash
pip install "setuptools<82"
```

**Setuptools removed `pkg_resources` after v81**, and Python 3.12 venvs no
longer install setuptools at all by default. Version 81.0.0 works. Confirmed:

| setuptools | `pkg_resources` |
|---|---|
| 84.0.0 | ✗ removed |
| 81.0.0 | ✓ |
| 80.9.0 | ✓ |

If the hidden error names something else (`librosa`, `scipy`), install that
instead.

---

## `ReadTimeout ... port=11434 ... read timeout=300`

Ollama didn't finish a script in time. Not a crash — an 8B model on a CPU runs
at 3–6 tokens/sec and a script is ~1500 tokens of JSON, so **5–8 minutes is
normal**. Raise it in `config.yaml`:

```yaml
models:
  ollama_timeout: 900
```

If that still isn't enough, either use a smaller model or switch
`models.writer` to `anthropic`, where the same script takes about ten seconds.

---

## `BrokenPipeError: [Errno 32] Broken pipe` during render

ffmpeg exited before we finished writing frames — almost always because it
couldn't open the **voice track**, which it opens first. The broken pipe is a
symptom; the cause is upstream.

Check the audio directly:

```bash
ls -la work/<slug>/
ffprobe work/<slug>/voice.mp3
```

Zero bytes or an ffprobe error confirms it. The renderer now pre-checks the
audio and reports ffmpeg's real stderr, so you should see a plain message
instead of this.

---

## `skipped: numbers with no traceable source in [...]`

Working as designed. A figure in the script matched nothing in `data/cars.csv`,
so it can't be cited and the build is blocked rather than publishing an
invented number.

Three ways forward:

1. Add the figure to `cars.csv` with a real source, then re-run
2. Pick a topic your data actually covers
3. Set `pipeline.require_sources: false` — **not recommended**; this guard is
   the main difference between this pipeline and the one that produced 479
   uploads and 2 likes

Check what the writer can see for a topic:

```bash
python -m autoedits.cars "nissan patrol vs land cruiser uae"
```

---

## The terminal fills with `y` forever

You typed `yes` at the shell prompt instead of into a program's confirmation
prompt. `yes` is a real command that prints "y" until stopped. **Ctrl+C.**

When a command asks `overwrite 'file'?`, answer with just `y`.

---

## Everything is slow to debug

Voice is 90% of the runtime and the part least likely to be broken. While
fixing anything else, switch to Kokoro:

```bash
sed -i 's/engine: chatterbox/engine: kokoro/' config.yaml
```

Renders drop from ~15 minutes to seconds. Switch back once the pipeline works
end to end.

Two commands that skip the slow parts entirely:

```bash
python -m autoedits.script "some topic"   # generate a script, render nothing
python -m autoedits.topics --probe        # test the search endpoint, 2 seconds
```

And if a render fails after the voice is already made, don't regenerate it:

```bash
python -m autoedits.pipeline --rebuild <slug>
```

---

## Topic discovery returns nothing

```bash
python -m autoedits.topics --probe
```

Healthy output ends with `{'ok': 2}`. If you see `HTTP 400` the suggestion host
is wrong — it should be `suggestqueries.google.com`, not the youtube-branded
one, which rejects these parameters.

Zero suggestions for a *complete sentence* is correct, not a fault:
autocomplete completes prefixes. Seeds must be openings (`is it worth buying`),
never finished questions.

If the filter summary shows most phrases dropped as `no region word`, the seed
has no UAE anchor of its own and nothing it generates will inherit one. Fix the
seed rather than loosening `must_contain_any` — the region filter is what keeps
you out of competition with the entire internet.
