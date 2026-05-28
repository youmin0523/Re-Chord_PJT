"""Pin the AUX under-populated-category confidence discount.

Leave-one-out measurement (2026-05-27) showed epiano/synth_lead/fx
classify poorly because the reference DB has too few exemplars. The
_top_k_vote now discounts confidence for under-populated categories so
the UI flags them and the cue-merge step drops the shakiest ones.
"""

from __future__ import annotations

import numpy as np

from backend.app.pipeline.aux_classifier import (
    ReferenceDB, _top_k_vote, _category_counts, MIN_RELIABLE_REFS,
)


def _make_db(category_counts: dict[str, int], dim: int = 8) -> ReferenceDB:
    """Build a toy reference DB where each category occupies a distinct
    orthogonal-ish direction so nearest-neighbour is deterministic."""
    rng = np.random.default_rng(0)
    embs, cats = [], []
    cat_dirs = {}
    for i, cat in enumerate(category_counts):
        d = np.zeros(dim, dtype=np.float32)
        d[i % dim] = 1.0
        cat_dirs[cat] = d
    for cat, n in category_counts.items():
        for _ in range(n):
            v = cat_dirs[cat] + 0.01 * rng.standard_normal(dim).astype(np.float32)
            v /= np.linalg.norm(v)
            embs.append(v); cats.append(cat)
    emb = np.stack(embs).astype(np.float32)
    return ReferenceDB(embeddings=emb, categories=cats,
                       sources=["t"] * len(cats), instruments=[""] * len(cats))


def test_category_counts():
    db = _make_db({"piano": 50, "fx": 5})
    counts = _category_counts(db)
    assert counts["piano"] == 50
    assert counts["fx"] == 5


def test_well_populated_category_keeps_confidence():
    db = _make_db({"piano": 50, "organ": 50})
    # Query right on the piano direction.
    q = db.embeddings[0]
    cat, conf, _ = _top_k_vote(q, db, k=8)
    assert cat == "piano"
    assert conf > 0.5, f"well-populated category should keep confidence, got {conf}"


def test_under_populated_category_confidence_discounted():
    # fx has only 5 refs (< MIN_RELIABLE_REFS) → confidence scaled down.
    db = _make_db({"piano": 50, "fx": 5})
    # Query on the fx direction (so fx wins the vote).
    fx_idx = db.categories.index("fx")
    q = db.embeddings[fx_idx]
    cat, conf, _ = _top_k_vote(q, db, k=4)
    assert cat == "fx"
    # 5/40 = 0.125 discount factor → confidence heavily reduced.
    expected_max = 5 / MIN_RELIABLE_REFS + 0.01
    assert conf <= expected_max, \
        f"under-populated fx confidence should be ≤{expected_max:.3f}, got {conf}"


def test_discount_scales_with_count():
    """A category with more refs (but still < threshold) keeps more
    confidence than a sparser one."""
    db = _make_db({"piano": 50, "fx": 5, "synth_lead": 30})
    fx_q = db.embeddings[db.categories.index("fx")]
    sl_q = db.embeddings[db.categories.index("synth_lead")]
    _, fx_conf, _ = _top_k_vote(fx_q, db, k=4)
    _, sl_conf, _ = _top_k_vote(sl_q, db, k=4)
    # synth_lead (30 refs) should retain more confidence than fx (5 refs).
    assert sl_conf > fx_conf
