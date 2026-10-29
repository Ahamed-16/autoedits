"""
The five minutes a day.

    streamlit run review_app.py

Watch the draft, check the sourced numbers, sharpen the hook if it's flat,
approve or bin it. Approving does not upload — `python -m autoedits.publish`
(or the morning cron) ships what you ticked.

The Performance tab is the part that compounds: it sorts your own published
hooks by like rate, so after a few weeks you are writing from evidence rather
than instinct.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from autoedits import db, publish, sources, theme as T

st.set_page_config(page_title="Auto Edits — review", page_icon="🎬",
                   layout="centered")
db.init()

st.title("Review queue")

def description_report(desc: str, scenes: list[dict]) -> list[tuple[bool, str]]:
    """Does this description follow the format, before it goes to YouTube?

    Descriptions are built from the scenes now, so they should always be
    right — but "should" is how the tread depth stayed wrong at 1.6mm for
    weeks. This is thirty seconds of checking against the three things the
    format exists to guarantee, shown where the approving happens.
    """
    d = (desc or "").strip()
    checks: list[tuple[bool, str]] = []

    verdict = next((sc.get("text", "").replace("*", "").strip()
                    for sc in scenes if sc.get("type") == "verdict"), "")
    if verdict:
        checks.append((d.startswith(verdict[:40]),
                       "Answers the question in the first line"))

    urls = [w for w in d.split() if w.startswith("http")]
    if urls:
        tiers = {sources.tier_of(u) for u in urls}
        official = tiers <= {"primary", "official"}
        checks.append((official,
                       f"Sources are official ({', '.join(sorted(tiers))})"))
    else:
        checks.append((False, "No source link in the description"))

    checks.append((d.endswith(T.END_CTA),
                   f"Ends with the ask — \u201c{T.END_CTA}\u201d"))
    return checks


tab_drafts, tab_ready, tab_perf = st.tabs(["Drafts", "Approved", "Performance"])


# ------------------------------------------------------------------ drafts --
with tab_drafts:
    rows = db.drafts()
    if not rows:
        st.info("Nothing waiting. Run `python -m autoedits.pipeline` to build "
                "tonight's batch.")

    for row in rows:
        with st.container(border=True):
            # A draft whose file has moved or been cleaned up must not take the
            # whole page down with it — st.video raises on a missing path, and
            # one stale row would then block every other draft from review.
            video = Path(row["video_path"] or "")
            if video.exists():
                st.video(str(video))
            else:
                st.warning(
                    f"Video file is missing — `{video}`. This draft probably "
                    "predates a folder move. Reject it below."
                )

            try:
                scenes = json.loads(row["scenes"] or "[]")
            except json.JSONDecodeError:
                scenes = []

            # Sourced claims — the actual reason a human is in this loop.
            claims = [(s.get("label") or s.get("title") or s["type"],
                       s.get("source", "— no source —"))
                      for s in scenes if s.get("type") in {"stat", "compare"}]
            if claims:
                st.markdown("**Check these before approving**")
                for label, src in claims:
                    ok = src and src != "— no source —"
                    st.markdown(f"{'✅' if ok else '⚠️'} *{label}* — {src}")

            # Captions on a photo short are claims too — a model name with
            # nothing behind it but recognition. A VENOM-badged 991 went out
            # of here labelled as a RUF, and the only thing that would have
            # caught it is reading the caption before approving.
            captions = [s["label"] for s in scenes
                        if s.get("type") in {"photo", "clip"} and s.get("label")]
            if captions:
                st.markdown("**Captions — check every car you name**")
                for cap in captions:
                    st.markdown(f"· {cap}")

            verdict = next((s["text"] for s in scenes
                            if s.get("type") == "verdict"), "")
            if verdict:
                st.caption(f"Verdict: {verdict}")

            title = st.text_input("Title", row["title"], key=f"t{row['id']}",
                                  max_chars=100)
            desc = st.text_area("Description", row["description"] or "",
                                key=f"d{row['id']}", height=260)

            # The description is what a search visitor reads before deciding
            # whether to stay. It gets the same scrutiny as the figures.
            report = description_report(desc, scenes)
            if report:
                st.markdown("**Description format**")
                for ok, label in report:
                    mark = "\u2705" if ok else "\u26a0\ufe0f"
                    st.markdown(f"{mark} {label}")

            c1, c2, c3 = st.columns([1, 1, 2])
            if c1.button("Approve", key=f"a{row['id']}", type="primary"):
                db.update_meta(row["id"], title, desc)
                db.set_status(row["id"], "approved")
                st.rerun()
            if c2.button("Reject", key=f"r{row['id']}"):
                db.set_status(row["id"], "rejected", "manual")
                st.rerun()
            c3.caption(f"draft #{row['id']} · {row['created_at'][:16]}")


# ---------------------------------------------------------------- approved --
with tab_ready:
    ready = db.approved()
    if not ready:
        st.info("Nothing approved. Approve a draft and it appears here.")

    st.write(f"**{len(ready)}** approved and waiting to upload.")

    # Approving used to be a one-way door: the only control here was Upload,
    # so a short approved before a rebuild sat in the queue with no way out
    # except publishing it. Both escape hatches now live next to the title.
    for row in ready:
        c1, c2, c3 = st.columns([5, 1.4, 1.2])
        c1.markdown(f"**{row['title']}**")
        c1.caption(f"#{row['id']} · {(row['decided_at'] or '')[:16]}")
        if c2.button("Send back", key=f"back{row['id']}",
                     help="Return this to Drafts without publishing"):
            db.set_status(row["id"], "draft")
            st.rerun()
        if c3.button("Discard", key=f"drop{row['id']}",
                     help="Take it out of the queue entirely"):
            db.set_status(row["id"], "rejected", "discarded from the queue")
            st.rerun()

    if ready:
        st.divider()
        st.caption("Upload publishes every approved video above, in one go.")
        if st.button("Upload now", type="primary"):
            with st.spinner("Uploading…"):
                done = publish.upload_approved()
            st.success(f"Published {len(done)} video(s).")
            st.rerun()


# ------------------------------------------------------------- performance --
with tab_perf:
    st.subheader("YouTube")
    if st.button("Refresh from YouTube"):
        with st.spinner("Fetching stats…"):
            st.success(f"Updated {publish.sync_metrics()} video(s).")

    perf = db.performance()
    if not perf:
        st.info("Nothing published through the pipeline yet.")
    else:
        st.dataframe(
            [{"Title": r["title"], "Views": r["views"], "Likes": r["likes"],
              "Comments": r["comments"], "Like %": r["like_rate"],
              "Checked": (r["checked_at"] or "")[:16].replace("T", " "),
              "Published": (r["published_at"] or "")[:10]} for r in perf],
            use_container_width=True, hide_index=True)
        st.caption(
            "Like rate is the number to watch. Your channel currently sits "
            "near 0.13%; a healthy Short is 2-5%. Sort by it, read the three "
            "best hooks, and write the next batch like those."
        )
        st.caption(
            ":grey[**Views here will not match YouTube Studio, and that is "
            "expected.** This column is `statistics.viewCount` from the Data "
            "API, which is cached and lags Studio badly for the first day or "
            "two of a Short's life. Studio reads the Analytics counter "
            "instead. The Checked column is when this row was last pulled — "
            "not now. To see every counter side by side and find out which "
            "one is off, run `python -m autoedits.reconcile`.]"
        )

    # ------------------------------------------------------ instagram --
    st.divider()
    st.subheader("Instagram")
    if st.button("Refresh from Instagram"):
        from autoedits import instagram
        with st.spinner("Fetching Instagram stats…"):
            try:
                res = instagram.sync_metrics()
            except instagram.InstagramError as exc:
                st.error(f"Instagram stats failed: {exc}")
            else:
                st.success(f"Updated {res['updated']} post(s).")
                if res["gone"]:
                    st.warning("No longer on Instagram: " +
                               ", ".join(f"#{i}" for i in res["gone"]))
                if res["no_insights"]:
                    st.warning(
                        "Only likes and comments were available. Views, reach, "
                        "saves, shares and watch time need the "
                        "instagram_business_manage_insights permission: add it "
                        "in the app dashboard, generate a new token and put it "
                        "in .env.")
                if res["stopped"]:
                    st.error(f"Stopped: {res['stopped']}")

    ig = db.ig_performance()
    if not ig:
        st.info("Nothing posted to Instagram yet.")
    else:
        st.dataframe(
            [{"#": r["id"], "Title": r["title"], "Views": r["views"],
              "Reach": r["reach"], "Likes": r["likes"],
              "Comments": r["comments"], "Saves": r["saved"],
              "Shares": r["shares"],
              "Avg watch (s)": (round(r["avg_watch_ms"] / 1000, 1)
                                if r["avg_watch_ms"] is not None else None),
              "Like %": r["like_rate"],
              "Checked": (r["checked_at"] or "")[:16].replace("T", " ")}
             for r in ig],
            use_container_width=True, hide_index=True)
        st.caption(
            "Blank means Instagram has not reported that number yet; a new "
            "Reel can take up to 48 hours. Saves and shares are the strongest "
            "signal on Instagram, and average watch time against the Reel's "
            "length tells you where people drop off.")
