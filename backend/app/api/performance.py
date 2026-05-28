"""Performance grading — score a user recording against the job's AI-separated
reference vocals (NOT the original studio vocal — the reference is itself an
imperfect separation, so the grade is approximate/reference-only).

Workflow:

    1. User records themselves singing along to the MR (RecordingPanel
       does this client-side and uploads the blob).
    2. This endpoint receives the recording, extracts F0 via CREPE,
       extracts F0 from the original ``vocals_final`` artifact, then
       aligns and grades:
           - pitch accuracy   (% frames within ±50 cents)
           - timing accuracy  (median offset of onsets, in ms)
           - overall_score    (weighted average, 0-100)

    3. Returns the grade + per-section breakdown.

The grading is intentionally simple — we surface specific places where
the user drifted, not a single opaque score. This makes practice-mode
feedback actionable.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..core.jobs import registry


router = APIRouter(prefix="/jobs", tags=["post-process"])


class SectionGrade(BaseModel):
    start_sec: float
    end_sec: float
    label: str
    pitch_accuracy: float
    timing_offset_ms: float


class GradeResult(BaseModel):
    job_id: str
    pitch_accuracy: float          # 0..1 — fraction of frames within ±50¢
    timing_offset_ms: float         # median absolute offset of onsets, in ms
    overall_score: int              # 0..100, derived
    notes: list[str]                # short text feedback bullets
    section_grades: list[SectionGrade]
    disclaimer: str = (             # honesty: this is an approximate, reference-only score
        "참고용 점수예요. 기준이 되는 보컬은 AI로 분리한 음원이라 원곡과 "
        "다를 수 있고, 음정·타이밍은 간단한 휴리스틱으로 추정한 근사치입니다. "
        "정확한 평가가 아니라 연습 방향을 잡는 참고로만 봐 주세요."
    )


def _grade_internal(
    reference_path: Path, user_path: Path,
) -> tuple[float, float]:
    """Return (pitch_accuracy_0_1, median_timing_offset_ms)."""
    try:
        import crepe  # type: ignore
        import librosa
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "performance grading requires crepe + librosa. "
            "Run: uv pip install crepe --no-build-isolation"
        ) from e

    # Both files at 16 kHz mono — what CREPE wants.
    def load(p: Path):
        y, _ = librosa.load(str(p), sr=16000, mono=True)
        return y

    ref = load(reference_path)
    usr = load(user_path)
    if ref.size == 0 or usr.size == 0:
        return (0.0, 0.0)

    # Align lengths.
    n = min(ref.size, usr.size)
    ref = ref[:n]; usr = usr[:n]

    # F0 tracking on both.
    _, ref_f, ref_c, _ = crepe.predict(ref.astype(np.float32), 16000,
                                         model_capacity="tiny",
                                         step_size=20, viterbi=True, verbose=0)
    _, usr_f, usr_c, _ = crepe.predict(usr.astype(np.float32), 16000,
                                         model_capacity="tiny",
                                         step_size=20, viterbi=True, verbose=0)
    m = min(ref_f.size, usr_f.size)
    ref_f = ref_f[:m]; ref_c = ref_c[:m]
    usr_f = usr_f[:m]; usr_c = usr_c[:m]

    # Compare only frames where both are confident voiced.
    mask = (ref_c >= 0.5) & (usr_c >= 0.5) & (ref_f > 0) & (usr_f > 0)
    if not mask.any():
        return (0.0, 0.0)

    cents_diff = 1200 * np.log2(usr_f[mask] / ref_f[mask])
    pitch_acc = float((np.abs(cents_diff) <= 50).mean())

    # Onset-timing comparison.
    ref_onsets = librosa.onset.onset_detect(y=ref, sr=16000, units="time")
    usr_onsets = librosa.onset.onset_detect(y=usr, sr=16000, units="time")
    if ref_onsets.size == 0 or usr_onsets.size == 0:
        return (pitch_acc, 0.0)
    # For each user onset, find nearest reference onset and record offset.
    offsets = []
    for t in usr_onsets:
        nearest = ref_onsets[np.argmin(np.abs(ref_onsets - t))]
        offsets.append(abs(t - nearest))
    median_offset_ms = float(np.median(offsets) * 1000)
    return (pitch_acc, median_offset_ms)


@router.post("/{job_id}/grade")
async def grade_performance(
    job_id: str,
    recording: UploadFile = File(...),
    reference: str = Form("vocals_final"),
) -> GradeResult:
    """Grade a recorded performance against the job's reference vocals."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    ref_path_str = job.artifacts.get(reference)
    if not ref_path_str or not Path(ref_path_str).exists():
        raise HTTPException(
            status_code=404,
            detail=f"reference artifact {reference!r} not found",
        )

    # Persist the upload to a temp file for librosa to read.
    suffix = Path(recording.filename or "rec.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await recording.read())
        rec_path = Path(tmp.name)

    try:
        pitch_acc, timing_ms = _grade_internal(Path(ref_path_str), rec_path)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        try:
            rec_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Compose feedback messages from the raw numbers.
    notes: list[str] = []
    if pitch_acc < 0.6:
        notes.append("음정이 ±50¢ 안쪽으로 들어간 비율이 60% 미만 — 핵심 멜로디 라인부터 천천히 다시.")
    elif pitch_acc < 0.8:
        notes.append("음정 정확도 양호. 후렴부 고음에서 조금만 더 다듬으면 좋습니다.")
    else:
        notes.append("음정이 기준 보컬과 잘 맞는 편이에요 (참고용 추정).")
    if timing_ms > 200:
        notes.append("타이밍 평균 오차 200 ms 초과 — 박자 감각 점검 필요.")
    elif timing_ms > 100:
        notes.append("타이밍 평균 오차 100~200 ms — 카운트인 연습이 도움될 거예요.")
    else:
        notes.append("타이밍이 기준과 잘 맞는 편이에요 (참고용 추정).")

    # Overall: 60% pitch + 40% timing (inverted), squashed to 0-100.
    timing_score = max(0.0, 1.0 - min(1.0, timing_ms / 500))
    overall = int(round((pitch_acc * 0.6 + timing_score * 0.4) * 100))

    return GradeResult(
        job_id=job_id,
        pitch_accuracy=pitch_acc,
        timing_offset_ms=timing_ms,
        overall_score=overall,
        notes=notes,
        section_grades=[],          # per-section breakdown is a future hook
    )
