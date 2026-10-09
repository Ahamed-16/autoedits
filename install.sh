#!/usr/bin/env bash
# Auto Edits — one-shot installer for Debian/Ubuntu.
#
#   bash install.sh
#
# Installs system packages, creates a virtualenv, installs Python deps, and
# runs the pre-flight check. Safe to re-run; it skips anything already done.
# Nothing here needs an API key — the free path (Ollama + Kokoro) works after
# this script finishes.

set -euo pipefail
cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
dim()  { printf '\033[2m%s\033[0m\n' "$1"; }

bold "1/5  System packages"
if command -v apt-get >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg fonts-inter espeak-ng \
                            python3-venv python3-pip
else
    dim "Not a Debian/Ubuntu box — install these yourself:"
    dim "  ffmpeg, fonts-inter, espeak-ng, python3-venv"
fi

bold "2/5  Fonts"
mkdir -p assets/fonts
if [ ! -f assets/fonts/InterDisplay-Black.otf ]; then
    for f in InterDisplay-Black InterDisplay-Bold InterDisplay-SemiBold \
             Inter-Bold Inter-SemiBold Inter-Medium Inter-Regular; do
        cp "/usr/share/fonts/opentype/inter/$f.otf" assets/fonts/ 2>/dev/null || true
    done
fi
ls assets/fonts/*.otf >/dev/null 2>&1 \
    && dim "  fonts present" \
    || dim "  WARNING: no fonts found — see doctor output below"

bold "3/5  Virtualenv"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip

bold "4/5  Python packages"
pip install --quiet -r requirements.txt
dim "  installed"

bold "5/5  Config"
[ -f .env ] || { cp .env.example .env; dim "  created .env"; }
mkdir -p work data

echo
bash -c "source .venv/bin/activate && python -m autoedits.doctor" || true

cat <<'EOF'

Next, in order:

  source .venv/bin/activate

  1. Pull a local model so the writer works for free:
       ollama pull llama3.1:8b
     ...then set  models.writer: ollama  in config.yaml

  2. Test the voice:
       python -m autoedits.voice

  3. Fill the topic queue (takes a few minutes, it is polite to the endpoint):
       python -m autoedits.topics

  4. Build tonight's drafts:
       python -m autoedits.pipeline

  5. Review them:
       streamlit run review_app.py

YouTube upload can wait until you have something you actually want to publish.
EOF
