"""Instagram upload logic, with the network stubbed. Nothing is posted.

    python tests/test_instagram.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoedits import instagram as I                 # noqa: E402

SECRET = "IGAAsecret-token-value-123"


class _Net:
    """Fake graph.instagram.com. Records calls; never touches the network."""

    def __init__(self, refresh_ok=False, publish_scope=True, statuses=None):
        self.calls = []
        self.refresh_ok = refresh_ok
        self.publish_scope = publish_scope
        self.statuses = list(statuses or ["IN_PROGRESS", "FINISHED"])

    def __call__(self, method, path, token, **params):
        self.calls.append((method, path, params))
        if path == "refresh_access_token":
            if not self.refresh_ok:
                raise I.InstagramError("token too new to refresh (code 190)")
            return {"access_token": "IGAArenewed", "expires_in": 5184000}
        if path == "me":
            return {"user_id": "1784", "username": "theautoedits",
                    "account_type": "MEDIA_CREATOR", "media_count": 3}
        if path.endswith("content_publishing_limit"):
            if not self.publish_scope:
                raise I.InstagramError("missing permission (code 10)")
            return {"data": [{"quota_usage": 0, "config": {"quota_total": 100}}]}
        if path.endswith("/media"):
            return {"id": "box1"}
        if path == "box1":
            return {"status_code": self.statuses.pop(0)}
        if path.endswith("media_publish"):
            return {"id": "media99"}
        raise AssertionError(path)


def _run(net, fn, env_token=SECRET):
    real_call, real_file, real_sleep = I._call, I.TOKEN_FILE, I.time.sleep
    with tempfile.TemporaryDirectory() as tmp:
        I._call, I.TOKEN_FILE = net, Path(tmp) / "ig_token.json"
        I.time.sleep = lambda s: None
        import os
        old = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        os.environ["INSTAGRAM_ACCESS_TOKEN"] = env_token
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = fn()
            saved = I.TOKEN_FILE.read_text() if I.TOKEN_FILE.exists() else None
            return out, buf.getvalue(), saved
        finally:
            I._call, I.TOKEN_FILE, I.time.sleep = real_call, real_file, real_sleep
            if old is None:
                os.environ.pop("INSTAGRAM_ACCESS_TOKEN", None)
            else:
                os.environ["INSTAGRAM_ACCESS_TOKEN"] = old


def test_check_passes_and_never_prints_the_token():
    code, text, _ = _run(_Net(), I.check)
    assert code == 0, text
    assert "@theautoedits" in text and "Nothing was posted" in text, text
    assert SECRET not in text, "the token was printed"


def test_check_reports_a_missing_publish_permission():
    code, text, _ = _run(_Net(publish_scope=False), I.check)
    assert code == 1 and "content_publish" in text, text


def test_a_fresh_token_still_works_when_renewal_is_refused():
    """Meta will not renew a token under a day old. That must not break it."""
    tok, _, saved = _run(_Net(refresh_ok=False), I.token)
    assert tok == SECRET and saved is None


def test_a_renewed_token_is_saved_and_used():
    net = _Net(refresh_ok=True)
    tok, _, saved = _run(net, I.token)
    assert tok == "IGAArenewed", tok
    assert json.loads(saved)["token"] == "IGAArenewed"


def test_publish_waits_for_processing_before_publishing():
    net = _Net(statuses=["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    media, _, _ = _run(net, lambda: I.publish_reel("https://x/v.mp4", "cap"))
    assert media == "media99"
    paths = [p for _, p, _ in net.calls]
    assert paths.index("1784/media_publish") > max(
        i for i, p in enumerate(paths) if p == "box1"), paths


def test_a_failed_processing_never_publishes():
    net = _Net(statuses=["ERROR"])
    try:
        _run(net, lambda: I.publish_reel("https://x/v.mp4", "cap"))
    except I.InstagramError:
        pass
    else:
        raise AssertionError("an ERROR container was not refused")
    assert not any(p.endswith("media_publish") for _, p, _ in net.calls)



# ------------------------------------------------------- server and queue --

def test_the_server_exposes_one_file_and_nothing_else():
    import requests
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "v.mp4"
        f.write_bytes(bytes(range(256)) * 40)
        (Path(tmp) / ".env").write_text("SECRET=1")
        srv = I._one_file_server(f, "abc123.mp4")
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            ok = requests.get(f"{base}/abc123.mp4", timeout=5)
            assert ok.status_code == 200 and ok.content == f.read_bytes()
            part = requests.get(f"{base}/abc123.mp4",
                                headers={"Range": "bytes=10-19"}, timeout=5)
            assert part.status_code == 206 and part.content == f.read_bytes()[10:20]
            for bad in ("/", "/.env", "/v.mp4", "/../.env", "/abc123.mp4/x"):
                r = requests.get(base + bad, timeout=5)
                assert r.status_code == 404, f"{bad} answered {r.status_code}"
        finally:
            srv.shutdown()


def test_a_failed_tunnel_is_not_mistaken_for_an_open_one():
    """The real failure output from a blocked network. Its error line holds
    https://api.trycloudflare.com, which once passed for the tunnel."""
    lines = [
        "INF Thank you for trying Cloudflare Tunnel. Doing so, without a "
        "Cloudflare account, is a quick way to experiment",
        'failed to request quick Tunnel: Post "https://api.trycloudflare.com/'
        'tunnel": dial tcp: lookup api.trycloudflare.com: no such host']
    found, errors = [], []
    for l in lines:
        I._tunnel_line(l, found, errors)
    assert found == [], found
    assert errors and "failed to request" in errors[0]

    found, errors = [], []
    I._tunnel_line("INF |  https://frog-lamp-oak-mild.trycloudflare.com  |",
                   found, errors)
    assert found == ["https://frog-lamp-oak-mild.trycloudflare.com"], found


def _db():
    from autoedits import db as D
    import sqlite3
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "t.db"
    # An old database: the videos table as it was before Instagram.
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE videos (id INTEGER PRIMARY KEY, topic_id INTEGER,
        status TEXT NOT NULL, title TEXT, description TEXT, tags TEXT, scenes TEXT,
        video_path TEXT, poster_path TEXT, youtube_id TEXT, note TEXT,
        created_at TEXT NOT NULL, decided_at TEXT, published_at TEXT);
        INSERT INTO videos(id,status,title,created_at,published_at,tags)
          VALUES (1,'published','old video','2026-09-01','2026-09-02','[]'),
                 (2,'approved','queued video','2026-10-24',NULL,'[]');""")
    c.commit(); c.close()
    old = D.DB_PATH
    D.DB_PATH = path
    D.init()
    return D, old, tmp


def test_the_back_catalogue_is_not_posted():
    D, old, tmp = _db()
    try:
        assert D.get_video(1)["ig_status"] == "skipped"
        assert D.get_video(2)["ig_status"] is None
        assert [r["id"] for r in D.ig_pending()] == []
        D.mark_published(2, "yt2")
        assert [r["id"] for r in D.ig_pending()] == [2]
    finally:
        D.DB_PATH = old; tmp.cleanup()


def test_an_instagram_failure_leaves_youtube_alone():
    D, old, tmp = _db()
    real = I.post_video
    try:
        D.mark_published(2, "yt2")
        def boom(row):
            raise I.InstagramError("tunnel down")
        I.post_video = boom
        with redirect_stdout(io.StringIO()):
            assert I.post_pending() == []
        row = D.get_video(2)
        assert row["status"] == "published" and row["youtube_id"] == "yt2"
        assert row["ig_status"] == "failed" and "tunnel" in row["ig_note"]
        assert D.ig_pending() == [], "a failed post would retry every run"
    finally:
        I.post_video = real; D.DB_PATH = old; tmp.cleanup()


def test_the_caption_fits_and_carries_hashtags():
    row = {"title": "Motorcycle helmet fine in UAE", "description": "x" * 5000,
           "tags": json.dumps(["uae motorcycle", "helmet fine", "dubai"])}
    c = I.caption(row)
    assert len(c) <= 2200 and c.startswith("Motorcycle helmet fine")
    assert c.endswith("#uaemotorcycle #helmetfine #dubai"), c[-60:]


# ------------------------------------------------------------------ stats --

class _StatsNet:
    """Fake media and insights endpoints for three posted Reels."""

    def __init__(self, insights="ok", gone=(), blocked=False):
        self.calls = []
        self.insights, self.gone, self.blocked = insights, set(gone), blocked

    def __call__(self, method, path, token, **params):
        self.calls.append(path)
        if path == "refresh_access_token":
            raise I.InstagramError("too new (code 190)")
        if self.blocked:
            raise I.InstagramError("API access blocked. (code 200, subcode None)",
                                   code=200)
        media = path.split("/")[0]
        if media in self.gone:
            raise I.InstagramError("Unsupported get request. Object with ID "
                                   f"'{media}' does not exist (code 100, subcode 33)",
                                   code=100)
        if path.endswith("/insights"):
            if self.insights == "denied":
                raise I.InstagramError(
                    "(#10) Application does not have permission for this action "
                    "(code 10, subcode None)", code=10)
            if self.insights == "empty" or media == "m3":
                return {"data": []}            # a Reel under a day old
            return {"data": [
                {"name": "views", "values": [{"value": 1520}]},
                {"name": "reach", "values": [{"value": 1100}]},
                {"name": "likes", "values": [{"value": 41}]},
                {"name": "comments", "values": [{"value": 3}]},
                {"name": "saved", "values": [{"value": 7}]},
                {"name": "shares", "total_value": {"value": 5}},
                {"name": "ig_reels_avg_watch_time", "values": [{"value": 8400}]}]}
        return {"like_count": 40, "comments_count": 3, "id": media}


def _stats_db():
    from autoedits import db as D
    tmp = tempfile.TemporaryDirectory()
    old = D.DB_PATH
    D.DB_PATH = Path(tmp.name) / "t.db"
    D.init()
    with D.conn() as c:
        for vid, media in ((1, "m1"), (2, "m2"), (3, "m3"), (4, None)):
            c.execute("INSERT INTO videos(id,status,title,tags,created_at,"
                      "published_at,instagram_id,ig_status) VALUES "
                      "(?,?,?,?,?,?,?,?)",
                      (vid, "published", f"video {vid}", "[]", "2026-10-20",
                       "2026-10-21", media, "posted" if media else "skipped"))
    return D, old, tmp


def _stats(net):
    D, old, tmp = _stats_db()
    try:
        res, text, _ = _run(net, I.sync_metrics)
        return res, {r["id"]: dict(r) for r in D.ig_performance()}
    finally:
        D.DB_PATH = old; tmp.cleanup()


def test_stats_are_recorded_for_every_posted_reel():
    res, rows = _stats(_StatsNet())
    assert res["updated"] == 3 and not res["no_insights"], res
    assert set(rows) == {1, 2, 3}, "a video never posted to Instagram was listed"
    r = rows[1]
    assert (r["views"], r["reach"], r["likes"], r["saved"], r["shares"],
            r["avg_watch_ms"]) == (1520, 1100, 41, 7, 5, 8400), r
    assert r["like_rate"] == 2.7, r["like_rate"]


def test_a_new_reel_shows_blank_not_zero():
    """Meta returns an empty set for the first day or so, not zeros."""
    _, rows = _stats(_StatsNet())
    r = rows[3]
    assert r["views"] is None and r["reach"] is None, r
    assert r["likes"] == 40, "likes from the media itself should still show"


def test_without_the_insights_permission_likes_and_comments_still_come_back():
    net = _StatsNet(insights="denied")
    res, rows = _stats(net)
    assert res["updated"] == 3 and "permission" in res["no_insights"], res
    assert rows[1]["likes"] == 40 and rows[1]["views"] is None, rows[1]
    asked = [p for p in net.calls if p.endswith("/insights")]
    assert len(asked) == 1, f"asked for refused insights {len(asked)} times"


def test_a_deleted_post_is_skipped_not_fatal():
    res, rows = _stats(_StatsNet(gone={"m2"}))
    assert res["gone"] == [2] and res["updated"] == 2, res
    assert rows[2]["checked_at"] is None and rows[1]["views"] == 1520


def test_an_account_block_stops_and_is_not_taken_for_a_missing_permission():
    net = _StatsNet(blocked=True)
    res, rows = _stats(net)
    assert res["stopped"] and "blocked" in res["stopped"], res
    assert res["updated"] == 0 and not res["no_insights"], res
    assert len([p for p in net.calls if p != "refresh_access_token"]) == 1, net.calls


def test_a_newly_pasted_token_replaces_the_renewed_one():
    """After adding a permission you paste a new token into .env. The renewed
    token saved in ig_token.json predates it and lacks the permission."""
    net = _Net(refresh_ok=False)
    def go():
        I.TOKEN_FILE.write_text(json.dumps(
            {"token": "IGAAold-renewed", "issued": I._now(),
             "env_hash": I._env_hash("IGAAold-from-env")}))
        return I.token()
    tok, _, _ = _run(net, go, env_token="IGAAnew-with-insights")
    assert tok == "IGAAnew-with-insights", "the new .env token was ignored"

    def same():
        I.TOKEN_FILE.write_text(json.dumps(
            {"token": "IGAAold-renewed", "issued": I._now(),
             "env_hash": I._env_hash(SECRET)}))
        return I.token()
    tok, _, _ = _run(net, same)
    assert tok == "IGAAold-renewed", "the renewed token was dropped for no reason"


def test_the_stats_report_never_prints_the_token():
    D, old, tmp = _stats_db()
    try:
        code, text, _ = _run(_StatsNet(insights="denied"), I.stats_report)
    finally:
        D.DB_PATH = old; tmp.cleanup()
    assert code == 0 and SECRET not in text, text
    assert "manage_insights" in text and "1,520" not in text, text


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
    raise SystemExit(bad)
