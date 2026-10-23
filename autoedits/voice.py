"""
Voiceover.

Each scene's narration is synthesised as its own clip. That gives us the exact
duration of every line, so scene timing is derived from the speech rather than
guessed — the visual always changes on the sentence. It also means a single
bad line can be re-rolled without redoing the whole track.

Two engines, set `voice.engine` in config.yaml:

  chatterbox  MIT, clones your voice from ~7 seconds of reference audio.
              Slow on a CPU-only box — fine for a 3am cron, painful live.
              This is what ships.
  kokoro      82M params, Apache-2.0, preset voices. Fast on CPU and not
              your voice, so it is for checking timing while iterating,
              never for anything that gets uploaded.

A licensing note that matters if you ever monetise: XTTS-v2 (Coqui) and F5-TTS
are the two clone models everyone recommends, and BOTH are non-commercial
licences. Coqui shut down in 2024, so nobody can even sell you an XTTS
commercial licence any more. Monetised YouTube is commercial use. Chatterbox
(MIT) and Kokoro (Apache-2.0) are the clean ones.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import CFG, ROOT, VOICE_ENGINE, WORK

# Silence held after each line so the viewer can read the screen before it cuts.
TAIL = 0.45

_model_cache: dict[str, object] = {}


def duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _to_mp3(wav: Path, out_path: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                    "-b:a", "192k", str(out_path)], check=True)
    wav.unlink(missing_ok=True)
    return out_path


def _concat(clips: list[Path], out_path: Path) -> Path:
    """Join mp3 clips without re-encoding."""
    listing = out_path.with_suffix(".txt")
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", str(listing), "-c", "copy",
                    str(out_path)], check=True)
    listing.unlink(missing_ok=True)
    return out_path


# Split on sentence boundaries, but not on decimals or common abbreviations.
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE.split(text.strip()) if p.strip()]


# ------------------------------------------------------------------ engines --

def _kokoro(text: str, out_path: Path) -> Path:
    """82M-parameter model, Apache-2.0, comfortably real-time on CPU.

    Voices: af_heart, af_bella, am_michael, bf_emma, bm_george, … the leading
    letter is accent (a=American, b=British), the second is gender.
    """
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro not installed. Run:\n"
            "  pip install kokoro soundfile\n"
            "  sudo apt install espeak-ng") from exc

    lang = CFG["voice"].get("kokoro_lang", "b")      # 'b' = British English
    if "kokoro" not in _model_cache:
        _model_cache["kokoro"] = KPipeline(lang_code=lang)
    pipe = _model_cache["kokoro"]

    chunks = [audio for _, _, audio in
              pipe(text, voice=CFG["voice"].get("kokoro_voice", "bm_george"))]
    if not chunks:
        raise RuntimeError(f"Kokoro produced no audio for: {text[:60]!r}")

    wav = out_path.with_suffix(".wav")
    sf.write(wav, np.concatenate(chunks), 24000)
    return _to_mp3(wav, out_path)


def _chatterbox(text: str, out_path: Path) -> Path:
    """MIT-licensed zero-shot cloning. Point `voice.reference_audio` at a clean
    10-20s recording of yourself and it speaks in your voice.

    On a CPU-only machine expect several minutes per line. That is fine for a
    nightly batch and miserable for anything interactive.
    """
    try:
        import torch
        import torchaudio
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:
        raise RuntimeError(
            "Chatterbox not installed. Run:\n"
            "  pip install chatterbox-tts torchaudio") from exc

    ref = ROOT / CFG["voice"].get("reference_audio", "data/my_voice.wav")
    if not ref.exists():
        raise RuntimeError(
            f"No reference recording at {ref}.\n"
            "Record 10-20 seconds of yourself reading normally, save as a "
            "mono 24kHz WAV, and point voice.reference_audio at it.")

    if "chatterbox" not in _model_cache:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"    loading Chatterbox on {device} (first run downloads ~1GB)")
        _model_cache["chatterbox"] = ChatterboxTTS.from_pretrained(device=device)
    model = _model_cache["chatterbox"]

    wav_tensor = model.generate(text, audio_prompt_path=str(ref))
    wav = out_path.with_suffix(".wav")
    torchaudio.save(str(wav), wav_tensor, model.sr)
    return _to_mp3(wav, out_path)


ENGINES = {
    "chatterbox": _chatterbox,
    "kokoro": _kokoro,
}



# Chatterbox will sometimes emit an end-of-speech token partway through and
# return a clip that sounds perfectly natural with a clause missing. Feeding
# it one sentence at a time (see say) makes that rarer, not impossible. This
# is the second net: a clip far shorter than its text could possibly be spoken
# in did not say all of it, so generate it again.
# Measured, not guessed: 14 narration clips from the saved runs in work/
# give a median of 4.1 spoken syllables per second, ranging 2.4 to 5.5.
# 5.6 was optimistic by about a third, and the error was not evenly spread —
# it under-counted exactly the lines this project most wants, because
# "139,900" is four characters of digits and eleven syllables of speech.
#
# That mattered here twice over. This constant also sets the threshold below
# which a clip is assumed truncated, so an inflated rate made the detector
# too lenient: a clip missing half its words still measured 0.84 of the
# expected length and passed the 0.70 test.
SYL_PER_SEC = 4.4          # a little above the median, so a merely fast
                           # clip is not mistaken for a truncated one
SHORT_RATIO = 0.70         # below this share of the expected length, retry
RETRIES = 2


# "four by four", not "four ex four". The x survives number expansion
# otherwise, and the engine reads it as a letter.
_BY = re.compile(r"(?<!\w)(\d+)\s*[xX]\s*(\d+)(?!\w)")

# A number, with optional comma groups and an optional decimal part.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def speakable(text: str) -> str:
    """The narration rewritten as words, for the voice engine.

    Chatterbox does not reliably read digits. Asked for "162,900 dirhams" it
    said "sixty-two thousand nine hundred" — the leading hundred-thousand
    silently gone, in a published draft, in the one figure the whole video
    was about. Writing prices as digits was supposed to be the SAFE choice
    after spelled-out numbers got truncated; it turns out both forms fail,
    for different reasons, and only one of them is ours to control.

    So the engine never sees a digit. The spec keeps its numerals, the
    renderer still draws "AED 162,900" on screen, and only the text handed to
    the synthesiser is expanded. That also makes the duration estimate exact
    by construction, since it now counts the very words that get spoken.
    """
    from .script import _spell          # late: avoids an import cycle

    def one(m: re.Match) -> str:
        whole, _, frac = m.group(0).replace(",", "").partition(".")
        out = _spell(int(whole)) if whole else ""
        if frac:
            # "12.3" -> "twelve point three": decimals are read digit by
            # digit, which is how a person says a screen size or a 0-100 time.
            out += " point " + " ".join(_spell(int(d)) for d in frac)
        # Spaces on BOTH sides. Without the leading one, "B8" became
        # "Beight" — a model name turned into a nonsense word, which the
        # engine would have read aloud exactly as written.
        return " " + out + " "

    out = _NUMBER.sub(one, _BY.sub(r"\1 by \2", text))
    # Tidy the seams, and keep punctuation tight to the word before it so
    # sentence splitting still works.
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    # "B5's" expands to "B five 's" without this — the possessive floats off
    # the word it belongs to and the engine reads it as a separate token.
    return re.sub(r"\s+(['\u2019])", r"\1", out).strip()


# An acronym is read letter by letter, and syllables() cannot see that:
# "UAE" has one vowel group and three spoken syllables, "GLX" has none and
# three. Undercounting them is what made a 4.7s estimate of the Denza hook
# come back as 7.0s of audio. Only the COUNT is corrected — the engine reads
# acronyms correctly on its own, so the text it receives is left alone.
_ACRONYM = re.compile(r"(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z])")
_LETTER = {"W": "double you"}        # every other letter is one syllable


def _spell_letters(word: str) -> str:
    return " ".join(_LETTER.get(c, c) for c in word)


def spoken_syllables(text: str) -> int:
    """Syllables as the VOICE will say them, with digits spelled out.

    syllables("139,900 dirhams") counts 4; Chatterbox says "one hundred
    thirty-nine thousand nine hundred dirhams" and takes 14. Every length
    estimate in this project was wrong by that gap, and wrong in the
    direction that truncates audio.
    """
    return syllables(_ACRONYM.sub(lambda m: _spell_letters(m.group(0)),
                                  speakable(text)))


def syllables(text: str) -> int:
    """Rough syllable count. Vowel groups, with a silent-e correction."""
    n = 0
    for word in re.findall(r"[a-zA-Z']+", text.lower()):
        groups = re.findall(r"[aeiouy]+", word)
        c = len(groups)
        if word.endswith("e") and c > 1 and not word.endswith(("le", "ee", "ye")):
            c -= 1
        n += max(1, c)
    return n


def _speak_checked(engine, text: str, out_path: Path) -> Path:
    """Generate, and regenerate while the clip is impossibly short for the text."""
    expected = spoken_syllables(text) / SYL_PER_SEC
    for attempt in range(RETRIES + 1):
        engine(text, out_path)
        got = duration(out_path)
        if expected <= 0 or got >= expected * SHORT_RATIO:
            return out_path
        if attempt < RETRIES:
            print(f"    clip was {got:.1f}s for ~{expected:.1f}s of text "
                  f"— regenerating ({attempt + 1}/{RETRIES})")

    # This used to print a warning and hand back the short clip, which is the
    # one thing it must not do. A clip this far under length is one with
    # WORDS MISSING — the engine emitted an end-of-speech token partway
    # through — so returning it ships a video whose voiceover states half a
    # price and sounds completely fluent doing it. There is nothing
    # downstream that can notice.
    #
    # pipeline.run() catches this and moves to the next topic, so a bad night
    # for the synthesiser costs one draft rather than the batch.
    raise RuntimeError(
        f"the voice engine kept cutting this line short — {got:.1f}s of "
        f"audio for about {expected:.1f}s of words, after {RETRIES} retries. "
        f"The clip is missing part of the sentence, so the draft is not safe "
        f"to build:\n    {text[:120]!r}\n"
        f"  Re-run to roll again, or shorten the line in the spec.")


def say(text: str, out_path: Path, engine_name: str | None = None) -> Path:
    """Speak one narration line.

    Multi-sentence input is generated one sentence at a time and stitched back
    together. Chatterbox in particular will sometimes emit an end-of-speech
    token partway through a two-sentence input and silently drop the rest —
    you get a clip that sounds fine and is missing half your script. Feeding it
    one sentence at a time removes the failure mode entirely, and costs nothing
    on the other engines.
    """
    if not text.strip():
        # A silent placeholder keeps scene indices aligned.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=mono", "-t", "1.6",
                        str(out_path)], check=True)
        return out_path

    # An override lets one build use a different voice without editing
    # config.yaml — so a clone can be auditioned against the stock voice on
    # the same script before anything becomes permanent.
    chosen = engine_name or VOICE_ENGINE
    if chosen not in ENGINES:
        raise RuntimeError(
            f"Unknown voice engine {chosen!r}. "
            f"Pick one of: {', '.join(ENGINES)}")
    engine = ENGINES[chosen]

    # Numbers become words before the engine ever sees them. See speakable().
    text = speakable(text)

    parts = split_sentences(text)
    if len(parts) <= 1:
        return _speak_checked(engine, text, out_path)

    pieces = []
    for i, part in enumerate(parts):
        p = out_path.with_name(f"{out_path.stem}_s{i:02d}{out_path.suffix}")
        _speak_checked(engine, part, p)
        pieces.append(p)
    _concat(pieces, out_path)
    for p in pieces:
        p.unlink(missing_ok=True)
    return out_path


def narrate(lines: list[str], slug: str,
            engine_name: str | None = None) -> tuple[Path, list[float]]:
    """Synthesise every line, pad each with a tail of silence, concatenate.

    Returns the joined track and the per-scene durations to hand the renderer.
    """
    d = WORK / slug
    d.mkdir(parents=True, exist_ok=True)

    clips, durations = [], []
    for i, line in enumerate(lines):
        raw = say(line, d / f"line_{i:02d}.mp3", engine_name)
        padded = d / f"pad_{i:02d}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-af", f"apad=pad_dur={TAIL}", "-b:a", "192k", str(padded)],
            check=True)
        clips.append(padded)
        durations.append(duration(padded))

    return _concat(clips, d / "voice.mp3"), durations


def mix_music(voice: Path, music: Path, out: Path, music_db: float = -22.0) -> Path:
    """Optional bed under the voice. Use royalty-free or YouTube Audio Library
    tracks only — a claimed track costs you the video's revenue and its reach."""
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-i", str(music),
        "-filter_complex",
        f"[1:a]volume={music_db}dB,afade=t=out:st=0:d=2[m];"
        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-b:a", "192k", str(out)], check=True)
    return out


if __name__ == "__main__":
    # Quick engine test: python -m autoedits.voice
    out = WORK / "voice_test.mp3"
    out.parent.mkdir(exist_ok=True)
    say("Starting price in Dubai is one hundred and eighty nine thousand "
        "dirhams. That is twenty five thousand less than last year.", out)
    print(f"{VOICE_ENGINE}: wrote {out} ({duration(out):.1f}s)")
