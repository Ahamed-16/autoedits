"""
Back-catalogue audit.

    python -m autoedits.audit

Lists every video on the channel — title, date, length, views, privacy — into
data/channel_audit.csv, and prints a summary you can act on.

Why this exists: the Partner Program review looks at the *channel*, not the
video you happen to be proud of. A library of short compilations and reposted
news clips is exactly the profile that gets an application rejected under the
"original and authentic" rule, and you cannot make that judgement from a
Studio page that shows thirty rows at a time. This gives you all of them at
once, sorted, so the decision is yours and it is informed.

Read-only. It uses the YouTube credentials you already authorised and changes
nothing on the channel.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime, timezone

from .config import ROOT
from .publish import service

OUT = ROOT / "data" / "channel_audit.csv"

# ISO 8601 durations, as returned by contentDetails.duration ("PT1M30S").
_DUR = re.compile(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _seconds(iso: str) -> int:
    m = _DUR.match(iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _uploads_playlist(yt) -> str:
    resp = yt.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("The authorised account has no channel.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _video_ids(yt, playlist_id: str) -> list[str]:
    ids, page = [], None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails", playlistId=playlist_id,
            maxResults=50, pageToken=page).execute()
        ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        page = resp.get("nextPageToken")
        if not page:
            break
    return ids


def collect() -> list[dict]:
    yt = service()
    ids = _video_ids(yt, _uploads_playlist(yt))
    rows = []
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(
            part="snippet,statistics,contentDetails,status",
            id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            stats = it.get("statistics", {})
            secs = _seconds(it["contentDetails"].get("duration", ""))
            rows.append({
                "video_id": it["id"],
                "title": it["snippet"]["title"],
                "published": it["snippet"]["publishedAt"][:10],
                "seconds": secs,
                "format": "short" if secs <= 60 else "long",
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "privacy": it["status"].get("privacyStatus", ""),
                "url": f"https://youtu.be/{it['id']}",
            })
    return rows


def report(rows: list[dict]) -> None:
    if not rows:
        print("No videos found on the authorised channel.")
        return

    total_views = sum(r["views"] for r in rows)
    dead = [r for r in rows if r["views"] < 10]
    quiet = [r for r in rows if r["views"] < 100]
    this_year = datetime.now(timezone.utc).year

    print(f"\n{len(rows)} videos, {total_views:,} lifetime views")
    print(f"  under 100 views : {len(quiet):>4}  "
          f"({100 * len(quiet) / len(rows):.0f}% of the library)")
    print(f"  under 10 views  : {len(dead):>4}")

    by_year = Counter(r["published"][:4] for r in rows)
    print("\nUploads by year:")
    for year in sorted(by_year):
        share = sum(r["views"] for r in rows if r["published"][:4] == year)
        mark = "  <- this year" if year == str(this_year) else ""
        print(f"  {year}  {by_year[year]:>4} videos   {share:>9,} views{mark}")

    fmt = Counter(r["format"] for r in rows)
    print(f"\nShorts (<=60s): {fmt['short']}   Long: {fmt['long']}")

    print("\nYour 10 most-watched — these are the ones worth protecting:")
    for r in sorted(rows, key=lambda r: -r["views"])[:10]:
        print(f"  {r['views']:>8,}  {r['published']}  {r['title'][:58]}")

    # The concentration is the number that decides the back-catalogue question.
    ranked = sorted(rows, key=lambda r: -r["views"])
    top20 = sum(r["views"] for r in ranked[:20])
    if total_views:
        print(f"\nYour top 20 videos carry {100 * top20 / total_views:.0f}% of "
              f"all views. The rest of the library is {len(rows) - 20} videos "
              f"holding the other {100 - 100 * top20 / total_views:.0f}%.")


def likes(rows: list[dict], include_long: bool = False) -> None:
    """Likes per video in the terminal, worst-to-best on the rate.

    Views tell you the algorithm showed it to people. Likes tell you they
    were glad it did — which is the half you control by writing a better
    script. A Short doing 2-5% is healthy; under 1% means the format landed
    but the content did not, and that distinction is invisible in a views
    column.

    Rate is only meaningful once a video has been seen, so anything under
    MIN_VIEWS is listed separately rather than shown with a wild percentage
    off three views.
    """
    MIN_VIEWS = 20

    pick = rows if include_long else [r for r in rows if r["format"] == "short"]
    if not pick:
        print("\nNo Shorts found on the channel.")
        return

    label = "videos" if include_long else "Shorts"
    tv = sum(r["views"] for r in pick)
    tl = sum(r["likes"] for r in pick)
    print(f"\nLikes on your {label} — {len(pick)} videos, {tv:,} views, "
          f"{tl:,} likes ({100 * tl / tv if tv else 0:.2f}% overall)\n")

    rated = [r for r in pick if r["views"] >= MIN_VIEWS]
    thin = [r for r in pick if r["views"] < MIN_VIEWS]

    def rate(r):
        return 100 * r["likes"] / r["views"] if r["views"] else 0.0

    print(f"  {'likes':>6} {'views':>7} {'like%':>7}  {'published':<11} title")
    for r in sorted(rated, key=rate, reverse=True):
        flag = "  " if rate(r) >= 2 else ("! " if rate(r) < 1 else "~ ")
        print(f"{flag}{r['likes']:>6} {r['views']:>7,} {rate(r):>6.2f}%  "
              f"{r['published']:<11} {r['title'][:52]}")

    zero = [r for r in rated if r["likes"] == 0]
    if zero:
        print(f"\n  {len(zero)} of {len(rated)} have no likes at all.")
    if thin:
        print(f"  {len(thin)} more have under {MIN_VIEWS} views — too few to "
              f"read a rate from.")
    print("\n  ! under 1%   ~ 1-2%   (blank) 2%+ — a healthy Short is 2-5%.\n")


def run(mode: str = "full") -> int:
    rows = collect()
    if mode in ("likes", "likes-all"):
        likes(rows, include_long=(mode == "likes-all"))
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["video_id", "title", "published", "seconds",
                            "format", "views", "likes", "comments",
                            "privacy", "url"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: -r["views"]))
    report(rows)
    print(f"\nFull list, sorted by views: {OUT}")
    print("Open it in a spreadsheet before you hide or delete anything.\n")
    return 0


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--likes" in args:
        raise SystemExit(run("likes-all" if "--all" in args else "likes"))
    raise SystemExit(run())
