"""Auto Edits — assisted production pipeline.

This file exists for one reason: to catch the mistake that has now cost two
runs. `python -m autoedits.<anything>` imports this package before it imports
the module you asked for, which makes it the only place a warning can land
*ahead* of an ImportError from a dependency that lives in the virtualenv.

Almost nothing here works on the system interpreter — Kokoro, the Google API
client, Streamlit and Pillow are all installed into .venv. The traceback you
get instead ("No module named 'googleapiclient'") describes the symptom and
not the cause, so it gets fixed by installing things system-wide, which then
leaves two half-configured environments.
"""

import sys as _sys
from pathlib import Path as _Path

_VENV = _Path(__file__).resolve().parent.parent / ".venv"

if _VENV.is_dir() and not _Path(_sys.prefix).resolve() == _VENV.resolve():
    _sys.stderr.write(
        "\n  ! Running on {exe}\n"
        "    not the project virtualenv at {venv}\n\n"
        "    Most dependencies are installed there, so imports below this\n"
        "    line will fail. Fix it with:\n\n"
        "        source .venv/bin/activate\n\n".format(
            exe=_sys.executable, venv=_VENV)
    )
