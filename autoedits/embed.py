"""
Semantic similarity from your local Ollama, for topics and facts.

    ollama pull nomic-embed-text
    python -m autoedits.embed --compare      # does it beat what we already do?

WHY THIS IS NOT A VECTOR DATABASE
---------------------------------
Milvus is excellent and it is the wrong tool here. It is built to search
millions of vectors; this channel has a few hundred video titles, a few
hundred queued topics and 109 fact rows. Exact cosine similarity over 500
vectors is one numpy matrix multiply — roughly a third of a millisecond, no
index, no approximation, no wrong answers.

What Milvus would add on top of that is: an etcd container, a MinIO
container, a Milvus container, about two gigabytes of RAM, and one more
service that can be down at 3am when the cron fires. The nightly run already
depends on Ollama being up. Adding a second daemon to save a third of a
millisecond is a worse trade, not a better one.

The useful half of the idea is the EMBEDDINGS, not the store. Word overlap
cannot see that "what happens if my car is written off" and "total loss
threshold" are the same question — they share no words. An embedding can.
So: embeddings from Ollama, cached in a .npz file, searched with numpy.

Revisit this if the corpus ever passes ~100k vectors. It will not get there
from UAE car facts.
"""

from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import requests

from .config import ROOT, OLLAMA_HOST

MODEL = "nomic-embed-text"
CACHE = ROOT / "data" / "embeddings.npz"
_MEM: dict[str, np.ndarray] = {}


def _key(text: str) -> str:
    return hashlib.sha1(f"{MODEL}:{text.strip().lower()}".encode()).hexdigest()


def _load_cache() -> None:
    if _MEM or not CACHE.exists():
        return
    with np.load(CACHE) as z:
        _MEM.update({k: z[k] for k in z.files})


def _save_cache() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, **_MEM)



def _fetch(text: str) -> np.ndarray:
    """One embedding, from whichever endpoint this Ollama actually has.

    Ollama moved embeddings from /api/embeddings {"prompt": ...} -> {"embedding": [...]}
    to /api/embed {"input": ...} -> {"embeddings": [[...]]}. Both are in the
    wild depending on when you installed it, and the old one 404s on new
    builds. Try the new shape first, fall back, and say something useful if
    the model simply is not pulled.
    """
    last = None
    for path, payload, pick in (
        ("/api/embed", {"model": MODEL, "input": text},
         lambda d: d["embeddings"][0]),
        ("/api/embeddings", {"model": MODEL, "prompt": text},
         lambda d: d["embedding"]),
    ):
        try:
            r = requests.post(f"{OLLAMA_HOST}{path}", timeout=120, json=payload)
            if r.status_code == 404:
                last = f"{path} -> 404"
                continue
            r.raise_for_status()
            return np.asarray(pick(r.json()), dtype=np.float32)
        except (KeyError, IndexError, TypeError) as exc:
            last = f"{path} -> unexpected response ({exc})"
        except requests.RequestException as exc:
            last = f"{path} -> {str(exc)[:80]}"
    raise RuntimeError(
        f"Could not get an embedding from Ollama at {OLLAMA_HOST} ({last}). "
        f"Is it running, and have you run:  ollama pull {MODEL}")


def embed(texts: list[str], quiet: bool = False) -> np.ndarray:
    """Unit-length embeddings, one row per text. Cached across runs.

    Embedding is the slow part and the text rarely changes, so a title
    embedded once stays embedded. Delete data/embeddings.npz to rebuild.
    """
    _load_cache()
    missing = [t for t in texts if _key(t) not in _MEM]
    for i, t in enumerate(missing):
        if not quiet:
            print(f"\r  embedding {i + 1}/{len(missing)}", end="", flush=True)
        v = _fetch(t)
        _MEM[_key(t)] = v / (np.linalg.norm(v) or 1.0)
    if missing:
        _save_cache()
        if not quiet:
            print()
    return np.vstack([_MEM[_key(t)] for t in texts])


def most_similar(query: str, corpus: list[str], top: int = 5):
    """Cosine similarity against the whole corpus. No index, no approximation."""
    if not corpus:
        return []
    M = embed(corpus, quiet=True)
    q = embed([query], quiet=True)[0]
    scores = M @ q                      # unit vectors, so this IS cosine
    order = np.argsort(-scores)[:top]
    return [(corpus[i], float(scores[i])) for i in order]


def compare() -> int:
    """Put the embedding dedup next to the one already shipping.

    The point is not that embeddings are cleverer. It is whether they change
    any decision on THIS channel's titles. If they agree everywhere, the
    extra dependency buys nothing and should not be added.
    """
    from . import db

    with db.conn() as c:
        titles = [r["title"] for r in c.execute(
            "SELECT title FROM videos ORDER BY id DESC LIMIT 60").fetchall()]
    titles = [t for t in titles if t]
    if len(titles) < 4:
        print("Not enough videos in the database to compare.")
        return 1

    print(f"Comparing {len(titles)} titles, both ways.\n")
    subj = [db._subject(t) for t in titles]
    idf = db._idf(subj)
    M = embed(titles)

    rows = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            w = db._similarity(subj[i], subj[j], idf)
            e = float(M[i] @ M[j])
            rows.append((w, e, titles[i], titles[j]))

    # Where they disagree is the only interesting part.
    dis = [r for r in rows if (r[0] >= db.TOO_SOON) != (r[1] >= 0.80)]
    print(f"{len(rows)} pairs, {len(dis)} where the two methods disagree\n")
    print(f"  {'words':>6} {'embed':>6}  pair")
    for w, e, a, b in sorted(dis, key=lambda r: -abs(r[0] - r[1]))[:15]:
        flag = "embed only" if e >= 0.80 else "words only"
        print(f"  {w:>6.2f} {e:>6.2f}  [{flag}] {a[:30]} | {b[:30]}")

    print("\nRead it this way. 'embed only' pairs are duplicates the shipping")
    print("dedup MISSES — same question, different words. If there are none,")
    print("word overlap is already doing the job and this stays unused.\n")
    return 0


if __name__ == "__main__":
    if "--compare" in sys.argv:
        raise SystemExit(compare())
    q = " ".join(a for a in sys.argv[1:] if not a.startswith("--"))
    if not q:
        print(__doc__)
        raise SystemExit(1)
    from . import cars
    corpus = [f"{r['category']}: {r['item']}" for r in cars.load_facts()]
    for text, score in most_similar(q, corpus):
        print(f"  {score:.3f}  {text}")
    raise SystemExit(0)
