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


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


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
    """The words in a phrase that actually carry its subject."""
    from .cars import _tokens, STOPWORDS          # late: avoids an import cycle
    return _tokens(text) - STOPWORDS


def _similarity(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    inter = a & b
    if not inter:
        return 0.0
    wi = sum(idf.get(w, 1.0) for w in inter)
    wa = sum(idf.get(w, 1.0) for w in a) or 1.0
    wb = sum(idf.get(w, 1.0) for w in b) or 1.0
    return wi / min(wa, wb)


def _idf(docs: list[set[str]]) -> dict[str, float]:
    import math
    df: dict[str, int] = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(docs))
    return {w: math.log(1 + n / (1 + c)) for w, c in df.items()}


def next_topics(n: int) -> list[sqlite3.Row]:
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
    """
    with conn() as c:
        cands = c.execute(
            "SELECT * FROM topics WHERE used_at IS NULL "
            "ORDER BY score DESC, demand DESC LIMIT 400").fetchall()
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
        if any(_similarity(subj, h, idf) >= SAME_TOPIC for h in hist_subj):
            continue
        if any(_similarity(subj, h, idf) >= TOO_SOON for h in recent):
            continue
        # And no two in the same batch, or three nights of insurance becomes
        # one night of three insurance videos.
        if any(_similarity(subj, q, idf) >= TOO_SOON for q in picked_subj):
            continue
        picked.append(r)
        picked_subj.append(subj)
    return picked


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
