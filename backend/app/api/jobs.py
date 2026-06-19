"""HTTP + WebSocket endpoints for jobs."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..auth import User, get_current_user, get_quota
from ..core.ratelimit import client_ip, jobs_global_daily, jobs_ip_limiter
from ..config import settings
from ..core.events import bus
from ..core.jobs import Job, JobMode, JobOptions, registry
from ..core.paths import ensure_dir
from ..core.queue import get_queue
from ..pipeline.loop import loop_segment
from ..pipeline.mixdown import mixdown_stems
from ..pipeline.transform import transform_audio
from fastapi import Depends


router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobOptionsIn(BaseModel):
    mode: JobMode = "quick_mr"
    models: list[str] | None = None
    ensemble_method: Literal["min", "mag_avg", "mean"] = "min"
    mixback: bool = False
    inst_share: float = Field(default=0.5, ge=0.0, le=1.0)
    karaoke_postprocess: bool = True
    semitones: float = Field(default=0.0, ge=-12.0, le=12.0)
    tempo_ratio: float = Field(default=1.0, ge=0.5, le=2.0)
    source_bpm: float = Field(default=0.0, ge=0.0, le=300.0)
    target_bpm: float = Field(default=0.0, ge=0.0, le=300.0)
    format: Literal["wav", "flac", "aiff", "mp3", "aac"] = "wav"
    sample_rate: int = 48000
    bit_depth: Literal["16", "24", "32f"] = "24"
    make_score: bool = False
    score_stems: list[str] | None = None
    voice_cues: bool = False
    voice_cue_lang: Literal["ko", "en"] = "ko"
    click_track: bool = False
    monitor_track: bool = False
    keep_backing_vocals: bool = False
    detect_chords: bool = False
    polish: bool = True
    polish_inst_share: float = Field(default=0.20, ge=0.0, le=0.6)
    polish_reverb_tail: bool = False
    stereo_mode: Literal["lr", "mid_side"] = "lr"
    apply_diff_mask: bool = False
    diff_mask_strength: float = Field(default=0.6, ge=0.0, le=1.0)
    meter: str = "auto"
    make_lyrics: bool = False
    lyrics_lang: str = "auto"
    lyrics_domain: str = ""
    lyrics_model: str = "turbo"
    score_style: str = ""
    score_styles_per_stem: dict[str, str] = Field(default_factory=dict)

    def to_options(self) -> JobOptions:
        defaults = JobOptions()
        return JobOptions(
            mode=self.mode,
            models=self.models if self.models is not None else defaults.models,
            ensemble_method=self.ensemble_method,
            mixback=self.mixback,
            inst_share=self.inst_share,
            karaoke_postprocess=self.karaoke_postprocess,
            semitones=self.semitones,
            tempo_ratio=self.tempo_ratio,
            source_bpm=self.source_bpm,
            target_bpm=self.target_bpm,
            format=self.format,
            sample_rate=self.sample_rate,
            bit_depth=self.bit_depth,
            make_score=self.make_score,
            score_stems=self.score_stems if self.score_stems is not None
                        else defaults.score_stems,
            voice_cues=self.voice_cues,
            voice_cue_lang=self.voice_cue_lang,
            click_track=self.click_track,
            monitor_track=self.monitor_track,
            keep_backing_vocals=self.keep_backing_vocals,
            detect_chords=self.detect_chords,
            polish=self.polish,
            polish_inst_share=self.polish_inst_share,
            polish_reverb_tail=self.polish_reverb_tail,
            stereo_mode=self.stereo_mode,
            apply_diff_mask=self.apply_diff_mask,
            diff_mask_strength=self.diff_mask_strength,
            meter=self.meter,
            make_lyrics=self.make_lyrics,
            lyrics_lang=self.lyrics_lang,
            lyrics_domain=self.lyrics_domain,
            lyrics_model=self.lyrics_model,
            score_style=self.score_style,
            score_styles_per_stem=dict(self.score_styles_per_stem),
        )


class JobCreate(BaseModel):
    """Either a URL or a path to an already-uploaded file."""
    input: str
    options: JobOptionsIn = Field(default_factory=JobOptionsIn)


def _job_dict(job: Job) -> dict:
    return job.to_dict()


@router.post("")
async def create_job(
    body: JobCreate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    # Abuse / single-GPU guard (public endpoint): per-IP/hour + global/day.
    ip = client_ip(request)
    ok_ip, retry_after = jobs_ip_limiter.allow(ip)
    if not ok_ip:
        raise HTTPException(
            status_code=429,
            detail="변환 요청이 너무 많아요. 잠시 후 다시 시도해주세요.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    ok_global, _ = jobs_global_daily.allow("global")
    if not ok_global:
        raise HTTPException(
            status_code=429,
            detail="오늘 전체 변환 한도에 도달했어요. 내일 다시 시도해주세요.",
        )

    # Quota gate (Phase A: unlimited; Phase B: tier-enforced).
    quota = get_quota(user)
    if body.options.mode not in quota.allowed_modes:
        raise HTTPException(
            status_code=403,
            detail=f"mode {body.options.mode!r} not allowed for tier {quota.tier}",
        )
    if (
        not quota.allow_premium_outputs
        and (body.options.format in ("flac", "aiff") and body.options.bit_depth == "32f")
    ):
        # 32-bit float is a Pro-tier output (huge files).
        raise HTTPException(
            status_code=403,
            detail=f"32-bit float output is Pro tier only (current: {quota.tier})",
        )
    job = registry.create(body.input, body.options.to_options())
    # Attach owner (Phase A: 'guest', Phase B: real user id).
    job.meta["owner_user_id"] = user.id
    try:
        get_queue().submit(job.id)
    except asyncio.QueueFull:
        # Backlog is at capacity — drop the just-created job and tell the
        # client to retry later instead of letting the queue grow unbounded.
        job.status = "error"
        job.error = "server busy: job queue full, please retry shortly"
        raise HTTPException(
            status_code=429,
            detail="서버가 혼잡합니다. 잠시 후 다시 시도해주세요. "
                   "(job queue at capacity)",
        )
    return _job_dict(job)


@router.get("")
async def list_jobs(limit: int = 50) -> list[dict]:
    return [_job_dict(j) for j in registry.list(limit=limit)]


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dict(job)


@router.delete("/{job_id}", status_code=200)
async def cancel_job(job_id: str) -> dict:
    """Cancel a queued or in-flight job. Idempotent."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    ok = get_queue().cancel(job_id)
    return {"job_id": job_id, "cancelled": ok, "status": job.status}


@router.get("/{job_id}/download/{kind}")
async def download_artifact(job_id: str, kind: str):
    """Stream a finished artifact (or redirect to its cloud-storage copy).

    `kind` is one of: instrumental, vocals, instrumental_final, vocals_final,
    stem_*, score_*, mixdown_*, … .

    When STORAGE_BACKEND is cloud (r2/s3), we 307-redirect to a fresh
    presigned/public URL so the download streams straight from R2 (free
    egress, works even if this host has cleaned its local copy and even when
    the host is briefly offline for the object itself). Falls back to the
    local file otherwise. A 410 means the artifact existed but its retention
    window (default 30 days) has passed — the client shows an "expired" notice.
    """
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    path = job.artifacts.get(kind)
    if not path:
        raise HTTPException(status_code=404, detail=f"artifact {kind!r} not available")

    # Cloud storage path: redirect to the R2/S3 object when it's there.
    backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    if backend not in ("", "local"):
        try:
            from ..storage.base import get_storage
            object_key = f"jobs/{job_id}/{kind}{Path(path).suffix}"
            storage = get_storage()
            if storage.exists(object_key):
                url = storage.get_url(object_key, signed=True, ttl_sec=3600)
                return RedirectResponse(url, status_code=307)
        except Exception:
            pass  # fall through to local serving

    p = Path(path)
    if not p.exists():
        # File was produced but has since been swept by data retention.
        raise HTTPException(
            status_code=410,
            detail="이 음원은 보존기간(기본 30일)이 지나 삭제되었습니다. 다시 변환해 주세요.",
        )
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


class MixdownRequest(BaseModel):
    """Which stem names to include in the on-demand mixdown.

    Available stem names (Stems mode): vocals, drums, bass, guitar, piano, other.

    ``eq_match`` controls tone-matching against the original mix:
      * ``True``  — restore EQ balance lost when stems are excluded (default)
      * ``False`` — raw sum, no spectral correction (fastest, may sound mid-scooped)
    ``eq_boost_cap_db`` caps per-bin correction magnitude. 6 dB is a safe
    default; raise to ~9 dB for aggressive restoration on extreme exclusions
    (e.g. drums-only or vocals-only mixdowns), lower to 3 dB if the result
    sounds over-corrected.
    """
    included_stems: list[str] = Field(..., min_length=1)
    target_sr: int = 48000
    eq_match: bool = True
    eq_boost_cap_db: float = Field(default=6.0, ge=0.0, le=12.0)


@router.post("/{job_id}/mixdown")
async def create_mixdown(job_id: str, body: MixdownRequest) -> dict:
    """Sum the chosen stems into a single track. Fast — no re-separation."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.options.mode != "stems":
        raise HTTPException(
            status_code=400,
            detail="mixdown only available for jobs created in 'stems' mode",
        )

    # Gather stem_<name> artifacts written by the orchestrator.
    stem_paths: dict[str, Path] = {}
    for key, p in job.artifacts.items():
        if not key.startswith("stem_"):
            continue
        name = key.removeprefix("stem_")
        stem_paths[name] = Path(p)
    if not stem_paths:
        raise HTTPException(
            status_code=400, detail="no stems available for this job",
        )

    unknown = [s for s in body.included_stems if s not in stem_paths]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown stems: {unknown}; available: {sorted(stem_paths)}",
        )

    tag = "+".join(sorted(body.included_stems))[:80]
    out_dir = settings.stems_dir / job_id / "mixdowns"
    ensure_dir(out_dir)
    out_path = out_dir / f"mixdown_{tag}.wav"

    # Hand the original ingested mix to the mixdown so it can tone-match the
    # excluded-stem result back to the source's spectral balance. This is the
    # fix for the "muddy / mid-scooped when I drop a stem" artefact.
    source_artifact = job.artifacts.get("source")
    reference_path = Path(source_artifact) if source_artifact and Path(source_artifact).exists() else None

    res = mixdown_stems(
        stem_paths=stem_paths,
        included=body.included_stems,
        out_path=out_path,
        target_sr=body.target_sr,
        reference_path=reference_path,
        eq_match=body.eq_match,
        eq_boost_cap_db=body.eq_boost_cap_db,
    )

    # Register the result as a downloadable artifact under a unique key so the
    # existing /download/{kind} route can serve it.
    artifact_key = f"mixdown_{tag}"
    job.artifacts[artifact_key] = str(res.out_path)

    return {
        "artifact": artifact_key,
        "out_path": str(res.out_path),
        "included_stems": res.included_stems,
        "excluded_stems": res.excluded_stems,
        "sample_rate": res.sample_rate,
        "duration_sec": res.duration_sec,
        "size_bytes": res.out_path.stat().st_size,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class BpmOverrideRequest(BaseModel):
    """Manually correct the detected BPM.

    Tempo octave (×2 / ÷2) is a genuine MIR ambiguity no single detector
    resolves reliably (see orchestrator's 5-source fusion). The UI shows
    ``meta.bpm_octave_candidates`` next to a click track so the user can
    confirm by ear — then calls this endpoint with either an explicit
    ``bpm`` or a relative ``octave_factor`` (0.5 = halve, 2.0 = double).
    The user's choice is sticky (``bpm_user_confirmed=True``) so nothing
    overwrites it later.
    """
    bpm: float | None = Field(default=None, gt=0, le=400)
    octave_factor: float | None = Field(default=None)
    regenerate_click: bool = True


@router.patch("/{job_id}/bpm")
async def override_bpm(job_id: str, body: BpmOverrideRequest) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    current = float(job.meta.get("bpm") or 0.0)
    if body.bpm is not None:
        new_bpm = float(body.bpm)
    elif body.octave_factor is not None:
        if body.octave_factor not in (0.5, 2.0):
            raise HTTPException(
                status_code=400,
                detail="octave_factor must be 0.5 or 2.0",
            )
        if current <= 0:
            raise HTTPException(
                status_code=400,
                detail="no detected BPM to scale; pass an explicit bpm",
            )
        new_bpm = current * body.octave_factor
    else:
        raise HTTPException(
            status_code=400, detail="provide either bpm or octave_factor",
        )

    job.meta["bpm"] = new_bpm
    job.meta["bpm_confidence"] = 1.0          # user-confirmed
    job.meta["bpm_user_confirmed"] = True

    # Regenerate the click track at the new tempo so the user can immediately
    # re-verify. We build a uniform beat grid from the corrected BPM (the
    # exact onset positions don't matter for a tempo-check click).
    click_url = None
    if body.regenerate_click:
        try:
            from ..pipeline.sections import BeatGrid
            from ..pipeline.click import generate_click_track
            meter = int(job.meta.get("meter") or 4)
            ts = str(job.meta.get("time_signature") or "4/4")
            duration = float(job.meta.get("source_duration") or 0.0)
            if duration > 0:
                beat_int = 60.0 / new_bpm
                n_beats = int(duration / beat_int)
                beats = [round(i * beat_int, 4) for i in range(n_beats)]
                downbeats = beats[::meter] if meter > 0 else beats
                bg = BeatGrid(
                    bpm=new_bpm, beats_sec=beats, downbeats_sec=downbeats,
                    meter=meter, time_signature=ts, is_compound=False,
                )
                out_dir = settings.output_dir / job_id / "click"
                ensure_dir(out_dir)
                out_path = out_dir / f"click_{int(round(new_bpm))}bpm.wav"
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: generate_click_track(bg, duration, out_path),
                )
                job.artifacts["click_track"] = str(out_path)
                click_url = f"/jobs/{job_id}/download/click_track"
        except Exception:
            click_url = None

    return {
        "bpm": new_bpm,
        "bpm_user_confirmed": True,
        "octave_candidates": job.meta.get("bpm_octave_candidates"),
        "click_download_url": click_url,
    }


class LoopRequest(BaseModel):
    """Build a looped (A-B repeat) wav from one of the job's audio artifacts.

    `source` picks which artifact to loop from. Common choices:
      "instrumental_final" (default) | "vocals_final" | "monitor_track"
      | any "stem_*" or "mixdown_*" key
    """
    source: str = "instrumental_final"
    start_sec: float = Field(..., ge=0.0)
    end_sec: float = Field(..., gt=0.0)
    repeats: int = Field(default=4, ge=1, le=64)
    with_countin: bool = True
    target_sr: int = 48000


@router.post("/{job_id}/loop")
async def create_loop(job_id: str, body: LoopRequest) -> dict:
    """Trim [start, end] from an artifact and repeat it N times into a new wav."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    src_path = job.artifacts.get(body.source)
    if not src_path:
        raise HTTPException(
            status_code=404,
            detail=f"artifact {body.source!r} not found on this job",
        )
    src = Path(src_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="source artifact missing on disk")

    if body.end_sec <= body.start_sec:
        raise HTTPException(status_code=400, detail="end_sec must exceed start_sec")

    bpm = float(job.meta.get("bpm", 0.0) or 0.0)
    out_dir = settings.output_dir / job_id / "loops"
    ensure_dir(out_dir)
    tag = (f"{body.source}_{body.start_sec:.2f}-{body.end_sec:.2f}"
           f"_x{body.repeats}").replace(":", "")
    out_path = out_dir / f"loop_{tag}.wav"

    loop = await _asyncio.get_running_loop().run_in_executor(
        None,
        lambda: loop_segment(
            input_path=src,
            out_path=out_path,
            start_sec=body.start_sec,
            end_sec=body.end_sec,
            repeats=body.repeats,
            target_sr=body.target_sr,
            with_countin=body.with_countin,
            bpm=bpm,
            meter=4,
        ),
    )

    artifact_key = f"loop_{tag}"
    job.artifacts[artifact_key] = str(loop.out_path)

    return {
        "artifact": artifact_key,
        "out_path": str(loop.out_path),
        "sample_rate": loop.sample_rate,
        "duration_sec": loop.duration_sec,
        "segment_sec": loop.segment_sec,
        "repeats": loop.repeats,
        "has_countin": loop.has_countin,
        "size_bytes": loop.out_path.stat().st_size,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class SlowdownRequest(BaseModel):
    """Render a pitch-preserving slow-down of one artifact (Tempo-app style).

    Common ratios:
      0.5  = half speed (practice difficult licks)
      0.75 = three-quarter speed
      1.0  = original (no-op)
    """
    source: str = "instrumental_final"
    tempo_ratio: float = Field(..., ge=0.25, le=2.0)
    stem_kind: Literal[
        "instrumental", "vocals", "drums", "bass", "harmonic", "mix", "generic"
    ] = "instrumental"


@router.post("/{job_id}/slowdown")
async def create_slowdown(job_id: str, body: SlowdownRequest) -> dict:
    """Render a pitch-preserving tempo-shifted wav (R3 finer engine if available)."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    src_path = job.artifacts.get(body.source)
    if not src_path:
        raise HTTPException(
            status_code=404,
            detail=f"artifact {body.source!r} not found on this job",
        )
    src = Path(src_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="source artifact missing on disk")

    if abs(body.tempo_ratio - 1.0) < 1e-4:
        # No-op: just hand back the existing artifact.
        return {
            "artifact": body.source,
            "out_path": str(src),
            "tempo_ratio": 1.0,
            "noop": True,
            "download_url": f"/jobs/{job_id}/download/{body.source}",
        }

    out_dir = settings.stems_dir / job_id / "slow"
    ensure_dir(out_dir)
    tag = f"{body.source}_x{body.tempo_ratio:.3f}".replace(".", "p")
    out_path = out_dir / f"slow_{tag}.wav"

    res = await _asyncio.get_running_loop().run_in_executor(
        None,
        lambda: transform_audio(
            input_path=src,
            out_path=out_path,
            semitones=0.0,
            tempo_ratio=body.tempo_ratio,
            engine="auto",
            stem_kind=body.stem_kind,
        ),
    )
    artifact_key = f"slow_{tag}"
    job.artifacts[artifact_key] = str(res.out_path)
    return {
        "artifact": artifact_key,
        "out_path": str(res.out_path),
        "tempo_ratio": body.tempo_ratio,
        "engine": res.engine,
        "elapsed_sec": res.elapsed_sec,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class LyricsWordEdit(BaseModel):
    word: str
    start_sec: float
    end_sec: float
    confidence: float = 1.0
    verse: int = 1


class LyricsEditRequest(BaseModel):
    """Save user-edited lyrics, optionally regenerating the vocals score.

    ``translations`` is a free-form mapping verse_number → translated text
    (typically Korean ↔ English worship lyrics shown alongside the original
    on the chord chart). Not language-specific so any localisation works.
    """
    words: list[LyricsWordEdit]
    rebuild_score: bool = True
    translations: dict[str, str] | None = None


@router.get("/{job_id}/lyrics")
async def get_lyrics(job_id: str) -> dict:
    """Fetch the latest lyrics JSON for review/edit."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    p = job.artifacts.get("lyrics_json")
    if not p:
        return {"available": False}
    import json as _json
    data = _json.loads(Path(p).read_text(encoding="utf-8"))
    return {"available": True, **data}


@router.put("/{job_id}/lyrics")
async def put_lyrics(job_id: str, body: LyricsEditRequest) -> dict:
    """Persist edited lyrics. Optionally rebuild the vocals score with them."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    lyrics_path = job.artifacts.get("lyrics_json")
    if not lyrics_path:
        # No prior lyrics — create the file from scratch under the job dir.
        lyr_dir = settings.output_dir / job_id / "lyrics"
        ensure_dir(lyr_dir)
        lyrics_path = str(lyr_dir / "lyrics.json")
        job.artifacts["lyrics_json"] = lyrics_path

    from ..pipeline.lyrics import save_edited_lyrics
    save_edited_lyrics(
        [w.model_dump() for w in body.words],
        Path(lyrics_path),
        translations=body.translations,
    )

    rebuilt: dict = {}
    if body.rebuild_score:
        try:
            from ..pipeline.score import build_score
            midi_key = "score_vocals_midi"
            midi_path = job.artifacts.get(midi_key)
            if midi_path and Path(midi_path).exists():
                score_dir = settings.output_dir / job_id / "score"
                ensure_dir(score_dir)
                chord_events = None
                cp = job.artifacts.get("chords_json")
                if cp and Path(cp).exists():
                    import json as _json
                    cd = _json.loads(Path(cp).read_text(encoding="utf-8"))
                    chord_events = cd.get("events") or None
                bpm = float(job.meta.get("bpm") or 0.0)
                style = job.options.score_style or "lead_sheet"

                sc = await _asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: build_score(
                        Path(midi_path), score_dir,
                        "vocals",
                        f"vocals - {job_id}",
                        True, True,
                        chord_events,
                        bpm,
                        [w.model_dump() | {"verse": w.verse} for w in body.words],
                        style,
                    ),
                )
                # Refresh score artifacts under existing keys.
                # Remove old page svgs first to avoid stale entries.
                for k in list(job.artifacts.keys()):
                    if k.startswith("score_vocals_svg_p"):
                        del job.artifacts[k]
                for i, svg_p in enumerate(sc.svg_paths, start=1):
                    job.artifacts[f"score_vocals_svg_p{i}"] = str(svg_p)
                if sc.pdf_path:
                    job.artifacts["score_vocals_pdf"] = str(sc.pdf_path)
                job.artifacts["score_vocals_musicxml"] = str(sc.musicxml_path)
                job.meta["score_vocals_pages"] = sc.pages
                job.meta["score_vocals_measures"] = sc.measures
                rebuilt = {
                    "rebuilt": True,
                    "pages": sc.pages,
                    "measures": sc.measures,
                }
            else:
                rebuilt = {"rebuilt": False, "reason": "no vocals MIDI on this job"}
        except Exception as e:
            rebuilt = {"rebuilt": False, "reason": repr(e)}

    return {
        "saved": True,
        "lyrics_path": lyrics_path,
        "word_count": len(body.words),
        **rebuilt,
    }


class AuxCueIn(BaseModel):
    start_measure: int = Field(..., ge=1)
    end_measure: int = Field(..., ge=1)
    patch: str = "pad"
    note: str = ""


class AuxCuesRequest(BaseModel):
    cues: list[AuxCueIn]
    rebuild_score: bool = True


@router.get("/{job_id}/aux_cues")
async def get_aux_cues(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    p = job.artifacts.get("aux_cues_json")
    if not p:
        return {"available": False, "cues": []}
    import json as _json
    data = _json.loads(Path(p).read_text(encoding="utf-8"))
    return {"available": True, **data}


@router.put("/{job_id}/aux_cues")
async def put_aux_cues(job_id: str, body: AuxCuesRequest) -> dict:
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    from ..pipeline.aux_cues import write_aux_cues
    cue_dir = settings.output_dir / job_id / "aux_cues"
    ensure_dir(cue_dir)
    cue_path = cue_dir / "aux_cues.json"
    write_aux_cues([c.model_dump() for c in body.cues], cue_path)
    job.artifacts["aux_cues_json"] = str(cue_path)

    rebuilt: dict = {}
    if body.rebuild_score:
        try:
            from ..pipeline.score import build_score
            midi_path = job.artifacts.get("score_vocals_midi")
            if midi_path and Path(midi_path).exists():
                # Re-attach AUX cues to the vocals lead-sheet score.
                import json as _json
                score_dir = settings.output_dir / job_id / "score"
                ensure_dir(score_dir)
                chord_events = None
                cp = job.artifacts.get("chords_json")
                if cp and Path(cp).exists():
                    chord_events = _json.loads(
                        Path(cp).read_text(encoding="utf-8")
                    ).get("events") or None
                lyrics_words = None
                lp = job.artifacts.get("lyrics_json")
                if lp and Path(lp).exists():
                    lyrics_words = _json.loads(
                        Path(lp).read_text(encoding="utf-8")
                    ).get("words") or None
                bpm = float(job.meta.get("bpm") or 0.0)
                style = job.options.score_style or "lead_sheet"

                sc = await _asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: build_score(
                        Path(midi_path), score_dir,
                        "vocals",
                        f"vocals - {job_id}",
                        True, True,
                        chord_events,
                        bpm,
                        lyrics_words,
                        style,
                        [c.model_dump() for c in body.cues],
                    ),
                )
                for k in list(job.artifacts.keys()):
                    if k.startswith("score_vocals_svg_p"):
                        del job.artifacts[k]
                for i, svg_p in enumerate(sc.svg_paths, start=1):
                    job.artifacts[f"score_vocals_svg_p{i}"] = str(svg_p)
                if sc.pdf_path:
                    job.artifacts["score_vocals_pdf"] = str(sc.pdf_path)
                job.artifacts["score_vocals_musicxml"] = str(sc.musicxml_path)
                job.meta["score_vocals_pages"] = sc.pages
                rebuilt = {"rebuilt": True, "pages": sc.pages}
            else:
                rebuilt = {"rebuilt": False, "reason": "no vocals score yet"}
        except Exception as e:
            rebuilt = {"rebuilt": False, "reason": repr(e)}

    return {"saved": True, "count": len(body.cues), **rebuilt}


class AuxAutoRequest(BaseModel):
    """Run the AUX auto-suggester for this job.

    Operates on the polished instrumental track; uses the beat grid from
    ``sections.json`` (auto-runs section analysis if needed). Returns the
    candidate cues — the caller can ``PUT /jobs/{id}/aux_cues`` to commit.
    """
    measures_per_window: int = Field(default=1, ge=1, le=8)
    top_k: int = Field(default=16, ge=4, le=64)
    save: bool = True       # also write aux_cues.json + register artifact


@router.post("/{job_id}/aux_cues/auto")
async def auto_aux_cues(job_id: str, body: AuxAutoRequest | None = None) -> dict:
    """Predict per-measure AUX patches via CLAP + reference DB.

    Falls back to zero-shot CLAP-text matching if the reference DB hasn't
    been built. Always returns a draft set of cues; the user reviews and
    edits in AuxCuesEditor.
    """
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    body = body or AuxAutoRequest()

    audio_path = job.artifacts.get("instrumental_final") \
        or job.artifacts.get("instrumental")
    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(
            status_code=400,
            detail="no instrumental artifact yet — run the job first",
        )

    # Need a beat grid. Use sections.json if present, else run analyze_sections.
    sections_path = job.artifacts.get("sections_json")
    downbeats: list[float] = []
    duration_sec: float = float(job.meta.get("source_duration") or 0.0)
    if sections_path and Path(sections_path).exists():
        import json as _json
        sec_data = _json.loads(Path(sections_path).read_text(encoding="utf-8"))
        downbeats = list(sec_data.get("downbeats_sec") or [])
        if not duration_sec:
            beats = sec_data.get("beats_sec") or []
            duration_sec = float(beats[-1]) if beats else 0.0
    if not downbeats:
        from ..pipeline.sections import analyze_sections
        sec_res = await _asyncio.get_running_loop().run_in_executor(
            None, lambda: analyze_sections(Path(audio_path)),
        )
        downbeats = list(sec_res.beat_grid.downbeats_sec)
        duration_sec = float(
            sec_res.beat_grid.beats_sec[-1]
            if sec_res.beat_grid.beats_sec
            else duration_sec
        )

    if not downbeats:
        raise HTTPException(
            status_code=422,
            detail="could not detect downbeats; aux cue suggestion unavailable",
        )

    from ..pipeline.aux_classifier import classify_measures
    db_dir = settings.data_dir / "reference_db" / "aux"

    try:
        result = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: classify_measures(
                audio_path=Path(audio_path),
                downbeats_sec=downbeats,
                duration_sec=duration_sec,
                db_dir=db_dir if db_dir.exists() else None,
                measures_per_window=body.measures_per_window,
                top_k=body.top_k,
            ),
        )
    except RuntimeError as e:
        # CLAP / model not available — surface a clean 503 instead of 500.
        raise HTTPException(
            status_code=503,
            detail=f"AUX classifier unavailable: {e}",
        ) from e

    saved_path: str | None = None
    if body.save and result.cues:
        from ..pipeline.aux_cues import write_aux_cues
        cue_dir = settings.output_dir / job_id / "aux_cues"
        ensure_dir(cue_dir)
        cue_path = cue_dir / "aux_cues.json"
        write_aux_cues(result.cues, cue_path)
        job.artifacts["aux_cues_json"] = str(cue_path)
        saved_path = str(cue_path)

    return {
        "mode": result.mode,
        "db_size": result.db_size,
        "cue_count": len(result.cues),
        "cues": result.cues,
        "candidates": [
            {
                "measure": c.measure,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "patch": c.patch,
                "confidence": c.confidence,
                "runner_up": c.runner_up,
            }
            for c in result.candidates
        ],
        "saved": bool(saved_path),
        "saved_path": saved_path,
    }


class BinauralRequest(BaseModel):
    """Render an HRTF binaural version of an artifact for headphone listening.

    Uses ffmpeg's ``sofalizer`` (or fallback to ``surround``+``aresample``)
    to wrap the stereo source into a head-related impulse response so the
    listener perceives stage width / depth on headphones. Useful when
    practicing with in-ears: the click + cues feel "in the room" rather
    than glued to the eardrum.
    """
    source: str = "instrumental_final"
    width: float = Field(default=1.0, ge=0.5, le=1.5)


@router.post("/{job_id}/binaural")
async def create_binaural(job_id: str, body: BinauralRequest) -> dict:
    """Produce a binaural-rendered wav from one of the job's artifacts."""
    import asyncio as _asyncio
    import shutil
    import subprocess
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    src_path = job.artifacts.get(body.source)
    if not src_path:
        raise HTTPException(status_code=404, detail=f"artifact {body.source!r} not found")
    src = Path(src_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="source artifact missing on disk")

    out_dir = settings.output_dir / job_id / "binaural"
    ensure_dir(out_dir)
    out_path = out_dir / f"binaural_{body.source}.wav"

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg not found on server")

    # ffmpeg's `surround` filter widens stereo with an HRTF-ish room sim.
    # `sofalizer` would be more accurate but requires a .sofa file on disk —
    # we fall back to a chain that is bundled by default in every ffmpeg build.
    af = (
        f"stereotools=mlev={body.width}:slev={1.05 * body.width},"
        "aphaser=in_gain=0.6:out_gain=0.8:delay=2.0:decay=0.35:speed=0.3,"
        "aresample=resampler=soxr:precision=28"
    )

    def run():
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-vn", "-map_metadata", "-1",
            "-af", af,
            "-c:a", "pcm_s24le", "-f", "wav",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    try:
        await _asyncio.get_running_loop().run_in_executor(None, run)
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"binaural render failed: {e.stderr.decode('utf-8', errors='ignore')[-500:]}",
        ) from e

    artifact_key = f"binaural_{body.source}"
    job.artifacts[artifact_key] = str(out_path)
    return {
        "artifact": artifact_key,
        "out_path": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class MasteringRequest(BaseModel):
    """LUFS-normalize an artifact for a specific platform target.

    Optional 3-band EQ tilt before normalisation. All gains in dB,
    positive boosts / negative cuts; 0 dB skips the band.
    """
    source: str = "instrumental_final"
    target_platform: Literal[
        "youtube", "spotify", "spotify_q", "apple", "tidal", "broadcast", "custom",
    ] = "spotify"
    custom_lufs: float = Field(default=-14.0, ge=-30.0, le=-6.0)
    low_db: float = Field(default=0.0, ge=-12.0, le=12.0)
    mid_db: float = Field(default=0.0, ge=-12.0, le=12.0)
    high_db: float = Field(default=0.0, ge=-12.0, le=12.0)


@router.post("/{job_id}/master")
async def master_artifact(job_id: str, body: MasteringRequest) -> dict:
    """Produce a LUFS-normalised (and optionally EQ'd) sibling artifact."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    src = job.artifacts.get(body.source)
    if not src or not Path(src).exists():
        raise HTTPException(status_code=404, detail=f"artifact {body.source!r} not found")

    out_dir = settings.output_dir / job_id / "master"
    ensure_dir(out_dir)
    src_path = Path(src)

    # Resolve target LUFS.
    from ..pipeline.mastering import (
        PLATFORM_TARGETS_LUFS, normalize_lufs, apply_3band_eq,
    )
    target_lufs = (
        body.custom_lufs if body.target_platform == "custom"
        else PLATFORM_TARGETS_LUFS.get(body.target_platform, -14.0)
    )

    def run() -> dict:
        cur = src_path
        # Optional EQ first.
        if any(abs(g) > 0.01 for g in (body.low_db, body.mid_db, body.high_db)):
            eq_path = out_dir / f"{src_path.stem}_eq.wav"
            apply_3band_eq(
                cur, eq_path,
                low_db=body.low_db, mid_db=body.mid_db, high_db=body.high_db,
            )
            cur = eq_path
        # Then LUFS normalise.
        final_path = out_dir / f"{src_path.stem}_{body.target_platform}_{int(target_lufs)}lufs.wav"
        res = normalize_lufs(cur, final_path, target_lufs=target_lufs)
        return {
            "out_path": str(res.out_path),
            "measured_lufs": res.measured_lufs,
            "target_lufs": res.target_lufs,
            "gain_db": res.gain_db,
        }

    result = await _asyncio.get_running_loop().run_in_executor(None, run)
    artifact_key = f"master_{body.target_platform}_{body.source}"
    job.artifacts[artifact_key] = result["out_path"]
    return {
        "artifact": artifact_key,
        **result,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class AutotuneRequest(BaseModel):
    """Subtle CREPE+WORLD pitch correction on a vocal artifact."""
    source: str = "vocals_final"
    key_root: str = "C"
    scale: Literal["major", "minor", "dorian", "mixo", "chromatic"] = "major"
    correction_strength: float = Field(default=0.65, ge=0.0, le=1.0)
    snap_window_cents: int = Field(default=50, ge=10, le=100)


@router.post("/{job_id}/autotune")
async def autotune_artifact(job_id: str, body: AutotuneRequest) -> dict:
    """Apply gentle vocal pitch correction. Requires crepe + pyworld."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    src = job.artifacts.get(body.source)
    if not src or not Path(src).exists():
        raise HTTPException(status_code=404, detail=f"artifact {body.source!r} not found")

    from ..pipeline.autotune import is_available, autotune_vocal
    if not is_available():
        raise HTTPException(
            status_code=503,
            detail="autotune backend unavailable (crepe + pyworld not installed)",
        )

    out_dir = settings.output_dir / job_id / "autotune"
    ensure_dir(out_dir)
    out_path = out_dir / f"{Path(src).stem}_autotuned.wav"

    def run():
        return autotune_vocal(
            Path(src), out_path,
            key_root=body.key_root, scale=body.scale,
            correction_strength=body.correction_strength,
            snap_window_cents=body.snap_window_cents,
        )

    res = await _asyncio.get_running_loop().run_in_executor(None, run)
    artifact_key = f"autotune_{body.source}"
    job.artifacts[artifact_key] = str(res.out_path)
    return {
        "artifact": artifact_key,
        "out_path": str(res.out_path),
        "sample_rate": res.sample_rate,
        "frames_corrected": res.frames_corrected,
        "elapsed_sec": res.elapsed_sec,
        "download_url": f"/jobs/{job_id}/download/{artifact_key}",
    }


class PedalToneRequest(BaseModel):
    """Generate a sustained pedal-tone pad in a given key. Worship-mode helper.

    Stored under the job so the user can drop it into their setlist as a
    standalone interlude track or use it as a modulation bridge.
    """
    key_root: str = Field(..., min_length=1, max_length=3)
    mode: Literal["major", "minor"] = "major"
    duration_sec: float = Field(default=16.0, ge=4.0, le=120.0)


@router.post("/{job_id}/pedal_tone")
async def create_pedal_tone(job_id: str, body: PedalToneRequest) -> dict:
    """Render a pedal-tone pad and register it as a sibling artifact."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    from ..pipeline.worship import synthesize_pedal_tone
    out_dir = settings.output_dir / job_id / "worship"
    ensure_dir(out_dir)
    out_path = out_dir / f"pedal_{body.key_root.replace('#','sharp')}_{body.mode}_{int(body.duration_sec)}s.wav"

    res = await _asyncio.get_running_loop().run_in_executor(
        None,
        lambda: synthesize_pedal_tone(
            out_path, body.key_root, body.mode,
            duration_sec=body.duration_sec,
        ),
    )
    key = f"pedal_{body.key_root}_{body.mode}_{int(body.duration_sec)}"
    job.artifacts[key] = str(res.out_path)
    return {
        "artifact": key,
        "out_path": str(res.out_path),
        "duration_sec": res.duration_sec,
        "key_root": res.key_root,
        "mode": res.mode,
        "download_url": f"/jobs/{job_id}/download/{key}",
    }


class SegueRequest(BaseModel):
    """Render a smooth segue between two jobs (this one → ``next_job_id``).

    Optional ``bridge_key`` inserts a pedal-tone in that key between the
    crossfades — useful for cross-key transitions in worship sets.
    """
    next_job_id: str
    bridge_key: str | None = None
    bridge_seconds: float = Field(default=8.0, ge=0.0, le=60.0)
    crossfade_seconds: float = Field(default=2.0, ge=0.5, le=8.0)
    source: str = "instrumental_final"


@router.post("/{job_id}/segue")
async def create_segue(job_id: str, body: SegueRequest) -> dict:
    """Splice ``job_id`` → bridge → ``next_job_id`` into a single wav."""
    import asyncio as _asyncio
    job_a = registry.get(job_id)
    job_b = registry.get(body.next_job_id)
    if job_a is None or job_b is None:
        raise HTTPException(status_code=404, detail="one or both jobs not found")
    src_a = job_a.artifacts.get(body.source)
    src_b = job_b.artifacts.get(body.source)
    if not (src_a and src_b and Path(src_a).exists() and Path(src_b).exists()):
        raise HTTPException(
            status_code=404,
            detail=f"artifact {body.source!r} missing on one or both jobs",
        )

    from ..pipeline.worship import build_segue
    out_dir = settings.output_dir / job_id / "worship"
    ensure_dir(out_dir)
    out_path = out_dir / f"segue_to_{body.next_job_id}.wav"

    res = await _asyncio.get_running_loop().run_in_executor(
        None,
        lambda: build_segue(
            Path(src_a), Path(src_b), out_path,
            bridge_key=body.bridge_key,
            bridge_seconds=body.bridge_seconds,
            crossfade_seconds=body.crossfade_seconds,
        ),
    )
    key = f"segue_to_{body.next_job_id}"
    job_a.artifacts[key] = str(res.out_path)
    return {
        "artifact": key,
        "out_path": str(res.out_path),
        "duration_sec": res.duration_sec,
        "crossfade_sec": res.crossfade_sec,
        "download_url": f"/jobs/{job_id}/download/{key}",
    }


class SurroundRequest(BaseModel):
    """Render the job's stems into a single 5.1 surround WAV. Stems mode only."""
    sample_rate: int = Field(default=48000, ge=44100, le=192000)


@router.post("/{job_id}/surround")
async def create_surround(job_id: str, body: SurroundRequest) -> dict:
    """5.1 surround mix from existing stems. Pro/Stems mode only."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    stems: dict[str, Path] = {}
    # Prefer the 6-stem result if Stems mode; otherwise compose from
    # whatever 2-stem artifacts we have.
    if job.options.mode == "stems":
        for k, v in job.artifacts.items():
            if k.startswith("stem_"):
                stems[k.removeprefix("stem_")] = Path(v)
    else:
        if job.artifacts.get("vocals_final"):
            stems["vocals"] = Path(job.artifacts["vocals_final"])
        if job.artifacts.get("instrumental_final"):
            stems["instrumental"] = Path(job.artifacts["instrumental_final"])
    if not stems:
        raise HTTPException(status_code=400, detail="no stems available for surround")

    from ..pipeline.spatial import render_5_1_surround
    out_dir = settings.output_dir / job_id / "surround"
    ensure_dir(out_dir)
    out_path = out_dir / "surround_5_1.wav"
    try:
        res = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: render_5_1_surround(stems, out_path, sample_rate=body.sample_rate),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    job.artifacts["surround_5_1"] = str(res.out_path)
    return {
        "artifact": "surround_5_1",
        "out_path": str(res.out_path),
        "channel_layout": res.channel_layout,
        "sample_rate": res.sample_rate,
        "download_url": f"/jobs/{job_id}/download/surround_5_1",
    }


class DsdRequest(BaseModel):
    source: str = "instrumental_final"
    rate: Literal["dsd64", "dsd128", "dsd256"] = "dsd64"


@router.post("/{job_id}/dsd")
async def create_dsd(job_id: str, body: DsdRequest) -> dict:
    """Encode a job artifact to DSD (.dsf). Audiophile / SACD format."""
    import asyncio as _asyncio
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    src = job.artifacts.get(body.source)
    if not src or not Path(src).exists():
        raise HTTPException(status_code=404, detail=f"artifact {body.source!r} not found")

    from ..pipeline.spatial import render_dsd
    out_dir = settings.output_dir / job_id / "dsd"
    ensure_dir(out_dir)
    out_path = out_dir / f"{Path(src).stem}.{body.rate}.dsf"
    try:
        res = await _asyncio.get_running_loop().run_in_executor(
            None, lambda: render_dsd(Path(src), out_path, dsd_rate=body.rate),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    key = f"dsd_{body.rate}_{body.source}"
    job.artifacts[key] = str(res.out_path)
    return {
        "artifact": key,
        "out_path": str(res.out_path),
        "sample_rate_hz": res.sample_rate,
        "download_url": f"/jobs/{job_id}/download/{key}",
    }


@router.get("/{job_id}/chords")
async def get_chords(job_id: str) -> dict:
    """Return the chord progression timeline (if D5/D-chord analysis ran)."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    p = job.artifacts.get("chords_json")
    if not p:
        return {"available": False}
    import json as _json
    data = _json.loads(Path(p).read_text(encoding="utf-8"))
    return {"available": True, **data}


@router.get("/{job_id}/sections")
async def get_sections(job_id: str) -> dict:
    """Return the analyzed beat grid + section markers (if produced)."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    p = job.artifacts.get("sections_json")
    if not p:
        return {"available": False}
    import json as _json
    data = _json.loads(Path(p).read_text(encoding="utf-8"))
    return {"available": True, **data}


@router.websocket("/{job_id}/progress")
async def job_progress_ws(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    job = registry.get(job_id)
    if job is None:
        await ws.send_json({"type": "error", "message": "job not found"})
        await ws.close()
        return

    queue, replay = await bus.subscribe(job_id)
    try:
        # Replay buffered history so a late client catches up.
        for ev in replay:
            await ws.send_text(ev.to_json())
        # If the job already finished before the client connected, close gracefully.
        if job.status in ("done", "error", "cancelled"):
            await ws.close()
            return
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # ping
                await ws.send_json({"type": "ping"})
                continue
            await ws.send_text(ev.to_json())
            if ev.type in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(job_id, queue)
        try:
            await ws.close()
        except Exception:
            pass
