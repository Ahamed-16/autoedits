"""Upload bookkeeping: what a failed upload leaves behind. Nothing is uploaded.

The bug this guards: three approved videos (#44-46) hit an expired YouTube
login on 17 Sep, were marked `failed`, and sat there for five weeks, because
`failed` had no way back. Two Instagram posts (#141-142) went the same way
when Meta put the developer account on hold. A login or access problem is
not the video's fault, so it must leave the video queued.

    python tests/test_publish.py
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits import db as D                      # noqa: E402
from autoedits import instagram as I               # noqa: E402
from autoedits import publish as P                 # noqa: E402

_GOOD_SCENES = [
    {"type": "hook", "narration": "What does a Hilux cost?"},
    {"type": "stat", "label": "Hilux from", "value": 120900,
     "narration": "The Hilux starts at 120,900 dirhams."},
    {"type": "verdict", "narration": "Start with the GL."},
    {"type": "question", "narration": "Petrol or diesel?"}]
_THIN_SCENES = [
    {"type": "hook", "narration": "Quick question, quick answer."},
    {"type": "verdict", "narration": "Longer warranties can save you money."},
    {"type": "question", "narration": "Pick the one that fits your needs."}]


def _with_db(fn):
    old = D.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        D.DB_PATH = Path(tmp) / "t.db"
        try:
            D.init()
            with D.conn() as c:
                for vid, status, scenes in ((1, "approved", _GOOD_SCENES),
                                            (2, "approved", _GOOD_SCENES),
                                            (3, "failed", _THIN_SCENES),
                                            (4, "failed", _GOOD_SCENES)):
                    c.execute(
                        "INSERT INTO videos(id,status,title,description,tags,"
                        "scenes,video_path,created_at,decided_at,note) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?)",
                        (vid, status, f"Toyota Hilux 2027 price in UAE {vid}", "",
                         "[]", json.dumps(scenes), f"/x/{vid}.mp4",
                         "2026-10-01", f"2026-10-0{vid}",
                         "invalid_grant: Token has been expired or revoked."
                         if status == "failed" else None))
            return fn()
        finally:
            D.DB_PATH = old


def _run(fn):
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = fn()
    return out, buf.getvalue()


def test_an_expired_login_leaves_videos_queued_and_stops():
    calls = []

    def upload(*a, **k):
        calls.append(a[0])
        raise P.RefreshError("invalid_grant: Token has been expired or revoked.")

    def go():
        real = P.upload
        P.upload = upload
        try:
            done, text = _run(lambda: P.upload_approved())
        finally:
            P.upload = real
        return done, text, [D.get_video(i)["status"] for i in (1, 2)], \
            D.get_video(1)["note"]

    done, text, statuses, note = _with_db(go)
    assert done == [] and statuses == ["approved", "approved"], statuses
    assert len(calls) == 1, "kept uploading after the login was known dead"
    assert "login" in (note or "").lower(), note
    assert "--auth" in text, text


def test_a_broken_video_is_still_marked_failed():
    def upload(*a, **k):
        raise FileNotFoundError("/x/1.mp4")

    def go():
        real = P.upload
        P.upload = upload
        try:
            _run(lambda: P.upload_approved())
        finally:
            P.upload = real
        return D.get_video(1)["status"]

    assert _with_db(go) == "failed"


def test_retry_rechecks_the_video_first():
    """#44-46 were the early three-line format with no figures; today's
    pipeline would refuse to build them, so they must not be re-queued."""
    def go():
        thin, t1 = _run(lambda: P.retry(3))
        good, t2 = _run(lambda: P.retry(4))
        return thin, good, D.get_video(3)["status"], D.get_video(4)["status"], t1

    thin, good, s3, s4, text = _with_db(go)
    assert not thin and s3 == "failed", (s3, text)
    assert good and s4 == "approved", s4


def test_discard_retires_a_stuck_video():
    def go():
        _run(lambda: P.discard(3))
        return D.get_video(3)["status"]
    assert _with_db(go) == "rejected"


def test_an_instagram_access_block_leaves_the_post_pending():
    """Meta's account hold returned 'API access blocked (code 200)'. The two
    videos it hit were marked failed and would never have been posted."""
    calls = []

    def post_video(row):
        calls.append(row["id"])
        raise I.InstagramError("API access blocked. (code 200, subcode None)",
                               code=200)

    def go():
        D.mark_published(1, "yt1")
        D.mark_published(2, "yt2")
        real = I.post_video
        I.post_video = post_video
        try:
            _run(lambda: I.post_pending())
        finally:
            I.post_video = real
        return [D.get_video(i)["ig_status"] for i in (1, 2)], \
            D.get_video(1)["ig_note"], [r["id"] for r in D.ig_pending()]

    statuses, note, pending = _with_db(go)
    assert statuses == [None, None], statuses
    assert len(calls) == 1, "kept posting after access was known blocked"
    assert "blocked" in (note or ""), note
    assert pending == [1, 2], pending


def test_an_instagram_processing_failure_is_marked_failed():
    def post_video(row):
        raise I.InstagramError("Instagram could not process the video: ERROR")

    def go():
        D.mark_published(1, "yt1")
        real = I.post_video
        I.post_video = post_video
        try:
            _run(lambda: I.post_pending())
        finally:
            I.post_video = real
        return D.get_video(1)["ig_status"]

    assert _with_db(go) == "failed"


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as exc:
                bad += 1
                print(f"FAIL  {name}  {exc}")
            except Exception as exc:                  # noqa: BLE001
                bad += 1
                print(f"ERROR {name}  {type(exc).__name__}: {exc}")
    raise SystemExit(bad)
