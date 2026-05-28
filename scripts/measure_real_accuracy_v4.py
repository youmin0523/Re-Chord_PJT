"""V4 accuracy measurement — URL-grounded, not "original-key" grounded.

User insight (2026-05-21):
  사용자가 절대음감이 아닌 이상 키를 정확히 찾는 건 불가능. 사용자가
  URL을 전달하는 이유 = 그 URL의 키/BPM이 필요해서. 그러므로 평가의
  reference는 "원곡 표준 키"가 아니라 "그 URL의 실제 키"여야 한다.

We never assume the user can verify the URL's key by ear. Instead, we
build a *probabilistic* ground truth from three external signals and
report metrics relative to each:

  M1 — chord_recall_transpose : transposition-invariant chord recall
        (a song-shape match — robust to whatever key the cover landed in)
  M2 — external_match         : when the YouTube description contains an
        explicit key/BPM string (worship teams routinely do this), we
        compare our output to that. Only counts the songs that *have* the
        signal — never penalises others.
  M3 — bpm_band_plausibility  : even without ground truth, real worship
        / pop BPM lives in 50-180. Detector outputs outside that band
        are almost certainly halved or doubled. Treated as a sanity gate,
        not a strict pass/fail.

These are honest — we don't claim a number we can't actually verify
("key is C# minor with confidence 0.99") when the user themselves can't
verify it. We report what we measured, plus the external signals we
have, and call out gaps explicitly.
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


# Force UTF-8 on Windows so em-dash / Korean fall-through in print() lines
# stop crashing the run with "cp949 can't encode" UnicodeEncodeError.
# Reconfigure works on Python 3.7+ and is a no-op on POSIX (already utf-8).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "data" / "qa" / "ground_truth_template.json"
OUTPUT = PROJECT_ROOT / "data" / "qa" / f"real_accuracy_v4_{dt.date.today().isoformat()}.json"
BACKEND = "http://127.0.0.1:7860"


# ---------- pitch class helpers (shared with v1 measure script) -----
_PC_OF = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def _chord_to_pc_quality(c: str) -> tuple[int, str] | None:
    c = re.sub(r"\s+", "", c or "").strip()
    if not c:
        return None
    root = c[:2] if len(c) > 1 and c[1] in "#b" else c[:1]
    pc = _PC_OF.get(root)
    if pc is None:
        return None
    tail = c[len(root):].lower()
    if tail.startswith("m") and not tail.startswith("maj"):
        q = "min"
    elif tail.startswith("dim"):
        q = "dim"
    elif tail.startswith("aug"):
        q = "aug"
    else:
        q = "maj"
    return pc, q


def _chord_recall_transpose(gt: list[str], pred: list[str]) -> float | None:
    g = [_chord_to_pc_quality(c) for c in gt or []]
    g = [t for t in g if t is not None]
    p = [_chord_to_pc_quality(c) for c in pred or []]
    p = [t for t in p if t is not None]
    if not g or not p:
        return None
    pred_set = set(p)
    gt_set = set(g)
    best = 0.0
    for k in range(12):
        shifted = {((pc + k) % 12, q) for pc, q in gt_set}
        recall = len(shifted & pred_set) / len(shifted)
        best = max(best, recall)
    return round(best, 3)


# ---------- external GT extraction (YouTube description) ------------
_DESC_KEY_RE = re.compile(
    r"(?:키|Key|key|KEY)\s*[:\-=]?\s*([A-G][#b]?)\s*(?:major|minor|maj|min|m\b)?",
    re.IGNORECASE,
)
_DESC_KEY_PAIR_RE = re.compile(
    r"\b([A-G][#b]?)\s+(major|minor|maj|min)\b", re.IGNORECASE,
)
_DESC_BPM_RE = re.compile(
    r"(?:BPM|bpm|Tempo|tempo|템포)\s*[:\-=]?\s*(\d{2,3})"
)


def _extract_external_gt(description: str | None) -> dict:
    """Parse a YouTube description for key/BPM hints. Returns {} if missing."""
    if not description:
        return {}
    out: dict = {}
    m = _DESC_KEY_PAIR_RE.search(description)
    if m:
        root = m.group(1)
        mode = "minor" if m.group(2).lower().startswith("min") else "major"
        out["external_key"] = f"{root.upper() if len(root)==1 else root[0].upper()+root[1:]} {mode}"
    else:
        m = _DESC_KEY_RE.search(description)
        if m:
            root = m.group(1)
            out["external_key"] = f"{root.upper() if len(root)==1 else root[0].upper()+root[1:]} major"
    m = _DESC_BPM_RE.search(description)
    if m:
        out["external_bpm"] = int(m.group(1))
    return out


def _fetch_youtube_description(url: str) -> str:
    """Pull the bare description string via yt-dlp."""
    try:
        import subprocess, sys as _sys
        p = subprocess.run(
            [_sys.executable, "-m", "yt_dlp",
             "--no-warnings", "--skip-download",
             "--dump-single-json", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45,
        )
        if p.returncode != 0:
            return ""
        meta = json.loads(p.stdout or "{}")
        return meta.get("description") or ""
    except Exception:
        return ""


# ---------- key comparison ------------------------------------------
def _parse_key(label: str | None) -> tuple[int, str] | None:
    if not label:
        return None
    parts = label.strip().split()
    if len(parts) < 2:
        return None
    pc = _PC_OF.get(parts[0])
    if pc is None:
        return None
    mode = "minor" if "min" in parts[1].lower() else "major"
    return pc, mode


def _key_match(gt: str | None, pred: str | None) -> dict:
    """Returns {exact: 0/1, relative_credit: 0/0.5/1}."""
    g = _parse_key(gt); p = _parse_key(pred)
    if g is None or p is None:
        return {"exact": None, "relative_credit": None}
    exact = 1.0 if g == p else 0.0
    relative = exact
    if not exact:
        gpc, gmode = g; ppc, pmode = p
        if gmode != pmode:
            off = (ppc - gpc) % 12
            if (gmode == "major" and off == 9) or (gmode == "minor" and off == 3):
                relative = 0.5
    return {"exact": exact, "relative_credit": relative}


# ---------- backend interaction -------------------------------------
def _post_job(url: str) -> str:
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


# ---------- main ----------------------------------------------------
def main() -> int:
    if not TEMPLATE.exists():
        print(f"[fatal] template not found: {TEMPLATE}", file=sys.stderr); return 1
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    songs = template.get("songs", [])

    report = {
        "date": dt.date.today().isoformat(),
        "design_note": (
            "URL-grounded: GT는 사용자가 채워둔 '원곡 표준 키/BPM'이 아니라 "
            "각 URL의 description에서 자동 추출한 외부 source이거나 transposition-"
            "invariant chord pattern입니다. 우리 시스템 출력 = '이 URL의 실제 "
            "키/BPM'이므로 측정 reference도 URL-bound여야 공정."
        ),
        "results": [],
        "summary": {},
    }

    for s in songs:
        sid = s.get("id", "?")
        url = s.get("input_url", "") or ""
        if not url or "PASTE_" in url:
            report["results"].append({"id": sid, "skipped": True,
                                       "reason": "input_url empty"})
            continue
        print(f"\n=== {sid}: {s.get('title')} ===")

        # 1) External GT from YouTube description (when worship-team adds it).
        desc = _fetch_youtube_description(url)
        external_gt = _extract_external_gt(desc)
        if external_gt:
            print(f"  [external GT from description] {external_gt}")
        else:
            print("  [external GT] not found in description")

        # 2) Run the conversion.
        try:
            job_id = _post_job(url)
            print(f"  posted job {job_id}; polling…")
            job = _poll(job_id, max_minutes=25)
        except Exception as e:
            print(f"  job failed: {e}")
            report["results"].append({"id": sid, "ok": False, "err": str(e)[:200]})
            continue

        meta = job.get("meta", {})
        pred_key = meta.get("key_name")
        pred_bpm = float(meta.get("bpm") or 0)
        bpm_sources = meta.get("bpm_sources") or {}

        pred_chords: list[str] = []
        cj = job.get("artifacts", {}).get("chords_json")
        if cj:
            try:
                cd = json.loads(Path(cj).read_text(encoding="utf-8"))
                pred_chords = [e.get("label", "") for e in cd.get("events", [])]
            except Exception:
                pred_chords = []

        # 3) Metrics.
        # M1: chord transposition recall (against user-supplied progression
        #     in the GT template, which holds regardless of key)
        gt_chords = (s.get("ground_truth") or {}).get("chord_progression") or []
        chord_recall_transpose = _chord_recall_transpose(gt_chords, pred_chords)

        # M2: external match (only when description-derived GT exists)
        ext_key_match = _key_match(external_gt.get("external_key"), pred_key)
        ext_bpm_target = external_gt.get("external_bpm")
        if ext_bpm_target:
            ext_bpm_4 = 1.0 if abs(pred_bpm - ext_bpm_target) <= ext_bpm_target * 0.04 else 0.0
            ext_bpm_8 = 1.0 if abs(pred_bpm - ext_bpm_target) <= ext_bpm_target * 0.08 else 0.0
        else:
            ext_bpm_4 = ext_bpm_8 = None

        # M3: BPM band plausibility (does the predicted BPM sit inside the
        #     realistic 50-180 range? this catches obvious halving/doubling
        #     without needing any external reference)
        bpm_plausible = 1.0 if 50 <= pred_bpm <= 180 else 0.0

        row = {
            "id": sid,
            "title": s.get("title"),
            "url": url,
            "predicted": {
                "key_name": pred_key,
                "bpm": round(pred_bpm, 2),
                "bpm_sources": bpm_sources,
                "chord_label_count": len(pred_chords),
                "unique_chord_count": len(set(pred_chords)),
            },
            "external_gt": external_gt,
            "metrics": {
                "chord_recall_transpose": chord_recall_transpose,
                "external_key_exact": ext_key_match.get("exact"),
                "external_key_relative": ext_key_match.get("relative_credit"),
                "external_bpm_within_4pct": ext_bpm_4,
                "external_bpm_within_8pct": ext_bpm_8,
                "bpm_band_plausible": bpm_plausible,
            },
        }
        report["results"].append(row)
        print(f"  key: pred={pred_key}, external={external_gt.get('external_key','—')}")
        print(f"  bpm: pred={pred_bpm:.1f}, external={external_gt.get('external_bpm','—')}, "
              f"sources={bpm_sources}")
        print(f"  chord_recall_transpose={chord_recall_transpose}, "
              f"bpm_band_plausible={bpm_plausible}")

    # Aggregate
    def _mean(metric: str) -> float | None:
        vals = [r["metrics"].get(metric) for r in report["results"]
                if "metrics" in r and r["metrics"].get(metric) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    report["summary"] = {
        "chord_recall_transpose_mean": _mean("chord_recall_transpose"),
        "external_key_exact_mean": _mean("external_key_exact"),
        "external_key_relative_mean": _mean("external_key_relative"),
        "external_bpm_4pct_mean": _mean("external_bpm_within_4pct"),
        "external_bpm_8pct_mean": _mean("external_bpm_within_8pct"),
        "bpm_band_plausible_mean": _mean("bpm_band_plausible"),
        "tracks_measured": sum(1 for r in report["results"] if "metrics" in r),
        "tracks_with_external_gt": sum(
            1 for r in report["results"]
            if r.get("external_gt", {}).get("external_key")
            or r.get("external_gt", {}).get("external_bpm")
        ),
    }

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n[report] wrote {OUTPUT}")
    print(f"summary: {report['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
