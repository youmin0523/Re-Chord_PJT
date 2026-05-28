"""Job model + in-memory registry.

Phase A: simple in-process dict. Phase B will swap to PostgreSQL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from .paths import new_job_id


JobStatus = Literal["queued", "running", "done", "error", "cancelled"]
JobMode = Literal["quick_mr", "karaoke", "stems", "pro"]


@dataclass
class JobOptions:
    """User-facing settings for a job (mirrors UI controls)."""
    mode: JobMode = "quick_mr"
    # separation
    models: list[str] = field(default_factory=lambda: [
        "mdx23c_instvoc_hq", "bs_roformer_1297", "htdemucs_ft", "melband_kim_inst_v2",
    ])
    ensemble_method: Literal["min", "mag_avg", "mean"] = "min"
    mixback: bool = False
    inst_share: float = 0.5
    karaoke_postprocess: bool = True
    # transform (optional)
    semitones: float = 0.0
    tempo_ratio: float = 1.0
    source_bpm: float = 0.0
    target_bpm: float = 0.0
    # output
    format: Literal["wav", "flac", "aiff", "mp3", "aac"] = "wav"
    sample_rate: int = 48000
    bit_depth: Literal["16", "24", "32f"] = "24"
    # score (AI transcription)
    make_score: bool = False
    score_stems: list[str] = field(default_factory=lambda: ["vocals"])
    # voice cues + click track (practice / live)
    voice_cues: bool = False
    voice_cue_lang: Literal["ko", "en"] = "ko"
    click_track: bool = False
    monitor_track: bool = False        # mix instrumental + cues + click into one wav
    # Keep backing vocals (harmonies, choir) in the instrumental — only the
    # lead vocal is removed. Useful for choir/worship-team practice.
    keep_backing_vocals: bool = False
    detect_chords: bool = False
    # Polish: light mixback + dynaudnorm. On by default — fixes "compression/
    # ducking" feel of bare instrumental after vocal removal.
    polish: bool = True
    polish_inst_share: float = 0.20
    polish_reverb_tail: bool = False       # NEW: envelope-aware tail restore
    # Pro mode advanced ensemble + analysis controls.
    stereo_mode: Literal["lr", "mid_side"] = "lr"
    apply_diff_mask: bool = False
    diff_mask_strength: float = 0.6
    meter: str = "auto"               # "auto" or "2".."12"
    # Lyrics (faster-whisper). When make_score=True, attached under notes too.
    make_lyrics: bool = False
    lyrics_lang: str = "auto"              # "auto" | "ko" | "en" | "ja" | ...
    lyrics_domain: str = ""                # one of DOMAIN_PROMPTS keys, or free prompt
    lyrics_model: str = "turbo"            # tiny|base|small|medium|large-v3|turbo
    # Notation style for score generation. "" = auto from stem_kind.
    score_style: str = ""                  # "lead_sheet" | "grand_staff" | "drum" | "guitar_tab" | "bass_tab" | "choir_satb"
    # Optional per-stem override map: {"vocals": "lead_sheet", "guitar": "guitar_tab", ...}
    # Falls back to score_style or NOTATION_BY_STEM default when missing.
    score_styles_per_stem: dict[str, str] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    input: str                      # URL string or local file path
    options: JobOptions
    status: JobStatus = "queued"
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    # Remote URLs for each artifact when an off-box storage backend (S3/R2)
    # is configured. Empty in Phase A; populated by the orchestrator's
    # storage mirror step before the job transitions to "done".
    storage_urls: dict[str, str] = field(default_factory=dict)
    # Detected/derived metadata.
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict already handles JobOptions as dict; nothing else to convert.
        return d


class JobRegistry:
    """In-process job store with best-effort disk persistence.

    Phase A is single-process, so the source of truth is the in-memory
    dict. But a server restart used to wipe *all* job history — a beta
    tester who refreshed after a crash lost their finished MR + score.

    We now mirror each *terminal* job (done / error / cancelled) to a
    per-job JSON sidecar under ``<data>/jobs/<id>.json``. On boot we
    reload those sidecars so finished results survive a restart. Jobs
    that were mid-flight ('running'/'queued') when the process died are
    reloaded as 'error' with a clear message — their artifacts are gone
    but the user sees what happened instead of a silent disappearance.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._persist_dir = None  # set lazily to avoid import-time settings

    def _dir(self):
        if self._persist_dir is None:
            try:
                from ..config import settings
                from .paths import ensure_dir
                self._persist_dir = settings.data_dir / "jobs"
                ensure_dir(self._persist_dir)
            except Exception:
                self._persist_dir = None
        return self._persist_dir

    def create(self, input_str: str, options: JobOptions) -> Job:
        jid = new_job_id()
        job = Job(id=jid, input=input_str, options=options)
        self._jobs[jid] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        items = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return items[:limit]

    # ── persistence ────────────────────────────────────────────────
    def persist(self, job: Job) -> None:
        """Write a job's current state to its JSON sidecar. Best-effort —
        a persistence failure must never break the live pipeline."""
        d = self._dir()
        if d is None:
            return
        try:
            import json
            path = d / f"{job.id}.json"
            path.write_text(
                json.dumps(job.to_dict(), ensure_ascii=False, indent=2,
                           default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    def restore_from_disk(self) -> int:
        """Reload terminal jobs from sidecars at startup. Returns count
        restored. Mid-flight jobs (running/queued) are marked errored
        since their in-flight state is unrecoverable in Phase A."""
        d = self._dir()
        if d is None:
            return 0
        restored = 0
        try:
            import json
            for path in sorted(d.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                jid = raw.get("id")
                if not jid or jid in self._jobs:
                    continue
                opts_raw = raw.get("options") or {}
                try:
                    options = JobOptions(**{
                        k: v for k, v in opts_raw.items()
                        if k in JobOptions.__dataclass_fields__
                    })
                except Exception:
                    options = JobOptions()
                job = Job(
                    id=jid,
                    input=raw.get("input", ""),
                    options=options,
                    status=raw.get("status", "error"),
                    stage=raw.get("stage", ""),
                    progress=float(raw.get("progress", 0.0) or 0.0),
                    message=raw.get("message", ""),
                    created_at=float(raw.get("created_at", time.time())),
                    started_at=raw.get("started_at"),
                    finished_at=raw.get("finished_at"),
                    error=raw.get("error"),
                    artifacts=dict(raw.get("artifacts") or {}),
                    storage_urls=dict(raw.get("storage_urls") or {}),
                    meta=dict(raw.get("meta") or {}),
                )
                # A job stuck mid-flight when the process died can't be
                # resumed — surface it honestly.
                if job.status in ("running", "queued"):
                    job.status = "error"
                    job.error = (job.error
                                 or "서버 재시작으로 작업이 중단되었습니다. 다시 시도해주세요.")
                    job.message = job.error
                self._jobs[jid] = job
                restored += 1
        except Exception:
            pass
        return restored


registry = JobRegistry()
