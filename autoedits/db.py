"""SQLite store: topic queue, video drafts, published history, performance.

Deliberately boring and file-based — it survives reboots, you can open it in
any SQLite browser, and nothing depends on a service being up.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id           INTEGER PRIMARY KEY,
    query        TEXT UNIQUE NOT NULL,   -- the actual search phrase people type
    source       TEXT,                   -- autocomplete | manual | related
    demand       REAL DEFAULT 0,         -- suggestion rank, higher = more typed
    competition  REAL,                   -- 0-1, lower is better
    score        REAL DEFAULT 0,
    used_at      TEXT,                   -- set once a video ships for it
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY,
    topic_id     INTEGER REFERENCES topics(id),
    status       TEXT NOT NULL,          -- draft|approved|rejected|published|failed
    title        TEXT,
    description  TEXT,
    tags         TEXT,                   -- json list
    scenes       TEXT,                   -- json, the script as scene dicts
    video_path   TEXT,
    poster_path  TEXT,
    youtube_id   TEXT,
    note         TEXT,                   -- rejection reason / failure detail
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id           INTEGER PRIMARY KEY,
    video_id     INTEGER REFERENCES videos(id),
    checked_at   TEXT NOT NULL,
    views        INTEGER,
    likes        INTEGER,
    comments     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_topics_score  ON topics(score DESC);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS never
# alters an existing table, so they are added here when missing.
INSTAGRAM_COLUMNS = (("instagram_id", "TEXT"),
                     ("ig_status", "TEXT"),     # posted|failed|skipped|NULL
                     ("ig_note", "TEXT"))


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(videos)")}
        new = [(n, t) for n, t in INSTAGRAM_COLUMNS if n not in have]
        for name, kind in new:
            c.execute(f"ALTER TABLE videos ADD COLUMN {name} {kind}")
        if new:
            # The back catalogue stays off Instagram. Sixty videos landing on
            # a brand-new account in one evening reads as spam, and some of
            # them (#134) should not be reposted at all. One can still be sent
            # on purpose: python -m autoedits.instagram --post <id>
            c.execute("UPDATE videos SET ig_status='skipped', "
                      "ig_note='published before Instagram was set up' "
                      "WHERE status='published'")


# ------------------------------------------------------------------ topics --

def add_topic(query: str, source: str = "autocomplete", demand: float = 0.0,
              competition: float | None = None) -> None:
    score = demand * (1.0 - (competition or 0.5))
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO topics(query,source,demand,competition,score,"
            "created_at) VALUES (?,?,?,?,?,?)",
            (query.strip().lower(), source, demand, competition, score, now()))


def promote_topic(query: str, source: str, score: float) -> None:
    """Add a topic at an explicit score, raising it if it is already queued.

    `add_topic` derives score from autocomplete demand, and INSERT OR IGNORE
    means a phrase harvested last week keeps whatever rank it landed on. The
    evergreen list has to be able to outrank that — it is a deliberate content
    plan, not a demand signal — so it sets its own score and wins ties.
    """
    with conn() as c:
        c.execute(
            "INSERT INTO topics(query,source,demand,competition,score,created_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(query) DO UPDATE SET"
            "   score  = MAX(topics.score, excluded.score),"
            "   source = excluded.source",
            (query.strip().lower(), source, score, 0.0, score, now()))


# How close is too close. Both are IDF-weighted overlap between the subject
# words of two phrases, so sharing "insurance" counts for little and sharing
# "depreciation" counts for a lot.
SAME_TOPIC = 0.50        # against everything ever made: a straight repeat
TOO_SOON = 0.28          # against the last few: right subject, wrong week
COOLDOWN = 10            # how many recent videos the cooldown looks back over


def _subject(text: str) -> set[str]:
    """The words in a phrase that actually carry its subject.

    "motorcycle" is a stopword for retrieval — it is in nearly every bike
    rule and ranks nothing — but for dedupe it is the whole difference.
    Stripped, "motorcycle licence age in uae" became {licence, age} and was
    refused as a repeat of "How to Check Black Points on License in Dubai".
    So every motorcycle phrase carries one marker, however it was worded:
    "bike licence" and "motorbike licence" still match each other, and
    neither matches a car video.
    """
    from .cars import _tokens, STOPWORDS, is_bike_query   # late: import cycle
    subj = _tokens(text) - STOPWORDS
    return subj | {"motorcycle"} if is_bike_query(text) else subj


def _similarity(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """How much of the smaller subject the larger one already covers.

    Dividing by the SHORTER subject is deliberate: it catches a rephrasing.
    "black points uae" sits entirely inside "How to Check Black Points in
    UAE", scores 1.00, and is correctly refused as the same video twice.

    But when the shorter subject is a single word, containment is automatic
    and means nothing. "cheapest cars in uae" reduces to {cheapest} once the
    stopwords go, and scored a perfect 1.00 against "Toyota GR prices in UAE
    - which one is cheapest" purely because that title happens to contain the
    word. They are not the same video.

    That is not a rare edge: short generic phrases are most of what
    autocomplete harvests, and every video published adds more words that can
    swallow one. At 120 videos it blocked 305 of the top 400 queued topics,
    and the nightly run went two days building nothing while 1,186 topics
    with data sat behind the guard.

    So a one-word subject has to clear the LARGER bar instead — it can still
    block, but only against something nearly as short and as specific.

    A motorcycle subject and a car subject are never the same video, however
    many words they share. Containment made "Car insurance cost in UAE" sit
    wholly inside "motorcycle insurance cost in uae" and score 1.00.
    """
    if ("motorcycle" in a) != ("motorcycle" in b):
        return 0.0
    # The marker has done its job once it has picked the pool. Left in the
    # score it is a shared word between ANY two bike topics: 0.24 on its own
    # against a TOO_SOON of 0.28, so "motorcycle helmet fine" (0.34) and
    # "motorcycle insurance cost" (0.31) were refused as near-repeats of
    # "motorcycle licence age", and one bike video would have blocked most of
    # the bike queue for the next ten nights.
    a, b = a - {"motorcycle"}, b - {"motorcycle"}
    inter = a & b
    if not inter:
        return 0.0
    wi = sum(idf.get(w, 1.0) for w in inter)
    wa = sum(idf.get(w, 1.0) for w in a) or 1.0
    wb = sum(idf.get(w, 1.0) for w in b) or 1.0
    denom = min(wa, wb) if min(len(a), len(b)) >= 2 else max(wa, wb)
    return wi / denom


def _idf(docs: list[set[str]]) -> dict[str, float]:
    import math
    df: dict[str, int] = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(docs))
    return {w: math.log(1 + n / (1 + c)) for w, c in df.items()}


def next_topics(n: int, match=None) -> list[sqlite3.Row]:
    """Highest-scoring topics that are not a repeat of something already made.

    `used_at IS NULL` was the only guard, and it compares whole strings. But
    autocomplete harvests near-misses by design: "cheapest car insurance in
    dubai", "cheap car insurance uae" and "minimum car insurance price uae" are
    three distinct rows about one video. Six of the fifteen most-watched videos
    on this channel turned out to be insurance.

    So two guards now, both on subject words rather than whole strings:

      SAME_TOPIC   against every title ever made — a straight repeat
      TOO_SOON     against the last COOLDOWN videos — right subject, wrong week

    The second is what actually breaks the clustering. Insurance topics do not
    stop being made; they stop being made four nights running.

    `match`, when given, is a predicate on the query text that a topic must
    pass BEFORE the 400-row window is cut. The bike slot needs it: motorcycle
    topics are a few dozen rows in a queue of 1,500 car phrases, and would
    otherwise never reach the top 400 to be considered at all.
    """
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM topics WHERE used_at IS NULL "
            "ORDER BY score DESC, demand DESC").fetchall()
        cands = [r for r in rows if match is None or match(r["query"])][:400]
        history = [r["title"] for r in c.execute(
            "SELECT title FROM videos ORDER BY id DESC").fetchall()]

    if not cands:
        return []

    hist_subj = [_subject(t) for t in history]
    cand_subj = {r["id"]: _subject(r["query"]) for r in cands}
    idf = _idf(hist_subj + list(cand_subj.values()))
    recent = hist_subj[:COOLDOWN]

    picked: list[sqlite3.Row] = []
    picked_subj: list[set[str]] = []
    for r in cands:
        if len(picked) >= n:
            break
        subj = cand_subj[r["id"]]
        if not subj:
            continue
        # A topic you typed by hand skips all three guards. They exist to stop
        # autocomplete's near-misses becoming four insurance videos in a row,
        # which is a judgement the harvester cannot make and you already have.
        #
        # They were also wrong often enough to be unusable for hand-added
        # topics. _similarity divides by min(wa, wb), so a SHORT new phrase is
        # blocked by any longer title sharing most of its words:
        # "land cruiser fj uae price" scored 0.6 against "Land Cruiser GR
        # Sport price vs Prado and Hybrid in UAE" on {land, cruiser, price}
        # alone — and `fj`, the one word that makes it a different car, is
        # what got outvoted.
        #
        # An evergreen line is hand-written too, so it skips SAME_TOPIC — but
        # only that one. It keeps the ten-night cooldown and the batch guard.
        # The permanent guard was refusing lines that are plainly different
        # videos on one shared word: "motorcycle licence cost" scored 0.56
        # against "motorcycle licence age", and "motorcycle insurance cost"
        # 0.53 against "licence cost" on the word "cost". The protection it
        # gave — catching an evergreen line that repeats a past video — now
        # happens where you can see it: `topics --evergreen` warns at load.
        if r["source"] != "added":
            if r["source"] != "evergreen" and any(
                    _similarity(subj, h, idf) >= SAME_TOPIC for h in hist_subj):
                continue
            if any(_similarity(subj, h, idf) >= TOO_SOON for h in recent):
                continue
            # And no two in the same batch, or three nights of insurance
            # becomes one night of three insurance videos.
            if any(_similarity(subj, q, idf) >= TOO_SOON for q in picked_subj):
                continue
        picked.append(r)
        picked_subj.append(subj)
    return picked


def repeats_of(queries: list[str]) -> list[tuple[str, float, str]]:
    """(query, score, title) for each unused query that the permanent
    SAME_TOPIC guard would call a repeat of a video already made.

    Evergreen lines no longer stop at that guard, so this is how a line that
    genuinely duplicates a past video still gets caught: it is named when the
    list is loaded, and you decide.
    """
    with conn() as c:
        used = {r["query"] for r in c.execute(
            "SELECT query FROM topics WHERE used_at IS NOT NULL").fetchall()}
        history = [r["title"] for r in c.execute(
            "SELECT title FROM videos ORDER BY id DESC").fetchall()]
    todo = [q.strip().lower() for q in queries if q.strip().lower() not in used]
    hist_subj = [_subject(t) for t in history]
    idf = _idf(hist_subj + [_subject(q) for q in todo])
    out = []
    for q in todo:
        subj = _subject(q)
        if not subj:
            continue
        best = max(((_similarity(subj, hs, idf), t)
                    for hs, t in zip(hist_subj, history)), default=(0.0, ""))
        if best[0] >= SAME_TOPIC:
            out.append((q, best[0], best[1]))
    return out


def why_blocked(query: str) -> str | None:
    """None if next_topics() would consider this phrase, else the reason.

    Four things can stop a topic reaching a render, and until this existed
    only the first announced itself. The other three are quiet by design —
    they exist to stop the channel making the same video four nights running
    — so a phrase you add by hand and never see again looks identical to a
    phrase the queue simply has not reached yet.

    The guards are applied in the same order and at the same thresholds as
    next_topics(), from the same helpers, so this cannot drift away from the
    behaviour it describes.
    """
    q = query.strip().lower()
    with conn() as c:
        row = c.execute("SELECT used_at, source FROM topics WHERE query=?",
                        (q,)).fetchone()
        history = [r["title"] for r in c.execute(
            "SELECT title FROM videos ORDER BY id DESC").fetchall()]
        queued = [r["query"] for r in c.execute(
            "SELECT query FROM topics WHERE used_at IS NULL AND query<>? "
            "ORDER BY score DESC LIMIT 400", (q,)).fetchall()]

    if row is None:
        return "not in the queue at all — add it first"
    if row["used_at"]:
        return f"already used, on {row['used_at'][:10]}"

    subj = _subject(q)
    if not subj:
        return ("every word in it is a stopword, so it has no subject to "
                "match rows on")

    hist_subj = [_subject(t) for t in history]
    idf = _idf(hist_subj + [_subject(x) for x in queued] + [subj])

    # Mirrors the exemption in next_topics(): nothing blocks a topic you
    # asked for by name. near_misses() is what reports the overlap instead.
    if row["source"] == "added":
        return None

    # Mirrors next_topics(): an evergreen line skips the permanent guard and
    # keeps the cooldown. The repeat is reported when the list is loaded.
    for title, hs in zip(history, hist_subj):
        if row["source"] != "evergreen" and _similarity(subj, hs, idf) >= SAME_TOPIC:
            return f"too close to a video you already made: {title!r}"
    for title, hs in zip(history[:COOLDOWN], hist_subj[:COOLDOWN]):
        if _similarity(subj, hs, idf) >= TOO_SOON:
            return (f"same subject as a recent video, {title!r} — it clears "
                    f"the cooldown after {COOLDOWN} more drafts")
    return None


def near_misses(query: str, limit: int = 3) -> list[tuple[float, str]]:
    """Videos already made that share this phrase's subject, worst first.

    Advice rather than a verdict. A hand-added topic is built whatever this
    returns, so the point is to let you see the overlap before the render
    rather than after it.
    """
    subj = _subject(query)
    if not subj:
        return []
    with conn() as c:
        history = [r["title"] for r in c.execute(
            "SELECT title FROM videos ORDER BY id DESC").fetchall()]
    hist_subj = [_subject(t) for t in history]
    idf = _idf(hist_subj + [subj])
    scored = [(_similarity(subj, h, idf), t)
              for t, h in zip(history, hist_subj)]
    return sorted((s for s in scored if s[0] >= TOO_SOON), reverse=True)[:limit]


def mark_topic_used(topic_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE topics SET used_at=? WHERE id=?", (now(), topic_id))


# ------------------------------------------------------------------ videos --

def add_video(topic_id: int, title: str, description: str, tags: list[str],
              scenes: list[dict], video_path: str, poster_path: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO videos(topic_id,status,title,description,tags,scenes,"
            "video_path,poster_path,created_at) VALUES (?,'draft',?,?,?,?,?,?,?)",
            (topic_id, title, description, json.dumps(tags),
             json.dumps(scenes), video_path, poster_path, now()))
        return int(cur.lastrowid)


def supersede(video_path: str, note: str = "superseded by a rebuild") -> int:
    """Retire earlier, unpublished rows that point at a file we are rewriting.

    Rebuilding a Short overwrites the same .mp4, so a row left in the queue
    from the previous build now points at *different footage* than the one it
    was reviewed as. Leaving both is how you end up approving the version you
    checked and publishing the version you didn't.

    Published rows are never touched — those are history.
    """
    with conn() as c:
        cur = c.execute(
            "UPDATE videos SET status='rejected', note=?, decided_at=? "
            "WHERE video_path=? AND status IN ('draft','approved','failed')",
            (note, now(), video_path))
        return int(cur.rowcount)


def drafts() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM videos WHERE status='draft' ORDER BY created_at"
        ).fetchall()


def ig_pending() -> list[sqlite3.Row]:
    """Published to YouTube, not yet tried on Instagram."""
    with conn() as c:
        return c.execute(
            "SELECT * FROM videos WHERE status='published' AND ig_status IS NULL "
            "ORDER BY published_at").fetchall()


def mark_instagram(video_id: int, status: str, media_id: str | None = None,
                   note: str | None = None) -> None:
    with conn() as c:
        c.execute("UPDATE videos SET ig_status=?, instagram_id=?, ig_note=? "
                  "WHERE id=?", (status, media_id, note, video_id))


def approved() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM videos WHERE status='approved' ORDER BY decided_at"
        ).fetchall()


def get_video(video_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()


def set_status(video_id: int, status: str, note: str | None = None) -> None:
    with conn() as c:
        c.execute("UPDATE videos SET status=?, note=?, decided_at=? WHERE id=?",
                  (status, note, now(), video_id))


def update_meta(video_id: int, title: str, description: str) -> None:
    with conn() as c:
        c.execute("UPDATE videos SET title=?, description=? WHERE id=?",
                  (title, description, video_id))


def mark_published(video_id: int, youtube_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE videos SET status='published', youtube_id=?, "
                  "published_at=? WHERE id=?", (youtube_id, now(), video_id))


def record_metrics(video_id: int, views: int, likes: int, comments: int) -> None:
    with conn() as c:
        c.execute("INSERT INTO metrics(video_id,checked_at,views,likes,comments)"
                  " VALUES (?,?,?,?,?)", (video_id, now(), views, likes, comments))


def performance() -> list[sqlite3.Row]:
    """Latest metrics per published video — what the review screen shows you so
    you learn which hooks actually worked."""
    with conn() as c:
        return c.execute("""
            SELECT v.id, v.title, v.youtube_id, v.published_at,
                   m.views, m.likes, m.comments, m.checked_at,
                   ROUND(100.0 * m.likes / NULLIF(m.views,0), 2) AS like_rate
            FROM videos v
            LEFT JOIN metrics m ON m.id = (
                SELECT id FROM metrics WHERE video_id = v.id
                ORDER BY checked_at DESC LIMIT 1)
            WHERE v.status='published'
            ORDER BY v.published_at DESC
        """).fetchall()
