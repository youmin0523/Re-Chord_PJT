"""Measure AUX timbre-classifier accuracy via leave-one-out on the
reference DB.

The AUX reference DB (5,178 CLAP embeddings labelled by category) has
never been validated. We can measure its internal separability without
new data: for each embedding, find its k nearest neighbours among the
OTHERS (cosine), take the majority-vote category, and check it against
the true label. This is the same top-k vote the live classifier uses,
so the accuracy is directly representative.

Reports overall + per-category accuracy and a confusion summary, writes
data/qa/aux_accuracy_<date>.json.

Caveat: leave-one-out on the reference set measures how separable the
*reference timbres* are in CLAP space — an upper-ish bound. Real-song
audio (mixed, reverberant) will score lower. But if even this is poor,
the classifier is fundamentally unreliable.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reference_db" / "aux"


def main() -> int:
    emb = np.load(DB / "embeddings.npy").astype(np.float32)
    meta = json.loads((DB / "metadata.json").read_text(encoding="utf-8"))
    cats = meta["categories"]
    n = emb.shape[0]
    print(f"[info] {n} embeddings, dim={emb.shape[1]}, "
          f"{len(set(cats))} categories")

    # L2-normalise → cosine = dot product.
    norm = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    # Full cosine similarity matrix (5178² × 4B ≈ 107 MB — fine).
    sim = norm @ norm.T
    np.fill_diagonal(sim, -np.inf)        # exclude self

    K = 16   # matches live classifier top-k vote
    correct = 0
    per_cat_total: Counter = Counter()
    per_cat_correct: Counter = Counter()
    confusion: dict = defaultdict(Counter)

    for i in range(n):
        topk = np.argpartition(sim[i], -K)[-K:]
        votes = Counter(cats[j] for j in topk)
        pred = votes.most_common(1)[0][0]
        true = cats[i]
        per_cat_total[true] += 1
        if pred == true:
            correct += 1
            per_cat_correct[true] += 1
        else:
            confusion[true][pred] += 1

    overall = correct / n
    per_cat = {
        c: {
            "accuracy": round(per_cat_correct[c] / per_cat_total[c], 3),
            "n": per_cat_total[c],
            "top_confusion": dict(confusion[c].most_common(2)),
        }
        for c in sorted(per_cat_total)
    }

    report = {
        "date": dt.date.today().isoformat(),
        "method": f"leave-one-out, top-{K} cosine vote",
        "n_embeddings": n,
        "overall_accuracy": round(overall, 3),
        "per_category": per_cat,
        "note": "Reference-set self-consistency; real-song audio will be lower.",
    }
    out = ROOT / "data" / "qa" / f"aux_accuracy_{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== AUX classifier leave-one-out accuracy ===")
    print(f"OVERALL: {overall:.3f}")
    for c, d in sorted(per_cat.items(), key=lambda kv: kv[1]["accuracy"]):
        conf = ", ".join(f"{k}:{v}" for k, v in d["top_confusion"].items())
        print(f"  {c:14s} acc={d['accuracy']:.3f}  n={d['n']:4d}  "
              f"{'→ ' + conf if conf else ''}")
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
