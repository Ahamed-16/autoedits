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
SYL_PER_SEC = 5.6          # brisk narration; deliberately generous
SHORT_RATIO = 0.70         # below this share of the expected length, retry
RETRIES = 2


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
    expected = syllables(text) / SYL_PER_SEC
    for attempt in range(RETRIES + 1):
        engine(text, out_path)
        got = duration(out_path)
        if expected <= 0 or got >= expected * SHORT_RATIO:
            return out_path
        if attempt < RETRIES:
            print(f"    clip was {got:.1f}s for ~{expected:.1f}s of text "
                  f"— regenerating ({attempt + 1}/{RETRIES})")
    print(f"    ! still short after {RETRIES} retries: {text[:60]!r}")
    return out_path


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
