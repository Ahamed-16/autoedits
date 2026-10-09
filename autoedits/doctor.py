"""
Pre-flight check.

    python -m autoedits.doctor

Walks every prerequisite in dependency order and tells you exactly what to run
for anything missing. Nothing here touches the network or costs money unless
you pass --live.

Run it after each setup step. When it's all green, the pipeline will work.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL = "\033[32m✓\033[0m", "\033[33m!\033[0m", "\033[31m✗\033[0m"
DIM, BOLD, END = "\033[2m", "\033[1m", "\033[0m"

results: list[tuple[str, str, str]] = []      # (state, label, fix)


def check(label: str, passed: bool, fix: str = "", warn_only: bool = False):
    state = OK if passed else (WARN if warn_only else FAIL)
    results.append((state, label, "" if passed else fix))
    print(f"  {state} {label}")
    if not passed and fix:
        for line in fix.strip().splitlines():
            print(f"      {DIM}{line}{END}")
    return passed


def section(title: str):
    print(f"\n{BOLD}{title}{END}")


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


# ============================================================ 1. the basics ==

def check_system():
    section("1. System")

    v = sys.version_info
    check(f"Python {v.major}.{v.minor}.{v.micro}", v >= (3, 10),
          "Need 3.10+.  sudo apt install python3.11 python3.11-venv")

    in_venv = sys.prefix != sys.base_prefix
    check("Running inside a virtualenv", in_venv,
          "python3 -m venv .venv && source .venv/bin/activate\n"
          "pip install -r requirements.txt",
          warn_only=True)

    check("ffmpeg", bool(shutil.which("ffmpeg")), "sudo apt install ffmpeg")
    check("ffprobe", bool(shutil.which("ffprobe")), "sudo apt install ffmpeg")

    fonts = ROOT / "assets" / "fonts"
    need = ["InterDisplay-Black.otf", "InterDisplay-Bold.otf", "Inter-SemiBold.otf",
            "Inter-Medium.otf"]
    missing = [f for f in need if not (fonts / f).exists()]
    check("Inter fonts bundled", not missing,
          f"Missing {missing} from assets/fonts/\n"
          "sudo apt install fonts-inter, then copy the .otf files across")

    for d in ("work", "data"):
        p = ROOT / d
        p.mkdir(exist_ok=True)
        check(f"{d}/ writable", os.access(p, os.W_OK), f"chmod u+w {p}")


def check_packages():
    section("2. Python packages")
    core = {"PIL": "Pillow", "requests": "requests", "yaml": "PyYAML",
            "dotenv": "python-dotenv", "streamlit": "streamlit"}
    for mod, pkg in core.items():
        check(pkg, has_module(mod), f"pip install {pkg}")

    yt = has_module("googleapiclient") and has_module("google_auth_oauthlib")
    check("google-api-python-client + google-auth-oauthlib", yt,
          "pip install google-api-python-client google-auth-oauthlib "
          "google-auth-httplib2\n(only needed when you're ready to upload)",
          warn_only=True)


# ========================================================== 3. config + env ==

def load_config():
    section("3. Configuration")

    cfg_path = ROOT / "config.yaml"
    if not check("config.yaml present", cfg_path.exists(),
                 "It ships with the project — re-extract the archive."):
        return None

    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text())
    except Exception as exc:                          # noqa: BLE001
        check("config.yaml parses", False, f"YAML error: {exc}")
        return None
    check("config.yaml parses", True)

    env = ROOT / ".env"
    check(".env present", env.exists(),
          "cp .env.example .env      # then fill in any keys you need",
          warn_only=True)

    writer = cfg.get("models", {}).get("writer")
    check(f"models.writer = {writer!r}", writer in {"groq", "ollama"},
          'Must be "groq" or "ollama" in config.yaml')

    engine = cfg.get("voice", {}).get("engine")
    check(f"voice.engine = {engine!r}",
          engine in {"chatterbox", "kokoro"},
          'Must be "chatterbox" (your voice) or "kokoro" (preset, for tests)')

    seeds = cfg.get("topics", {}).get("seeds") or []
    check(f"{len(seeds)} topic seed(s)", bool(seeds),
          "Add phrases under topics.seeds in config.yaml")
    return cfg


# ============================================================== 4. writer ====

def check_writer(cfg, live: bool):
    section("4. Writer (topic → script)")
    if not cfg:
        return
    writer = cfg["models"]["writer"]

    if writer == "groq":
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        key = os.getenv("GROQ_API_KEY", "")
        hint = ("console.groq.com -> API Keys -> Create API Key\n"
                "Then put it in .env as GROQ_API_KEY=gsk_...\n"
                "The free tier needs no card; adding one is what upgrades you.")
        near = _misnamed("GROQ_API_KEY") if not key else None
        if near:
            hint = (f"Found {near!r} in .env, which is not the same name.\n"
                    f"Environment variables are case-sensitive — rename it "
                    f"to GROQ_API_KEY and the value you already pasted works.")
        check("GROQ_API_KEY set", key.startswith("gsk_"), hint)
        if live and key:
            _ping_groq(key, cfg["models"].get("groq_model",
                                              "openai/gpt-oss-120b"))
        return

    host = cfg["models"]["ollama_host"]
    want = cfg["models"]["ollama_model"]
    have = False
    try:
        import requests
        tags = requests.get(f"{host}/api/tags", timeout=5).json()
        names = [m["name"] for m in tags.get("models", [])]
        check(f"Ollama reachable at {host}", True)
        have = any(n == want or n.startswith(want.split(":")[0]) for n in names)
        check(f"Model {want} pulled", have,
              f"ollama pull {want}\n"
              f"Currently installed: {', '.join(names) or 'none'}")
    except Exception:                                 # noqa: BLE001
        check(f"Ollama reachable at {host}", False,
              "Start it with:  ollama serve\n"
              f"Then:           ollama pull {want}")

    if live and have:
        _ping_ollama(host, want)


def _misnamed(want: str) -> str | None:
    """Find a .env entry that MEANS `want` but is spelled differently.

    os.getenv is an exact match, so GROQ_API_KEY and Groq_API_KEY are two
    unrelated variables and a capitalisation slip fails completely silently —
    the key is right there in the file and the program cannot see it.
    """
    try:
        text = (ROOT / ".env").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name != want and name.upper().replace("-", "_") == want:
            return name
    return None


def _ping_groq(key: str, model: str):
    """One tiny completion. Costs a handful of tokens out of the 200k/day
    free allowance and settles key, model and billing in one call."""
    import requests
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "content-type": "application/json"},
            json={"model": model, "max_completion_tokens": 8,
                  "messages": [{"role": "user", "content": "Say OK"}]},
            timeout=30)
        hint = f"HTTP {r.status_code}: {r.text[:180]}"
        if r.status_code == 401:
            hint = "Key rejected. Make a new one at console.groq.com/keys."
        elif r.status_code == 404:
            hint = (f"No such model {model!r}. Check models.groq_model "
                    f"against console.groq.com/docs/models.")
        elif r.status_code == 429:
            hint = "Key works, but you are rate limited right now. Wait a minute."
        check(f"Groq responds ({model})", r.status_code == 200, hint)
    except Exception as exc:                          # noqa: BLE001
        check("Groq responds", False, str(exc)[:180])


def _ping_ollama(host: str, model: str):
    """Actually generate a token. /api/tags can pass while the model itself
    fails to load — out of RAM, corrupt blob, wrong quant."""
    import requests
    try:
        r = requests.post(f"{host}/api/generate",
                          json={"model": model, "prompt": "Say OK",
                                "stream": False,
                                "options": {"num_predict": 4}},
                          timeout=180)
        ok = r.status_code == 200 and bool(r.json().get("response", "").strip())
        check(f"{model} generates", ok,
              f"HTTP {r.status_code}: {r.text[:180]}")
    except Exception as exc:                          # noqa: BLE001
        check(f"{model} generates", False, str(exc)[:180])


# =============================================================== 5. voice ====

def check_voice(cfg):
    section("5. Voice (script → speech)")
    if not cfg:
        return
    v = cfg["voice"]
    engine = v["engine"]

    if engine == "kokoro":
        ok = has_module("kokoro") and has_module("soundfile")
        check("kokoro + soundfile installed", ok,
              "pip install kokoro soundfile\nsudo apt install espeak-ng")
        check("espeak-ng", bool(shutil.which("espeak-ng")),
              "sudo apt install espeak-ng")

    elif engine == "chatterbox":
        check("chatterbox-tts installed", has_module("chatterbox"),
              "pip install chatterbox-tts torchaudio\n(~1GB on first run)")

        # resemble-perth 1.0.1 ships with an EMPTY dependency list, so pip
        # installs it without the libraries it imports. Its watermarker import
        # then fails, perth's __init__ swallows the ImportError and leaves the
        # class as None, and Chatterbox dies on load with the deeply unhelpful
        # "'NoneType' object is not callable".
        #
        # Most common cause on Python 3.12+: perth uses pkg_resources, which
        # lives in setuptools — and venvs stopped installing setuptools by
        # default in 3.12.
        check("setuptools (provides pkg_resources)", has_module("pkg_resources"),
              "pip install setuptools")

        if has_module("perth"):
            import perth
            check("perth watermarker loaded",
                  getattr(perth, "PerthImplicitWatermarker", None) is not None,
                  "Its import failed silently. Usually:\n"
                  "  pip install setuptools          # Python 3.12+\n"
                  "  pip install librosa scipy       # older environments\n"
                  "See the actual hidden error with:\n"
                  "  python -c \"from perth.perth_net.perth_net_implicit"
                  ".perth_watermarker import PerthImplicitWatermarker\"")

        ref = ROOT / v.get("reference_audio", "data/my_voice.wav")
        check(f"reference recording at {ref.relative_to(ROOT)}", ref.exists(),
              "Record 15-20s of yourself, then:\n"
              f"ffmpeg -i memo.m4a -ac 1 -ar 24000 {ref}")

    print(f"      {DIM}test it with:  python -m autoedits.voice{END}")


# ============================================================= 6. youtube ====

def check_youtube():
    section("6. YouTube upload  (only needed when you're ready to publish)")
    secret = ROOT / "client_secret.json"
    token = ROOT / "token.json"

    ok = check("client_secret.json", secret.exists(),
               "console.cloud.google.com → enable YouTube Data API v3\n"
               "→ Credentials → OAuth client ID → Desktop app → download JSON\n"
               "→ save it here as client_secret.json",
               warn_only=True)

    if ok:
        try:
            data = json.loads(secret.read_text())
            check("client_secret.json is a Desktop-app client",
                  "installed" in data,
                  'Wrong client type — recreate it as "Desktop app"')
        except json.JSONDecodeError:
            check("client_secret.json is valid JSON", False, "Re-download it")

    check("token.json (authorised)", token.exists(),
          "Run once:  python -c \"from autoedits import publish; publish.service()\"",
          warn_only=True)

    print(f"      {DIM}reminder: publish the OAuth consent screen, or refresh")
    print(f"      tokens expire after 7 days and your cron dies quietly{END}")


# ================================================================== main ====

def check_sources():
    """Are the legal claims backed by bodies entitled to make them?

    Sits in pre-flight rather than in the nightly run because it is not a
    transient failure — a badly sourced row stays badly sourced until someone
    replaces the URL, and it should be visible every time you check the rig.
    """
    section("Sources")
    try:
        from .cars import load_facts, usable_facts
        from .sources import LAW_CATEGORIES, audit, registry
    except Exception as exc:                          # noqa: BLE001
        check("source registry", False, f"cannot load: {exc}")
        return

    check(f"registry loaded ({len(registry())} domains)", bool(registry()),
          "data/sources.csv is missing or empty")

    rows = load_facts()
    law = [r for r in rows
           if (r.get("category") or "").strip() in LAW_CATEGORIES]
    problems = audit(rows)
    blocked = len(rows) - len(usable_facts())

    check(f"{len(law) - len(problems)}/{len(law)} legal claims officially "
          f"sourced", not problems,
          f"{len(problems)} rest on press or unlisted domains — "
          f"run: python -m autoedits.sources", warn_only=True)
    if blocked:
        check(f"{blocked} row(s) withheld from retrieval", True,
              warn_only=True)


def main() -> int:
    live = "--live" in sys.argv
    print(f"\n{BOLD}Auto Edits — pre-flight{END}")
    print(f"{DIM}{ROOT}{END}")

    check_system()
    check_packages()
    cfg = load_config()
    check_writer(cfg, live)
    check_voice(cfg)
    check_youtube()
    check_sources()

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]

    print(f"\n{BOLD}{'─' * 52}{END}")
    if not fails and not warns:
        print(f"{OK} Everything ready. Next:  python -m autoedits.topics")
    elif not fails:
        print(f"{OK} Core is ready — {len(warns)} optional item(s) outstanding.")
        print(f"  Next:  python -m autoedits.topics")
    else:
        print(f"{FAIL} {len(fails)} blocker(s) to fix:")
        for _, label, _ in fails:
            print(f"    · {label}")
    print()
    return len(fails)


if __name__ == "__main__":
    raise SystemExit(main())
