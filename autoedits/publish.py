"""
YouTube upload + performance readback.

Nothing here runs without you approving it first — the pipeline only ever
produces drafts, and `upload_approved` picks up what you ticked in the review
app. First run opens a browser for OAuth and caches the token locally.
"""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from . import db
from .config import CFG, ROOT

# The first two cover uploading and reading your own video list. The third is
# a different API entirely: views and likes come from the Data API, but
# retention, traffic sources and impressions only exist in Analytics. Adding a
# scope invalidates the saved token, so changing this list means re-authorising
# once — see autoedits/analytics.py.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
SECRETS = ROOT / "client_secret.json"
TOKEN = ROOT / "token.json"


def credentials():
    """The authorised credentials, so other modules can build their own client.

    analytics.py needs a *different* Google service off the same login. Reaching
    into the returned Resource for its credentials works until it doesn't —
    that attribute is private and has moved between library versions.
    """
    creds = None
    if TOKEN.exists() and _token_matches_secrets():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError as exc:
                # The usual cause is the seven-day expiry Google applies to
                # refresh tokens while the OAuth consent screen is in Testing.
                # Re-authorising interactively is the whole fix, so do it here
                # rather than ending the run in a traceback the caller cannot
                # act on. See token_status() for the permanent cure.
                print(f"Saved login is dead ({str(exc)[:60]}…). "
                      "Re-authorising — a browser window will open.")
                creds = None

        if not refreshed and not creds:
            if not SECRETS.exists():
                raise RuntimeError(
                    f"Missing {SECRETS}. In Google Cloud Console: enable the "
                    "YouTube Data API v3, create an OAuth client of type "
                    "'Desktop app', download the JSON here.")
            creds = InstalledAppFlow.from_client_secrets_file(
                str(SECRETS), SCOPES).run_local_server(port=0)
        TOKEN.write_text(creds.to_json())
    return creds


def _token_matches_secrets() -> bool:
    """Does the saved token belong to the OAuth client we currently hold?

    Downloading a fresh client_secret.json mints a NEW client id. The old
    token.json is then bound to a client that no longer applies, and Google
    rejects it as invalid_grant — the same error text you get from an expired
    token, which sends you off fixing the wrong thing. Catch it by comparing
    the two ids directly instead of guessing from the error message.
    """
    if not SECRETS.exists():
        return True
    try:
        tok = json.loads(TOKEN.read_text()).get("client_id")
        sec = json.loads(SECRETS.read_text())
        cur = (sec.get("installed") or sec.get("web") or {}).get("client_id")
    except (OSError, ValueError):
        return True
    if tok and cur and tok != cur:
        print("client_secret.json is a different OAuth client than the one "
              "token.json was issued for — that token can never work again. "
              "Re-authorising against the new client.")
        return False
    return True


def service():
    return build("youtube", "v3", credentials=credentials())


def upload(video_path: str, title: str, description: str, tags: list[str],
           privacy: str = "public", publish_at: str | None = None) -> str:
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:20],
            "categoryId": "2",           # Autos & Vehicles
        },
        "status": {
            "privacyStatus": "private" if publish_at else privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at   # RFC3339, schedules the post

    req = service().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True))

    response = None
    while response is None:
        _, response = req.next_chunk()
    return response["id"]


def upload_approved(limit: int = 5, privacy: str = "public") -> list[tuple[int, str]]:
    """Ship everything you approved. Returns (video_id, youtube_id) pairs."""
    done = []
    for row in db.approved()[:limit]:
        try:
            yt_id = upload(row["video_path"], row["title"], row["description"],
                           json.loads(row["tags"] or "[]"), privacy=privacy)
            db.mark_published(row["id"], yt_id)
            done.append((row["id"], yt_id))
        except Exception as exc:                      # noqa: BLE001
            db.set_status(row["id"], "failed", str(exc)[:500])
    return done


def sync_metrics() -> int:
    """Pull view/like/comment counts for everything published, into the DB.

    This is the feedback loop: after twenty videos you can sort your own hooks
    by like rate and stop guessing what works.
    """
    rows = [r for r in db.performance() if r["youtube_id"]]
    if not rows:
        return 0
    yt = service()
    updated = 0
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        resp = yt.videos().list(
            part="statistics",
            id=",".join(r["youtube_id"] for r in batch)).execute()
        stats = {it["id"]: it["statistics"] for it in resp.get("items", [])}
        for r in batch:
            s = stats.get(r["youtube_id"])
            if s:
                db.record_metrics(r["id"], int(s.get("viewCount", 0)),
                                  int(s.get("likeCount", 0)),
                                  int(s.get("commentCount", 0)))
                updated += 1
    return updated


def token_status() -> int:
    """Is the YouTube connection still alive, and for how long?

    While the Google Cloud project sits in Testing mode a refresh token dies
    after seven days, and the failure is silent: uploads simply stop and the
    drafts pile up in the Approved tab looking fine. Worth one command a week.
    """
    if not TOKEN.exists():
        print(f"No token at {TOKEN}. Run:  python -m autoedits.publish --auth")
        return 1

    data = json.loads(TOKEN.read_text())
    expiry = data.get("expiry", "unknown")
    try:
        yt = service()
        me = yt.channels().list(part="snippet", mine=True).execute()
        name = me["items"][0]["snippet"]["title"]
        print(f"Connected to YouTube as: {name}")
        print(f"Access token expires   : {expiry}  (auto-refreshed)")
        print("Upload path is working.")
        return 0
    except Exception as exc:                          # noqa: BLE001
        print(f"YouTube connection is BROKEN: {type(exc).__name__}: "
              f"{str(exc)[:200]}")
        print(f"\nFix it with:\n  python -m autoedits.publish --auth")
        print("\nIf this keeps happening every week, the cause is not the "
              "token — it is the consent screen. In Google Cloud Console → "
              "APIs & Services → OAuth consent screen, change Publishing "
              "status from 'Testing' to 'In production'. Testing-mode refresh "
              "tokens are killed after seven days by design; published ones "
              "last until you revoke them. You will see an 'unverified app' "
              "warning at sign-in — click Advanced → Go to (app), it is your "
              "own app and only you use it.")
        return 1


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    if "--check" in args:
        raise SystemExit(token_status())

    if "--auth" in args:
        # Re-authorise from scratch. Opens a browser.
        TOKEN.unlink(missing_ok=True)
        raise SystemExit(token_status())

    if "--metrics" in args:
        n = sync_metrics()
        print(f"Updated stats for {n} published video(s).")
        raise SystemExit(0)

    pending = db.approved()
    if not pending:
        print("Nothing approved. Approve drafts first: streamlit run review_app.py")
        raise SystemExit(0)

    print(f"Uploading {len(pending)} approved video(s)…")
    done = upload_approved()
    for vid, yt_id in done:
        print(f"  draft #{vid} → https://youtu.be/{yt_id}")
    failed = len(pending) - len(done)
    if failed:
        print(f"  {failed} failed — check the note column in the database, or "
              f"run: python -m autoedits.publish --check")
    raise SystemExit(1 if failed else 0)
