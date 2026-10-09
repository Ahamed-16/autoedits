"""
Why Studio and the review app disagree about views.

    python -m autoedits.reconcile          # videos published in the last 7 days
    python -m autoedits.reconcile 30

The review app's Performance tab shows `statistics.viewCount` from the **Data
API**. Studio's Shorts tab shows the **Analytics** view count. These are two
different counters maintained by two different services, and on a Short they
routinely disagree — most severely in the first 48 hours, which is exactly
when you look.

Three things can produce a gap, and they need different responses:

  lag          The Data API's viewCount is cached and refreshes on its own
               schedule. Studio is near-live. This closes by itself.
  definition   Since 2023 a Shorts "view" is any playback start. `views` and
               `engagedViews` in the Analytics API are both reported here so
               you can see which one Studio is echoing.
  window       Analytics is only complete to *yesterday*. A video published
               today may legitimately have no analytics row at all.

This prints every counter next to every other one and says which of those
three is responsible, instead of leaving you to guess from two screenshots.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import db
from .publish import credentials, service


def _data_api(ids: list[str]) -> dict[str, dict]:
    """statistics.viewCount — the number the review app currently trusts."""
    yt, out = service(), {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="statistics",
                                id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {"views": int(s.get("viewCount", 0)),
                             "likes": int(s.get("likeCount", 0))}
    return out


def _analytics(ids: list[str], metric: str, start: str,
               end: str) -> dict[str, int]:
    """One Analytics metric per video id, or {} if the metric is unsupported."""
    if not ids:
        return {}
    cli = build("youtubeAnalytics", "v2", credentials=credentials())
    try:
        resp = cli.reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics=metric, dimensions="video",
            filters="video==" + ",".join(ids[:200]),
            maxResults=200).execute()
    except HttpError as exc:
        # engagedViews is not enabled on every channel. Absence is an answer,
        # not a crash — report it and carry on with the metrics that do work.
        print(f"  ({metric} unavailable: {str(exc)[:90]})")
        return {}
    cols = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = [dict(zip(cols, r)) for r in resp.get("rows", [])]
    return {r["video"]: int(r.get(metric, 0)) for r in rows}


def run(days: int = 7) -> int:
    pub = [r for r in db.performance() if r["youtube_id"]]
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = [r for r in pub if (r["published_at"] or "")[:10] >= cutoff]
    if not rows:
        print(f"Nothing published through the pipeline in the last {days} days.")
        return 0

    ids = [r["youtube_id"] for r in rows]
    today = date.today()
    a_start = (today - timedelta(days=days + 1)).isoformat()

    print(f"\nReconciling {len(ids)} video(s) published since {cutoff}\n")

    data = _data_api(ids)
    # Two windows on purpose. Analytics is only *complete* to yesterday, but
    # asking through today shows whether partial same-day data exists at all —
    # which is how you tell "lagging" apart from "genuinely not counted yet".
    ana_y = _analytics(ids, "views", a_start,
                       (today - timedelta(days=1)).isoformat())
    ana_t = _analytics(ids, "views", a_start, today.isoformat())
    eng = _analytics(ids, "engagedViews", a_start, today.isoformat())

    print(f"  {'dataAPI':>8} {'ana→ytd':>8} {'ana→tdy':>8} {'engaged':>8}   title")
    for r in rows:
        vid = r["youtube_id"]
        d = data.get(vid, {}).get("views", 0)
        y, t = ana_y.get(vid, 0), ana_t.get(vid, 0)
        e = eng.get(vid)
        print(f"  {d:>8,} {y:>8,} {t:>8,} "
              f"{(f'{e:,}' if e is not None else '—'):>8}   "
              f"{(r['title'] or '')[:44]}")

    print("\nReading it:")
    print("  dataAPI far below ana→tdy .... Data API cache lag. It catches up;")
    print("                                 the app is showing a stale number.")
    print("  ana→tdy far above ana→ytd .... today's views are real but the")
    print("                                 28-day report deliberately drops them.")
    print("  engaged far below views ...... Studio is showing the loose count")
    print("                                 (any playback start), not engaged.")
    print("  all four close together ...... no discrepancy left to explain.\n")
    return 0


if __name__ == "__main__":
    n = next((int(a) for a in sys.argv[1:] if a.isdigit()), 7)
    raise SystemExit(run(n))
