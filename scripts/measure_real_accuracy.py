"""Compare our pipeline output to user-curated ground truth.

Usage:
    1. Edit data/qa/ground_truth_template.json — fill in 5 songs.
    2. Make sure the backend is running on :7860.
    3. python scripts/measure_real_accuracy.py
       (re-uses cached job results when possible; otherwise POSTs new jobs)
    4. Open data/qa/real_accuracy_<date>.json for the per-song delta table.

Metrics:
    * key_correct       — exact (root + mode) match (semitone tolerance 0)
    * key_relative      — relative-major/minor counted as 50% credit
    * bpm_within_4pct   — MIREX standard tolerance
    * bpm_within_8pct   — looser (catches half/double-time confusion as miss)
    * chord_recall      — fraction of GT chords found anywhere in our output
                          (label-only, no timing — that's a richer metric we
                          can add once basic accuracy is established).

Each metric returns ``None`` if the GT field is null.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "data" / "qa" / "ground_truth_template.json"
OUTPUT = PROJECT_ROOT / "data" / "qa" / f"real_accuracy_{dt.date.today().isoformat()}.json"
BACKEND = "http://127.0.0.1:7860"


def _post_job(url: str) -> str | None:
    body = {
        "input": url,
        "options": {
            "mode": "stems",
            "models": ["htdemucs_6s"],
            "detect_chords": True,
            "make_score": False,
            "make_lyrics": False,
            "polish": True,
        },
    }
    req = urllib.request.Request(
        f"{BACKEND}/jobs", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["id"]


def _poll(job_id: str, max_minutes: int = 25) -> dict:
    deadline = time.time() + max_minutes * 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BACKEND}/jobs/{job_id}", timeout=10) as r:
                j = json.loads(r.read())
        except urllib.error.URLError:
            time.sleep(10); continue
        stage = j.get("stage") or "?"
        if stage == "done" or "FAILED" in (j.get("message") or ""):
            return j
        time.sleep(15)
    raise TimeoutError(f"job {job_id} did not finish in {max_minutes} min")


_NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def _parse_key(label: str | None) -> tuple[int, str] | None:
    if not label:
        return None
    parts = label.strip().split()
    if len(parts) < 2:
        return None
    pc = _NOTE_TO_PC.get(parts[0])
    if pc is None:
        return None
    mode = "minor" if "min" in parts[1].lower() else "major"
    return pc, mode


def _score_key(gt: str | None, pred: str | None) -> tuple[float | None, float | None]:
    """Returns (exact, relative-major/minor credit)."""
    g = _parse_key(gt); p = _parse_key(pred)
    if g is None or p is None:
        return None, None
    exact = 1.0 if g == p else 0.0
    # relative pair: C major <-> A minor (down a minor 3rd)
    if g != p:
        gpc, gmode = g; ppc, pmode = p
        if gmode != pmode:
            offset = (ppc - gpc) % 12
            if (gmode == "major" and offset == 9) or (gmode == "minor" and offset == 3):
                return exact, 0.5
    return exact, exact


def _bpm_score(gt: float | None, pred: float | None, tol: float):
    if gt is None or not pred:
        return None
    return 1.0 if abs(pred - float(gt)) <= float(gt) * tol else 0.0


_CHORD_NORM = re.compile(r"\s+")


def _norm_chord(c: str) -> str:
    return _CHORD_NORM.sub("", c).strip()


_PC_OF = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def _chord_to_pc_quality(c: str) -> tuple[int, str] | None:
    """Parse 'C#m', 'Ab', 'F#m7' into (pitch_class, simple_quality) tuples."""
    c = _norm_chord(c)
    if not c:
        return None
    root = c[:2] if len(c) > 1 and c[1] in "#b" else c[:1]
    pc = _PC_OF.get(root)
    if pc is None:
        return None
    tail = c[len(root):].lower()
    if tail.startswith("m") and not tail.startswith("maj"):
        quality = "min"
    elif tail.startswith("dim"):
        quality = "dim"
    elif tail.startswith("aug"):
        quality = "aug"
    else:
        quality = "maj"
    return pc, quality


def _shift_chords(chords: list[tuple[int, str]], semitones: int) -> set[tuple[int, str]]:
    return {((pc + semitones) % 12, q) for pc, q in chords}


def _chord_recall(gt_chords: list[str], pred_chords: list[str]) -> float | None:
    """Transposition-invariant chord recall.

    Most key-detection misses transpose the predicted progression by a
    consistent interval (a major third up, a tritone, etc.). Computing
    plain set-intersection in that case zeroes the recall even though the
    chord sequence itself is structurally correct. We instead try all 12
    semitone shifts of the GT and take the best match, so we measure
    "does the predicted output contain the song's chord pattern?"
    independent of the absolute key the detector landed on.
    """
    if not gt_chords:
        return None
    gt = [_chord_to_pc_quality(c) for c in gt_chords]
    gt = [t for t in gt if t is not None]
    if not gt:
        return None
    pred = [_chord_to_pc_quality(c) for c in pred_chords]
    pred = [t for t in pred if t is not None]
    if not pred:
        return 0.0
    pred_set = set(pred)
    gt_set = set(gt)
    best = 0.0
    for k in range(12):
        shifted = _shift_chords(list(gt_set), k)
        recall = len(shifted & pred_set) / len(shifted)
        if recall > best:
            best = recall
    return best


def main() -> int:
    if not TEMPLATE.exists():
        print(f"[fatal] template not found: {TEMPLATE}", file=sys.stderr)
        return 1
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    songs = template.get("songs", [])
    if not songs:
        print("[fatal] no songs in template", file=sys.stderr); return 1

    report = {"date": dt.date.today().isoformat(), "results": [], "summary": {}}

    for s in songs:
        sid = s.get("id", "?")
        gt = s.get("ground_truth", {})
        url = s.get("input_url", "")
        if not url or "PASTE_" in url:
            print(f"[skip] {sid}: input_url not filled in")
            report["results"].append({"id": sid, "skipped": True,
                                       "reason": "input_url empty"})
            continue
        print(f"\n=== {sid}: {s.get('title')} ===")
        try:
            job_id = _post_job(url)
            print(f"  posted job {job_id}; polling…")
            job = _poll(job_id, max_minutes=25)
        except Exception as e:
            print(f"  job failed: {e}")
            report["results"].append({"id": sid, "ok": False,
                                       "err": str(e)[:200]})
            continue

        meta = job.get("meta", {})
        pred_key = meta.get("key_name")
        pred_bpm = float(meta.get("bpm") or 0)

        pred_chords: list[str] = []
        cj = job.get("artifacts", {}).get("chords_json")
        if cj:
            try:
                cd = json.loads(Path(cj).read_text(encoding="utf-8"))
                pred_chords = [e.get("label", "") for e in cd.get("events", [])]
            except Exception:
                pred_chords = []

        key_exact, key_rel = _score_key(gt.get("key_name"), pred_key)
        bpm_4 = _bpm_score(gt.get("bpm"), pred_bpm, 0.04)
        bpm_8 = _bpm_score(gt.get("bpm"), pred_bpm, 0.08)
        ch_rec = _chord_recall(gt.get("chord_progression", []), pred_chords)

        row = {
            "id": sid,
            "title": s.get("title"),
            "predicted": {
                "key_name": pred_key, "bpm": round(pred_bpm, 2),
                "chord_label_count": len(pred_chords),
            },
            "ground_truth": {
                "key_name": gt.get("key_name"),
                "bpm": gt.get("bpm"),
                "chord_progression": gt.get("chord_progression"),
            },
            "metrics": {
                "key_exact": key_exact,
                "key_relative_credit": key_rel,
                "bpm_within_4pct": bpm_4,
                "bpm_within_8pct": bpm_8,
                "chord_recall": ch_rec,
            },
        }
        report["results"].append(row)
        print(f"  key {pred_key} vs {gt.get('key_name')} -> {key_exact}")
        print(f"  bpm {pred_bpm:.1f} vs {gt.get('bpm')} -> 4pct={bpm_4}")
        print(f"  chord recall = {ch_rec}")

    # Aggregate
    def _mean(metric: str) -> float | None:
        vals = [r["metrics"].get(metric) for r in report["results"]
                if "metrics" in r and r["metrics"].get(metric) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    report["summary"] = {
        "key_exact_mean": _mean("key_exact"),
        "key_relative_mean": _mean("key_relative_credit"),
        "bpm_4pct_mean": _mean("bpm_within_4pct"),
        "bpm_8pct_mean": _mean("bpm_within_8pct"),
        "chord_recall_mean": _mean("chord_recall"),
        "tracks_measured": sum(1 for r in report["results"] if "metrics" in r),
    }

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n[report] wrote {OUTPUT}")
    print(f"summary: {report['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
