"""
Pull YouTube Analytics into the repo, so the numbers stop living in screenshots.

    python -m autoedits.analytics            # last 28 days
    python -m autoedits.analytics 90         # last 90 days

Views, likes and comments come from the Data API and are already handled by
`publish.py --metrics`. Everything that actually tells you whether a video
worked — how far people watch, and where they arrived from — lives in the
*Analytics* API, which is a separate service and a separate OAuth scope.

That scope was added to publish.SCOPES, which invalidates the token you have.
Before this works, once:

    1. In Google Cloud Console, enable "YouTube Analytics API" on the same
       project as your existing OAuth client.
    2. python -m autoedits.publish --auth

Written to data/analytics.csv so it can be diffed week to week.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import db
from .audit import _seconds
from .config import ROOT
from .publish import credentials, service, SCOPES

OUT = ROOT / "data" / "analytics.csv"

# averageViewPercentage is the closest API equivalent of the "stayed to watch"
# figure Studio shows on a Short. It is the one number worth watching.
VIDEO_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,"
                 "averageViewPercentage,likes,comments,subscribersGained")


def _client():
    return build("youtubeAnalytics", "v2", credentials=credentials())


def _range(days: int) -> tuple[str, str]:
    end = date.today() - timedelta(days=1)      # today is always incomplete
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def by_video(days: int = 28) -> list[dict]:
    start, end = _range(days)
    try:
        resp = _client().reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics=VIDEO_METRICS, dimensions="video",
            sort="-views", maxResults=200).execute()
    except HttpError as exc:
        print(f"  (per-video report unavailable: {str(exc)[:80]})")
        return []

    cols = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = [dict(zip(cols, r)) for r in resp.get("rows", [])]

    # Analytics returns ids and nothing else. Reading the local database only
    # names the handful this pipeline published, which left 133 rows as raw
    # ids — a report you cannot act on. Names come from the Data API instead.
    meta = _meta([r["video"] for r in rows if r.get("video")])
    for r in rows:
        title, length = meta.get(r.get("video"), ("", 0))
        r["title"] = title
        r["length_s"] = length
        # A Short that loops counts the replay, so averageViewPercentage runs
        # past 100. That is not an error — it is the strongest signal in here.
        r["loops"] = round((r.get("averageViewDuration") or 0) / length, 2) \
            if length else ""
    return rows


def _meta(ids: list[str]) -> dict[str, tuple[str, int]]:
    """Title and length for each video id, from the Data API."""
    yt, out = service(), {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet,contentDetails",
                                id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            out[it["id"]] = (it["snippet"]["title"],
                             _seconds(it["contentDetails"].get("duration", "")))
    return out


def traffic(days: int = 28) -> list[dict]:
    """Views by traffic source.

    subscribersGained is NOT a supported metric alongside
    insightTrafficSourceType — the API rejects the whole query rather than
    dropping the column, and that refusal used to kill the entire run. Which
    source converts has to be inferred from the per-video table instead.
    """
    start, end = _range(days)
    try:
        resp = _client().reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType", sort="-views").execute()
    except HttpError as exc:
        print(f"  (traffic-source report unavailable: {str(exc)[:80]})")
        return []
    cols = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in resp.get("rows", [])]


def run(days: int = 28) -> int:
    start, end = _range(days)
    print(f"\nYouTube Analytics — {start} to {end}\n")

    src = traffic(days)
    if src:
        total = sum(r["views"] for r in src) or 1
        print("Where the views came from:")
        for r in src:
            print(f"  {r['insightTrafficSourceType']:<24} {r['views']:>7,}  "
                  f"{100 * r['views'] / total:5.1f}%")

    rows = by_video(days)
    if not rows:
        print("\nNo per-video rows returned for this window.")
        return 0

    print(f"\nTop videos by views ({len(rows)} in the window):")
    print(f"  {'views':>7}  {'watched':>7}  {'loops':>5} {'subs':>5} {'/1k':>6}  title")
    for r in rows[:20]:
        pct = r.get("averageViewPercentage") or 0
        loops = r.get("loops") or 0
        subs = r.get("subscribersGained", 0) or 0
        per1k = 1000 * subs / r["views"] if r["views"] else 0
        name = (r.get("title") or r.get("video", ""))[:46]
        print(f"  {r['views']:>7,}  {pct:>6.1f}%  {loops:>5.2f} {subs:>5} "
              f"{per1k:>6.2f}  {name}")

    # The number this channel actually turns on. A video can be watched to the
    # end and still convert nobody: retention says the video worked, subs per
    # thousand says the CHANNEL worked. They are different problems with
    # different fixes, and only one of them is about the video you just made.
    conv = [r for r in rows if r["views"] >= 30]
    if conv:
        best = max(conv, key=lambda r: (r.get("subscribersGained", 0) or 0) / r["views"])
        b = (best.get("subscribersGained", 0) or 0)
        print(f"\nBest converter (30+ views): {1000 * b / best['views']:.2f} "
              f"subs per 1,000 — {(best.get('title') or '')[:44]}")
        dead = sum(1 for r in conv if not r.get("subscribersGained"))
        print(f"{dead} of {len(conv)} videos with 30+ views gained no "
              f"subscribers at all.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader(); w.writerows(rows)
    print(f"\nFull table: {OUT}")
    print("Anything under about 30% stayed is the format failing, not the "
          "topic.\n")
    return 0


if __name__ == "__main__":
    if "yt-analytics.readonly" not in " ".join(SCOPES):
        print("The analytics scope is missing from publish.SCOPES.")
        raise SystemExit(1)
    n = next((int(a) for a in sys.argv[1:] if a.isdigit()), 28)
    raise SystemExit(run(n))
