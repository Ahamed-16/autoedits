"""
Instagram Reels upload, through the Instagram API with Instagram Login.

    python -m autoedits.instagram --check        # is the token alive? posts nothing
    python -m autoedits.instagram --test-tunnel  # can Instagram reach this PC? posts nothing
    python -m autoedits.instagram --post 140     # post one video, by draft number
    python -m autoedits.instagram --pending      # post every new YouTube upload

Like publish.py, nothing here runs on its own: only videos you approved in
the review app are ever posted.

The token comes from INSTAGRAM_ACCESS_TOKEN in .env the first time. It lasts
60 days, so each renewal is saved to ig_token.json next to token.json (the
YouTube login), and that file is preferred from then on. Neither file may be
committed or shared: either one can post as the account.

Two things differ from YouTube and shape this file:

* Instagram will not take an upload. It fetches the video from a public HTTPS
  URL you give it, so a video has to be reachable publicly while it is
  processed. How that URL is made is the one open decision (see public_url).
* Publishing is two calls with a wait between them: create a container, poll
  until Instagram has finished processing the video, then publish it.
  Publishing early fails.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import db
from .config import CFG, ROOT

API = "https://graph.instagram.com"
VERSION = str(CFG.get("instagram", {}).get("api_version", "v24.0"))
TOKEN_FILE = ROOT / "ig_token.json"

# A token can only be renewed once it is at least a day old, and must be
# renewed before 60 days. Renewing at 45 leaves two weeks of slack for a
# machine that was off.
RENEW_AFTER_DAYS = 45

POLL_SECONDS = 10
POLL_LIMIT = 60            # ten minutes; a 30-second Reel takes well under one


class InstagramError(RuntimeError):
    pass


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _load() -> dict:
    """{"token": ..., "issued": epoch seconds or None}. Never printed."""
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        if data.get("token"):
            return data
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        raise InstagramError(
            "No Instagram token. Add INSTAGRAM_ACCESS_TOKEN=... to .env "
            "(App Dashboard -> Instagram -> API setup with Instagram login -> "
            "Generate token).")
    return {"token": token, "issued": None}


def _save(token: str) -> None:
    TOKEN_FILE.write_text(json.dumps({"token": token, "issued": _now()}))
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def _call(method: str, path: str, token: str, **params) -> dict:
    url = f"{API}/{VERSION}/{path.lstrip('/')}" if path != "refresh_access_token" \
        else f"{API}/refresh_access_token"
    params["access_token"] = token
    r = (requests.get(url, params=params, timeout=60) if method == "GET"
         else requests.post(url, data=params, timeout=120))
    try:
        body = r.json()
    except ValueError:
        body = {"error": {"message": r.text[:300]}}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        # The token is in the request, never in the message: Meta's errors
        # do not echo it, and nothing here formats the URL into one.
        raise InstagramError(f"{err.get('message', 'request failed')} "
                             f"(code {err.get('code')}, "
                             f"subcode {err.get('error_subcode')})")
    return body


def token() -> str:
    """A live token, renewed first if it is getting old."""
    data = _load()
    issued = data.get("issued")
    age_days = (_now() - issued) / 86400 if issued else None
    # A token straight from .env has an unknown age. Renew it on first use
    # so its age becomes known; renewal fails harmlessly if it is under a
    # day old, and the old one stays valid.
    if age_days is None or age_days >= RENEW_AFTER_DAYS:
        try:
            body = _call("GET", "refresh_access_token", data["token"],
                         grant_type="ig_refresh_token")
            _save(body["access_token"])
            return body["access_token"]
        except InstagramError:
            if age_days is not None and age_days >= 59:
                raise
    return data["token"]


def account(tok: str | None = None) -> dict:
    return _call("GET", "me", tok or token(),
                 fields="user_id,username,account_type,media_count")


def check() -> int:
    """Prove the login works without posting anything."""
    try:
        tok = token()
        me = account(tok)
    except InstagramError as exc:
        print(f"\n  Instagram login failed: {exc}\n")
        print("  Usual causes: the token was pasted with a space or quotes, "
              "it was generated\n  for a different account, or the account "
              "has not accepted the tester invite.\n")
        return 1
    print(f"\n  logged in as   @{me.get('username')}")
    print(f"  account type   {me.get('account_type')}")
    print(f"  posts          {me.get('media_count')}")
    try:
        lim = _call("GET", f"{me['user_id']}/content_publishing_limit", tok,
                    fields="quota_usage,config")
        row = (lim.get("data") or [{}])[0]
        total = (row.get("config") or {}).get("quota_total", "?")
        print(f"  API posts      {row.get('quota_usage', 0)} of {total} used "
              f"in the last 24 hours")
        print("\n  Publishing permission is granted. Nothing was posted.\n")
    except InstagramError as exc:
        print(f"\n  Logged in, but the publishing check failed: {exc}")
        print("  Add instagram_business_content_publish in Permissions and "
              "features, then\n  generate a new token.\n")
        return 1
    if me.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
        print("  The account is not a professional account; switch it to "
              "Business or Creator\n  in the Instagram app before posting.\n")
        return 1
    return 0


def publish_reel(video_url: str, caption: str) -> str:
    """Post a Reel from a public URL. Returns the Instagram media id."""
    tok = token()
    ig_id = account(tok)["user_id"]
    box = _call("POST", f"{ig_id}/media", tok, media_type="REELS",
                video_url=video_url, caption=caption[:2200],
                share_to_feed="true")["id"]
    for _ in range(POLL_LIMIT):
        status = _call("GET", box, tok, fields="status_code,status")
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram could not process the video: "
                                 f"{status.get('status', code)}")
        time.sleep(POLL_SECONDS)
    else:
        raise InstagramError("Instagram was still processing the video after "
                             "ten minutes; nothing was published")
    return _call("POST", f"{ig_id}/media_publish", tok,
                 creation_id=box)["id"]


# ------------------------------------------------------------- the tunnel --
#
# Instagram downloads the video from a public URL. The file is served from
# this computer through a Cloudflare quick tunnel: a temporary
# https://<random>.trycloudflare.com address, open only while one video posts.
# The local server answers for exactly one unguessable path and refuses
# everything else, so the tunnel exposes that file and nothing beside it.

ENABLED = bool(CFG.get("instagram", {}).get("enabled", False))
TUNNEL_WAIT = 60           # seconds for cloudflared to hand out an address
REACH_WAIT = 90            # and for that address to resolve from outside
# A quick tunnel's address is random words: https://frog-lamp-oak-mild.
# trycloudflare.com. "api.trycloudflare.com" also appears in cloudflared's
# output — in the error line when the tunnel could NOT be opened. Matching it
# once made a failed tunnel look like an open one, and the run then waited 90
# seconds on an address that never existed.
_URL = re.compile(r"https://(?!api\.)[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")
_FAILED = re.compile(r"failed to request quick tunnel|failed to unmarshal|"
                     r"error.*tunnel", re.I)


def _tunnel_line(line: str, found: list[str], errors: list[str]) -> None:
    """Sort one line of cloudflared output into an address or an error."""
    m = _URL.search(line)
    if m and not found:
        found.append(m.group(0))
    elif _FAILED.search(line) and not errors:
        errors.append(line.strip()[:200])


def _one_file_server(path: Path, name: str) -> http.server.ThreadingHTTPServer:
    size = path.stat().st_size

    class OneFile(http.server.BaseHTTPRequestHandler):
        def _send(self, head: bool):
            if self.path.split("?")[0] != f"/{name}":
                self.send_error(404)
                return
            start, end = 0, size - 1
            rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = int(rng.group(2)) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            if head:
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def do_GET(self):          # noqa: N802
            self._send(head=False)

        def do_HEAD(self):         # noqa: N802
            self._send(head=True)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OneFile)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@contextmanager
def public_url(video_path: str):
    """Yield a public HTTPS URL for one file; close everything afterwards."""
    exe = shutil.which("cloudflared")
    if not exe:
        raise InstagramError(
            "cloudflared is not installed. Install it once with:\n"
            "  curl -L -o /tmp/cloudflared.deb https://github.com/cloudflare/"
            "cloudflared/releases/latest/download/cloudflared-linux-amd64.deb\n"
            "  sudo dpkg -i /tmp/cloudflared.deb")
    path = Path(video_path)
    if not path.exists():
        raise InstagramError(f"video file not found: {video_path}")
    name = f"{secrets.token_hex(16)}.mp4"
    server = _one_file_server(path, name)
    port = server.server_address[1]
    proc = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    found: list[str] = []
    errors: list[str] = []

    def drain():                   # keep reading so cloudflared never blocks
        for line in proc.stdout:
            _tunnel_line(line, found, errors)

    threading.Thread(target=drain, daemon=True).start()
    try:
        deadline = time.time() + TUNNEL_WAIT
        while (not found and not errors and time.time() < deadline
               and proc.poll() is None):
            time.sleep(0.5)
        if errors and not found:
            raise InstagramError(f"cloudflared could not open a tunnel: {errors[0]}")
        if not found:
            raise InstagramError("cloudflared did not open a tunnel within "
                                 f"{TUNNEL_WAIT} seconds")
        url = f"{found[0]}/{name}"
        deadline = time.time() + REACH_WAIT
        while True:                # a new address takes a moment to resolve
            try:
                r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=10)
                if r.status_code in (200, 206):
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                raise InstagramError("the tunnel opened but the video was not "
                                     f"reachable from outside after {REACH_WAIT}s")
            time.sleep(3)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()


# ---------------------------------------------------------------- posting --

def caption(row) -> str:
    """Title, then the YouTube description, then a few hashtags.

    Links are not clickable in an Instagram caption, but the source lines
    stay: they are how a viewer checks a figure, and they cost nothing.
    """
    tags = json.loads(row["tags"] or "[]")
    hashtags = " ".join("#" + re.sub(r"[^a-z0-9]", "", t.lower())
                        for t in tags[:6] if re.sub(r"[^a-z0-9]", "", t.lower()))
    body = f"{row['title']}\n\n{row['description'] or ''}".strip()
    room = 2200 - len(hashtags) - 2
    return (body[:room].rstrip() + "\n\n" + hashtags).strip()


def post_video(row) -> str:
    with public_url(row["video_path"]) as url:
        return publish_reel(url, caption(row))


def post(video_id: int) -> str:
    """Post one video by draft number, whatever its Instagram status."""
    db.init()
    row = db.get_video(video_id)
    if row is None:
        raise InstagramError(f"no draft #{video_id}")
    if row["instagram_id"]:
        raise InstagramError(f"draft #{video_id} is already on Instagram "
                             f"(media {row['instagram_id']})")
    try:
        media = post_video(row)
    except Exception as exc:                          # noqa: BLE001
        db.mark_instagram(video_id, "failed", None, str(exc)[:500])
        raise
    db.mark_instagram(video_id, "posted", media)
    return media


def post_pending(limit: int = 5) -> list[tuple[int, str]]:
    """Post what reached YouTube and has not been tried on Instagram.

    A failure here is recorded against Instagram only. The YouTube upload
    already happened and stays counted, so one platform cannot undo the
    other.
    """
    db.init()
    done = []
    for row in db.ig_pending()[:limit]:
        try:
            media = post_video(row)
            db.mark_instagram(row["id"], "posted", media)
            done.append((row["id"], media))
        except Exception as exc:                      # noqa: BLE001
            db.mark_instagram(row["id"], "failed", None, str(exc)[:500])
            print(f"  Instagram failed for draft #{row['id']}: {str(exc)[:200]}")
    return done


def test_tunnel() -> int:
    """Open a tunnel to a tiny file and fetch it back. Posts nothing."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(b"\x00" * 4096)
    try:
        with public_url(fh.name) as url:
            host = url.split("/")[2]
            print(f"\n  tunnel open at {host}; the test file was reachable "
                  f"from outside.\n  Closed again. Nothing was posted.\n")
        return 0
    except InstagramError as exc:
        print(f"\n  {exc}\n")
        return 1
    finally:
        os.unlink(fh.name)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        raise SystemExit(check())
    if "--test-tunnel" in args:
        raise SystemExit(test_tunnel())
    if "--post" in args:
        vid = int(args[args.index("--post") + 1])
        try:
            media = post(vid)
        except InstagramError as exc:
            print(f"\n  {exc}\n")
            raise SystemExit(1)
        print(f"\n  draft #{vid} posted to Instagram (media {media})\n")
        raise SystemExit(0)
    if "--pending" in args:
        done = post_pending()
        for vid, media in done:
            print(f"  draft #{vid} posted to Instagram (media {media})")
        if not done:
            print("  Nothing new to post to Instagram.")
        raise SystemExit(0)
    print(__doc__)
