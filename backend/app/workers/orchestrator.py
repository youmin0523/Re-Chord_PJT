"""Pipeline orchestrator for a single Job.

Runs ingest -> decode -> separate (one or many) -> ensemble -> [karaoke
post-process] -> [analyze] -> [transform] -> encode, publishing progress
events along the way. Heavy CPU/GPU work runs in a thread executor so the
asyncio loop stays responsive to WebSocket clients.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from ..config import settings
from ..core.events import JobEvent, bus
from ..core.jobs import Job
from ..core.paths import ensure_dir
from ..pipeline.analyze import analyze, AnalyzeResult
from ..pipeline.backend_report import (
    build_dependency_warnings,
    freeze_backend_summary,
    record_backend,
    record_fallback,
)
from ..pipeline.chords import analyze_chords, refine_chords, write_chords_json
from ..pipeline.click import generate_click_track
from ..pipeline.decode import decode_to_master
from ..pipeline.encode import encode as encode_fn
from ..pipeline.ensemble import ensemble_stems, mixback
from ..pipeline.ingest import ingest as ingest_fn
from ..pipeline.lyrics import transcribe_lyrics, load_lyrics_json
from ..pipeline.score import build_score
from ..pipeline.sections import analyze_sections
from ..pipeline.separate import MODELS as MODEL_FILES, separate_two_stem
from ..pipeline.polish import polish_instrumental
from ..pipeline.quality import compute_quality, write_quality_json
from ..pipeline.transcribe import transcribe
from ..pipeline.transform import transform_audio, bpm_to_tempo_ratio
from ..pipeline.voice_cue import build_voice_cue_overlay, write_monitor_track

log = logging.getLogger(__name__)


# Per-stage weights for the aggregate 0..1 progress bar.
_STAGE_WEIGHTS: dict[str, float] = {
    "ingest": 0.05,
    "decode": 0.05,
    "separate": 0.46,
    "ensemble": 0.06,
    "karaoke": 0.06,
    "analyze": 0.05,
    "transform": 0.04,
    "lyrics": 0.07,
    "score": 0.08,
    "monitor": 0.05,
    "encode": 0.03,
}


def _aggregate_progress(completed_stages: list[str], current_stage_pct: float) -> float:
    total = 0.0
    for s in completed_stages:
        total += _STAGE_WEIGHTS.get(s, 0.0)
    return min(1.0, total + current_stage_pct)


async def _emit(job: Job, type_: str, stage: str, progress: float, message: str = "", **data) -> None:
    job.stage = stage
    job.progress = progress
    job.message = message
    await bus.publish(JobEvent(
        job_id=job.id, type=type_, stage=stage,
        progress=progress, message=message, data=data,
    ))


async def _mirror_artifacts_to_storage(job: Job) -> None:
    """Upload every job artifact through the configured storage backend.

    No-op when STORAGE_BACKEND=local (the default Phase A path) — the
    local backend would just copy files into ``data/storage/`` for no
    real gain. For S3/R2 we upload each file and stash the remote URL in
    ``job.storage_urls[<key>]`` so clients can use it directly.

    Best-effort: a single failed upload won't poison the others.
    """
    import os as _os
    from ..storage.base import get_storage
    backend_env = (_os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    if backend_env == "local":
        return
    storage = get_storage()
    urls: dict[str, str] = {}
    for key, path in list(job.artifacts.items()):
        try:
            p = Path(path)
            if not p.exists():
                continue
            object_key = f"jobs/{job.id}/{key}{p.suffix}"
            urls[key] = storage.put_file(object_key, str(p))
        except Exception:
            # Skip this one; keep going.
            continue
    if urls:
        job.storage_urls.update(urls)


async def run_job(job: Job) -> None:
    """Execute a job end-to-end. Updates job state + publishes events."""
    job.status = "running"
    job.started_at = time.time()
    opts = job.options
    completed: list[str] = []

    loop = asyncio.get_running_loop()

    async def run_blocking(fn, *args, **kwargs):
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def run_blocking_timed(fn, *args, timeout: float, stage: str, **kwargs):
        """run_blocking with a wall-clock guard.

        ``run_in_executor`` can't forcibly kill a stuck thread, but raising
        TimeoutError frees the asyncio loop and lets the job transition to
        'error' so a single hung stage (a model that never returns, a
        whisper pass on a corrupt stem) doesn't block the queue forever.
        The abandoned worker thread finishes on its own eventually; on a
        single-concurrency queue the GPU is reclaimed by the finally
        block's empty_cache once the next job starts.
        """
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"stage '{stage}' exceeded {timeout:.0f}s and was aborted "
                f"to keep the queue responsive"
            ) from None

    # Per-stage timeouts (seconds). Generous — these are *runaway* guards,
    # not performance targets. Override via env for slow machines.
    import os as _os
    def _stage_timeout(name: str, default: float) -> float:
        try:
            return float(_os.environ.get(f"RECHORD_TIMEOUT_{name.upper()}", default))
        except ValueError:
            return default

    try:
        # --- 0a. Mode-specific default model boost ---------------------
        # Stems mode needs a multi-stem model (htdemucs_6s) to actually
        # expose piano/guitar/bass/drums — the JobOptions default 4-model
        # ensemble is vocals/instrumental-only and would silently flatten
        # the request into a karaoke-shaped result. We also prepend the
        # bleedless SOTA roformer when stems mode is requested so the
        # vocal/instrumental boundary in the ensemble is as clean as
        # possible (directly addresses the "guitar bleed in instrumental"
        # complaint). Users who explicitly listed these stay unaffected.
        if opts.mode == "stems":
            _stems_boost = ["htdemucs_6s", "melband_kim_ft2_bleedless"]
            existing = list(opts.models)
            for alias in reversed(_stems_boost):
                if alias not in existing:
                    existing.insert(0, alias)
            opts.models = existing

        # Pro mode = max quality, time-no-object. Add the bleedless vocal
        # specialist to the ensemble — measured (2026-05-27, MUSDB18-7s)
        # to lift vocal SI-SDR ~+0.23 dB and instrumental ~+0.3 dB over the
        # 4-model default, at the cost of one extra model pass. Quick /
        # karaoke modes keep the faster 4-model set.
        if opts.mode == "pro":
            existing = list(opts.models)
            if "melband_kim_ft2_bleedless" not in existing:
                existing.insert(0, "melband_kim_ft2_bleedless")
            opts.models = existing

        # --- 0b. Disk pre-flight ---------------------------------------
        # Stems / Pro mode can easily eat 6-8 GB per job. Fail fast with
        # a clear message instead of dying mid-separation.
        from ..core.ops import disk_preflight
        chk = disk_preflight(settings.data_dir, mode=opts.mode)
        if not chk.ok:
            await _emit(job, "error", "preflight", 0.0, chk.advice)
            job.status = "error"; job.error = chk.advice
            return

        # --- 1. Ingest --------------------------------------------------
        await _emit(job, "stage", "ingest", _aggregate_progress(completed, 0.0),
                    "Fetching source")
        ingest_result = await run_blocking(ingest_fn, job.input, job.id)
        job.artifacts["source"] = str(ingest_result.source)
        job.meta["source_sr"] = ingest_result.sample_rate
        job.meta["source_codec"] = ingest_result.audio_codec
        job.meta["source_duration"] = ingest_result.duration_sec
        job.meta["source_title"] = ingest_result.title or "track"
        # Fingerprint the source so the /uploads/fingerprint duplicate
        # check can find this job later. Best-effort.
        try:
            from ..core.ops import fingerprint_audio
            fpr = fingerprint_audio(Path(ingest_result.source))
            if fpr.fingerprint:
                job.meta["fingerprint"] = fpr.fingerprint
        except Exception as e:
            log.debug("orchestrator.ingest: fingerprint skipped (%r) — dedup lookup will miss this job", e)
        completed.append("ingest")
        await _emit(job, "log", "ingest", _aggregate_progress(completed, 0.0),
                    f"Ingested {ingest_result.audio_codec} {ingest_result.sample_rate}Hz "
                    f"{ingest_result.duration_sec:.1f}s",
                    source=str(ingest_result.source))

        # --- 2. Decode --------------------------------------------------
        await _emit(job, "stage", "decode", _aggregate_progress(completed, 0.0),
                    "Decoding to working master")
        work_dir = settings.work_dir / job.id
        decode_result = await run_blocking(
            decode_to_master, ingest_result.source, work_dir,
            ingest_result.sample_rate, job.id,
        )
        job.artifacts["master"] = str(decode_result.master)
        job.meta["work_sr"] = decode_result.sample_rate
        completed.append("decode")
        await _emit(job, "log", "decode", _aggregate_progress(completed, 0.0),
                    f"Master {decode_result.sample_rate}Hz "
                    f"{decode_result.duration_sec:.1f}s")

        # --- 3. Separate (one or many models) ---------------------------
        await _emit(job, "stage", "separate", _aggregate_progress(completed, 0.0),
                    f"Separating with {len(opts.models)} model(s)")
        record_backend(
            job, "separate",
            "+".join(opts.models[:4]),
            level="sota" if len(opts.models) >= 3 else "primary",
            note=f"{len(opts.models)}-model ensemble ({opts.ensemble_method})",
        )
        per_model = []
        weight_per_model = _STAGE_WEIGHTS["separate"] / max(1, len(opts.models))
        for idx, alias in enumerate(opts.models):
            filename = MODEL_FILES.get(alias, alias)
            await _emit(job, "stage", "separate",
                        _aggregate_progress(completed, idx * weight_per_model),
                        f"Model {idx + 1}/{len(opts.models)}: {alias}")
            r = await run_blocking_timed(
                separate_two_stem, decode_result.master, job.id, filename,
                timeout=_stage_timeout("separate", 1200.0),
                stage=f"separate:{alias}",
            )
            per_model.append(r)
            await _emit(job, "log", "separate",
                        _aggregate_progress(completed, (idx + 1) * weight_per_model),
                        f"Model {alias} done ({r.elapsed_sec:.1f}s, "
                        f"{r.realtime_factor:.1f}x realtime)")
        completed.append("separate")

        # If Stems mode produced a 6-stem htdemucs_6s result, expose each
        # individual stem as a downloadable artifact and remember the dict so
        # the user can build custom mixdowns afterwards.
        if opts.mode == "stems":
            for r in per_model:
                if "guitar" in r.stems or "piano" in r.stems:
                    for stem_name, p in r.stems.items():
                        if stem_name == "instrumental":
                            continue  # synthesized helper, skip
                        job.artifacts[f"stem_{stem_name}"] = str(p)
                    job.meta["available_stems"] = sorted(
                        n for n in r.stems.keys() if n != "instrumental"
                    )
                    # Cross-bleed QA: flag stem pairs that leak into each
                    # other (bass↔other, guitar↔piano) so the user knows
                    # which stem to trust before transcribing it.
                    try:
                        from ..pipeline.quality import measure_stem_overlap
                        stem_paths = {
                            sn: pth for sn, pth in r.stems.items()
                            if sn != "instrumental"
                        }
                        overlap = await run_blocking(
                            measure_stem_overlap, stem_paths,
                            decode_result.sample_rate, 60.0,
                        )
                        job.meta["stem_overlap"] = overlap
                        if overlap.get("flagged"):
                            await _emit(
                                job, "log", "separate",
                                _aggregate_progress(completed, 0.0),
                                "stem 누설 감지: "
                                + ", ".join(overlap["flagged"])
                                + f" (max xcorr {overlap.get('max_xcorr')})",
                            )
                    except Exception as _ov:
                        await _emit(job, "log", "separate",
                                    _aggregate_progress(completed, 0.0),
                                    f"stem overlap 측정 skip: {_ov!r}")
                    break

        # --- 4. Ensemble -----------------------------------------------
        if len(per_model) > 1:
            await _emit(job, "stage", "ensemble", _aggregate_progress(completed, 0.0),
                        f"Combining {len(per_model)} sources ({opts.ensemble_method})")
            ens_dir = settings.stems_dir / job.id / f"ensemble_{opts.ensemble_method}"
            ensure_dir(ens_dir)
            inst_sources = [r.stems["instrumental"] for r in per_model if "instrumental" in r.stems]
            voc_sources = [r.stems["vocals"] for r in per_model if "vocals" in r.stems]
            # Build per-model trust weights so the SOTA mel-band / BS-Roformer
            # ckpts pull the ensemble harder than the older htdemucs anchors.
            try:
                from ..pipeline.ensemble import weight_for_model
                _model_weights = [weight_for_model(m) for m in opts.models]
            except Exception:
                _model_weights = None
            # Auto-upgrade ensemble method when the user kept the legacy default.
            _ens_method = opts.ensemble_method
            if _ens_method == "mag_avg" and len(inst_sources) >= 3:
                _ens_method = "weighted_mag"
            inst_res = await run_blocking(
                lambda: ensemble_stems(
                    inst_sources, ens_dir / "instrumental.wav",
                    _ens_method, decode_result.sample_rate,
                    opts.stereo_mode,
                    weights=_model_weights, phase_coherent=True,
                ),
            )
            voc_res = await run_blocking(
                lambda: ensemble_stems(
                    voc_sources, ens_dir / "vocals.wav",
                    _ens_method, decode_result.sample_rate,
                    opts.stereo_mode,
                    weights=_model_weights, phase_coherent=True,
                ),
            )
            job.meta["ensemble_method_used"] = _ens_method
            job.meta["ensemble_phase_coherent"] = True
            if _model_weights:
                job.meta["ensemble_weights"] = {
                    m: round(w, 2) for m, w in zip(opts.models, _model_weights)
                }
            current_inst = inst_res.out_path
            current_voc = voc_res.out_path
            completed.append("ensemble")
            await _emit(job, "log", "ensemble", _aggregate_progress(completed, 0.0),
                        f"Combined {inst_res.n_sources} sources, stereo={opts.stereo_mode}")

            # Optional spectrogram-diff residual masking (Pro mode).
            # Now iterative by default — two attenuating passes catch the
            # residual that a single pass leaves behind without dulling
            # high-frequency air.
            if opts.apply_diff_mask:
                try:
                    from ..pipeline.ensemble import apply_diff_mask_iterative
                    from ..pipeline.quality import suggest_diff_mask_strength
                    # Auto-tune the mask strength from measured vocal-band
                    # leakage. The user-supplied diff_mask_strength becomes
                    # the *cap*; a clean separation uses a gentler value so
                    # we don't dull the air on already-good instrumentals.
                    sugg = await run_blocking(
                        suggest_diff_mask_strength,
                        current_inst, current_voc, decode_result.sample_rate,
                        30.0,
                    )
                    auto_strength = min(
                        float(sugg.get("strength") or opts.diff_mask_strength),
                        opts.diff_mask_strength if opts.diff_mask_strength > 0 else 0.75,
                    )
                    job.meta["diff_mask_auto"] = sugg
                    job.meta["diff_mask_strength_used"] = round(auto_strength, 3)
                    diff_path = ens_dir / "instrumental_diffmasked.wav"
                    await run_blocking(
                        lambda: apply_diff_mask_iterative(
                            current_inst, current_voc, diff_path,
                            target_sr=decode_result.sample_rate,
                            passes=2, strength=auto_strength,
                            decay=0.7,
                        ),
                    )
                    current_inst = diff_path
                    await _emit(job, "log", "ensemble",
                                _aggregate_progress(completed, 0.0),
                                f"iterative diff-mask (2 passes, auto "
                                f"strength={auto_strength:.2f}; "
                                f"{sugg.get('reason', '')})")
                except Exception as e:
                    await _emit(job, "log", "ensemble",
                                _aggregate_progress(completed, 0.0),
                                f"diff-mask skipped: {e!r}")
        else:
            current_inst = per_model[0].stems["instrumental"]
            current_voc = per_model[0].stems["vocals"]

        # --- 4b. Optional mixback --------------------------------------
        if opts.mixback:
            mb_dir = settings.stems_dir / job.id / \
                f"ensemble_{opts.ensemble_method}_mixback{int(opts.inst_share * 100):03d}"
            paths = await run_blocking(
                mixback, decode_result.master, current_inst, current_voc,
                mb_dir / "instrumental.wav", mb_dir / "vocals.wav",
                opts.inst_share, decode_result.sample_rate,
            )
            current_inst = paths["instrumental"]
            current_voc = paths["vocals"]
            await _emit(job, "log", "ensemble", _aggregate_progress(completed, 0.0),
                        f"Mixback applied (share={opts.inst_share:.2f})")

        # --- 5. Karaoke post-process (residual vocal cleanup) ----------
        if opts.karaoke_postprocess:
            await _emit(job, "stage", "karaoke",
                        _aggregate_progress(completed, 0.0),
                        "Karaoke post-process (residual vocal cleanup)")
            karaoke_model = MODEL_FILES["mel_karaoke_aufr33"]
            try:
                kr = await run_blocking(
                    separate_two_stem, current_inst,
                    f"{job.id}_post", karaoke_model,
                )
                if "instrumental" in kr.stems:
                    current_inst = kr.stems["instrumental"]
                completed.append("karaoke")
                await _emit(job, "log", "karaoke",
                            _aggregate_progress(completed, 0.0),
                            f"Karaoke pass done ({kr.elapsed_sec:.1f}s)")
            except Exception as e:
                # Residual-vocal cleanup is optional polish — never let it sink
                # the whole job. Keep the (already valid) main-model
                # instrumental. The mel-band model's overlap-add notably fails
                # on clips shorter than its ~8s chunk; real songs are far
                # longer, but we degrade gracefully for any failure.
                await _emit(job, "log", "karaoke",
                            _aggregate_progress(completed, 0.0),
                            f"Karaoke pass skipped (kept main instrumental): {e!r}")

            # Optional: split the vocal stem itself into lead vs backing
            # (the karaoke model separates *main* vocals from everything else).
            # When the user wants choir/backing kept, we sum the karaoke
            # model's "instrumental" output (= non-main parts of vocals)
            # onto the current instrumental.
            if opts.keep_backing_vocals:
                try:
                    bv = await run_blocking(
                        separate_two_stem, current_voc,
                        f"{job.id}_bv", karaoke_model,
                    )
                    backing = bv.stems.get("instrumental")
                    if backing:
                        import numpy as _np
                        import soundfile as _sf
                        inst_arr, sr_a = _sf.read(str(current_inst),
                                                  dtype="float32", always_2d=True)
                        bk_arr, sr_b = _sf.read(str(backing),
                                                dtype="float32", always_2d=True)
                        if sr_a == sr_b and inst_arr.shape[1] == bk_arr.shape[1]:
                            n = min(inst_arr.shape[0], bk_arr.shape[0])
                            mixed = inst_arr[:n] + bk_arr[:n]
                            _np.clip(mixed, -1.0, 1.0, out=mixed)
                            bv_dir = settings.stems_dir / job.id / "with_backing"
                            ensure_dir(bv_dir)
                            bv_path = bv_dir / "instrumental_with_backing.wav"
                            _sf.write(str(bv_path), mixed, sr_a, subtype="FLOAT")
                            current_inst = bv_path
                            await _emit(job, "log", "karaoke",
                                        _aggregate_progress(completed, 0.0),
                                        "backing vocals merged into instrumental")
                        # Also keep main-only vocals as a new artifact.
                        main_only = bv.stems.get("vocals")
                        if main_only:
                            job.artifacts["vocals_lead"] = str(main_only)
                except Exception as e:
                    await _emit(job, "log", "karaoke",
                                _aggregate_progress(completed, 0.0),
                                f"backing split skipped: {e!r}")

        # --- 5a. Polish (light mixback + dynaudnorm) -------------------
        # Fixes the "compression / ducking" feel and dry-vocal-hole artifacts
        # that bare separated instrumentals exhibit. Conservative defaults:
        # only 20% of the residual is added back to keep vocal leakage tiny.
        if opts.polish:
            try:
                pol_dir = settings.stems_dir / job.id / "polish"
                ensure_dir(pol_dir)
                pol_res = await run_blocking(
                    lambda: polish_instrumental(
                        decode_result.master, current_inst, current_voc,
                        pol_dir,
                        inst_share=opts.polish_inst_share,
                        do_mixback=True,
                        do_dynaudnorm=True,
                        target_sr=decode_result.sample_rate,
                        do_reverb_tail=opts.polish_reverb_tail,
                    ),
                )
                current_inst = pol_res.out_path
                job.meta["polish_inst_share"] = pol_res.inst_share
                job.meta["polish_used"] = (
                    ("mixback" if pol_res.used_mixback else "")
                    + ("+dynaudnorm" if pol_res.used_dynaudnorm else "")
                )
                await _emit(job, "log", "ensemble",
                            _aggregate_progress(completed, 0.0),
                            f"polished (mixback={opts.polish_inst_share:.2f}, "
                            f"dynaudnorm={pol_res.used_dynaudnorm})")
            except Exception as e:
                await _emit(job, "log", "ensemble",
                            _aggregate_progress(completed, 0.0),
                            f"polish skipped: {e!r}")

        job.artifacts["instrumental"] = str(current_inst)
        job.artifacts["vocals"] = str(current_voc)

        # --- 5b. Quality report (null-test + leak metrics) -------------
        try:
            q = await run_blocking(
                compute_quality, decode_result.master, current_inst, current_voc,
                decode_result.sample_rate, 90.0,
            )
            q_path = settings.output_dir / job.id / "quality.json"
            await run_blocking(write_quality_json, q, q_path)
            job.artifacts["quality_json"] = str(q_path)
            job.meta["quality_grade"] = q.grade()
            job.meta["quality_null_rms_dbfs"] = q.null_rms_dbfs
            job.meta["quality_recon_corr"] = q.reconstruction_corr
            job.meta["quality_vocal_leak_dbfs"] = q.vocal_leak_dbfs
            job.meta["quality_voc_inst_xcorr"] = q.voc_inst_xcorr
            await _emit(job, "log", "ensemble",
                        _aggregate_progress(completed, 0.0),
                        f"quality grade={q.grade()}  null={q.null_rms_dbfs:.1f}dB  "
                        f"recon={q.reconstruction_corr:.3f}")
        except Exception as e:
            await _emit(job, "log", "ensemble",
                        _aggregate_progress(completed, 0.0),
                        f"quality measurement failed (continuing): {e!r}")

        # --- 6. Analyze (optional, on instrumental) --------------------
        # analyze() also fires whenever the user explicitly asked for chord /
        # score / lyrics output — those stages downstream need the detected
        # key/bpm. Without this gate the SOTA refinement chain (CREMA + LLM)
        # never sees a key and silently falls back to template-only chords.
        _want_analyze = (
            opts.mode in ("karaoke", "pro")
            or opts.detect_chords
            or opts.make_score
            or opts.make_lyrics
        )
        if _want_analyze:
            await _emit(job, "stage", "analyze", _aggregate_progress(completed, 0.0),
                        "Detecting key and BPM")
            try:
                an = await run_blocking(analyze, current_inst)
            except Exception as e:
                # Key/BPM detection is enrichment over an already-finished MR —
                # never let it discard a good instrumental. Fall back to an
                # unknown-key / neutral-tempo result (confidence 0) so the job
                # completes; downstream chord/score stages gate on their own
                # confidence and degrade from here.
                an = AnalyzeResult(key_name="unknown", key_root="C",
                                   key_mode="major", key_confidence=0.0,
                                   bpm=120.0, bpm_confidence=0.0,
                                   duration_sec=0.0)
                await _emit(job, "log", "analyze",
                            _aggregate_progress(completed, 0.0),
                            f"key/BPM detection failed, using defaults: {e!r}")
            # Record which key-detector path actually ran (madmom CNN
            # vs librosa Krumhansl fallback). detect via probing import.
            try:
                from importlib import util as _iu
                if _iu.find_spec("madmom") is not None:
                    record_backend(job, "key_detect", "madmom_cnn",
                                   level="sota",
                                   note="CNNKeyRecognitionProcessor")
                    record_backend(job, "beat_grid", "madmom_dbn",
                                   level="sota",
                                   note="DBNDownBeatTrackingProcessor")
                else:
                    record_backend(job, "key_detect", "librosa_krumhansl",
                                   level="fallback",
                                   note="Krumhansl-Schmuckler template match")
                    record_backend(job, "beat_grid", "librosa_beat_track",
                                   level="fallback",
                                   note="onset-energy meter scoring")
                    record_fallback(job, "key_detect", "madmom",
                                    reason="package not installed")
            except Exception as e:
                log.debug("orchestrator.analyze: backend-report stamping skipped (%r)", e)
            job.meta["key_name"] = an.key_name
            job.meta["key_root"] = an.key_root
            job.meta["key_mode"] = an.key_mode
            job.meta["key_confidence"] = an.key_confidence

            # ────────────────────────────────────────────────────────
            # Triple-source BPM fusion + half/double recovery.
            # ────────────────────────────────────────────────────────
            # The 'fail' case from v3 ("우리가 주를 더욱" 139.5 vs 78) was
            # both madmom RNN and DBN locking on the same wrong octave.
            # We add a third *independent* source — librosa's
            # autocorrelation-based beat_track — and vote among the
            # raw values + their {÷2, ×2} candidates with a musical
            # band prior (most worship/pop sits in 60–160).
            from ..pipeline.sections import detect_beat_grid as _dbg
            try:
                bg = await run_blocking(_dbg, current_inst, "auto")
                rnn_bpm = float(an.bpm)
                dbn_bpm = float(bg.bpm)

                def _librosa_bpm(path) -> float:
                    import librosa as _lr
                    import numpy as _np
                    y, sr = _lr.load(str(path), sr=22050, mono=True)
                    y_p = _lr.effects.percussive(y, margin=4.0)
                    onset = _lr.onset.onset_strength(y=y_p, sr=sr,
                                                     aggregate=_np.median)
                    tempo_arr = _lr.feature.tempo(onset_envelope=onset, sr=sr,
                                                  aggregate=None)
                    if tempo_arr is None or len(tempo_arr) == 0:
                        return 0.0
                    return float(_np.median(tempo_arr))

                def _drums_bpm(path) -> float:
                    """Quarter-note pulse from the **kick drum**.

                    Full-mix drum onset detection picks up kick + snare
                    + hi-hat together, and the eighth-note hi-hat firing
                    rate dominates the inter-onset-interval histogram —
                    that's how v8 ended up reporting 136 BPM on songs
                    whose actual quarter-note pulse is 72.

                    Fix: low-pass the drums stem at 150 Hz so only the
                    kick drum's fundamental survives. Kicks land
                    overwhelmingly on the downbeat / quarter-note grid in
                    every worship/pop/rock convention, so the resulting
                    IOI median is a clean quarter-note tempo. As a
                    sanity check we *also* compute the raw onset BPM and
                    treat the kick-only value as truth when it's roughly
                    half the raw value (the expected relationship when
                    the raw onset stream was tracking 8th notes).
                    """
                    import librosa as _lr
                    import numpy as _np
                    import scipy.signal as _ss
                    y, sr = _lr.load(str(path), sr=22050, mono=True)

                    def _ioi_bpm(samples):
                        of = _lr.onset.onset_detect(
                            y=samples, sr=sr, units="frames",
                            backtrack=False, pre_max=10, post_max=10,
                            pre_avg=20, post_avg=20, delta=0.07, wait=5,
                        )
                        if of is None or len(of) < 8:
                            return 0.0
                        ot = _lr.frames_to_time(of, sr=sr)
                        iois = _np.diff(ot)
                        iois = iois[(iois > 0.18) & (iois < 1.5)]
                        if len(iois) < 4:
                            return 0.0
                        return 60.0 / float(_np.median(iois))

                    # Raw drums (kick + snare + hi-hat).
                    raw_bpm = _ioi_bpm(y)
                    # Kick-only via low-pass — Butterworth 4-pole at 150 Hz.
                    try:
                        b, a = _ss.butter(4, 150.0 / (sr / 2.0), btype="low")
                        y_kick = _ss.lfilter(b, a, y).astype(_np.float32)
                        kick_bpm = _ioi_bpm(y_kick)
                    except Exception:
                        kick_bpm = 0.0

                    # Decision rule: prefer kick_bpm unless it failed.
                    # If kick is roughly half of raw (the eighth-note
                    # confusion case), kick is right; if they agree,
                    # both are right and we report kick anyway because
                    # it's less susceptible to ornamentation noise.
                    if 40 <= kick_bpm <= 200:
                        return kick_bpm
                    return raw_bpm

                try:
                    lib_bpm = await run_blocking(_librosa_bpm, current_inst)
                except Exception:
                    lib_bpm = 0.0

                # Drums-stem source — only available in stems mode.
                drums_bpm = 0.0
                drums_path = job.artifacts.get("stem_drums")
                if drums_path and Path(drums_path).exists():
                    try:
                        drums_bpm = await run_blocking(_drums_bpm, Path(drums_path))
                    except Exception:
                        drums_bpm = 0.0

                # Each detector contributes 3 candidates: raw, raw/2, raw*2.
                # We collect all candidates, throw away anything outside the
                # 50–200 sanity band, then pick the value where the most
                # detectors agree within ±5%. If nothing agrees, fall back
                # to whichever single value sits closest to the band centre
                # (110 BPM — empirical mid for the worship/pop catalogue).
                def _candidates(b: float) -> list[float]:
                    return [v for v in (b, b / 2.0, b * 2.0) if 50.0 <= v <= 200.0]

                pool: list[tuple[float, str]] = []
                for src, b in (("rnn", rnn_bpm), ("dbn", dbn_bpm),
                               ("lib", lib_bpm), ("drums", drums_bpm)):
                    for c in _candidates(b):
                        pool.append((c, src))

                fused_bpm = rnn_bpm  # safe default
                best_count = 0
                ties: list[float] = []
                if pool:
                    # For each candidate, count how many *distinct* detector
                    # sources have at least one candidate within ±5%.
                    for cand, _ in pool:
                        srcs = set()
                        for other, src in pool:
                            if abs(other - cand) / cand <= 0.05:
                                srcs.add(src)
                        n = len(srcs)
                        if n > best_count:
                            best_count = n
                            ties = [cand]
                        elif n == best_count:
                            ties.append(cand)

                # Tie-break — pick the *lower* tied candidate. v6 tried the
                # opposite (favouring higher) on the theory that halving
                # is more common than doubling; in practice that flipped
                # Way Maker / Goodness of God / 주님의 선하심 into doubled
                # numbers (≈120-145 BPM) which is plainly wrong for those
                # ballads. Halving and doubling are both real failure
                # modes; we leave the absolute resolution to the
                # chord-rate-based 4th source below, which uses the
                # chord-change interval to decide the right octave
                # independently of the onset detectors.
                if ties:
                    pick_from = ties
                    pick_from.sort()
                    fused_bpm = min(pick_from)

                # Final band guard.
                while fused_bpm > 200.0:
                    fused_bpm /= 2.0
                while 0 < fused_bpm < 50.0:
                    fused_bpm *= 2.0

                job.meta["bpm"] = float(fused_bpm)
                job.meta["bpm_confidence"] = float(
                    {3: 0.95, 2: 0.85, 1: 0.65}.get(best_count, 0.5)
                )
                job.meta["bpm_sources"] = {
                    "rnn_tempo": round(rnn_bpm, 2),
                    "dbn_downbeat": round(dbn_bpm, 2),
                    "librosa_autocorr": round(lib_bpm, 2),
                    "drums_onset_ioi": round(drums_bpm, 2),
                    "fused": round(fused_bpm, 2),
                    "agreeing_sources": best_count,
                }
                # Useful side-effect: stash the beat grid for any downstream
                # consumer (click track, score time-map) that wants it.
                job.meta["meter"] = bg.meter
                job.meta["time_signature"] = bg.time_signature
                job.meta["is_compound"] = bg.is_compound
            except Exception:
                job.meta["bpm"] = an.bpm
                job.meta["bpm_confidence"] = an.bpm_confidence
            completed.append("analyze")
            await _emit(job, "log", "analyze", _aggregate_progress(completed, 0.0),
                        f"Key {an.key_name} ({an.key_confidence:.2f}), "
                        f"BPM {job.meta['bpm']:.1f} ({job.meta['bpm_confidence']:.2f})")

            # AI chord detection (per-bar). On by default for karaoke/pro.
            want_chords = opts.detect_chords or opts.mode in ("karaoke", "pro")
            if want_chords:
                try:
                    chord_events = await run_blocking(analyze_chords, current_inst)
                    # Pro mode: layer CREMA + functional-harmony + LLM refinement
                    # on top of the template-match output. Each layer is a no-op
                    # when its dependency is missing, so this is safe to always
                    # call.
                    downbeats = []
                    try:
                        sec_artifact = job.artifacts.get("sections_json")
                        if sec_artifact:
                            import json as _json
                            _sec = _json.loads(Path(sec_artifact).read_text(encoding="utf-8"))
                            downbeats = list(_sec.get("downbeats_sec") or [])
                    except Exception:
                        downbeats = []
                    # SOTA refinement (CREMA 170-class + theory + LLM) now
                    # also fires when the user opted in via detect_chords on
                    # any mode — previously these were gated to ``pro`` only,
                    # which silently downgraded explicit user intent.
                    _full_refine = opts.mode == "pro" or opts.detect_chords
                    _chord_refine_report: dict = {}
                    chord_events = await run_blocking(
                        lambda evs=chord_events: refine_chords(
                            evs,
                            key_root=job.meta.get("key_root") or None,
                            key_mode=job.meta.get("key_mode") or None,
                            audio_path=current_inst,
                            downbeats_sec=downbeats,
                            use_crema=_full_refine,
                            use_theory=True,
                            use_llm=_full_refine,
                            report=_chord_refine_report,
                        ),
                    )
                    stages_run = _chord_refine_report.get("stages_run", [])
                    stages_skip = _chord_refine_report.get("stages_skipped", [])
                    primary = ("crema" if "crema" in stages_run
                               else "template_match")
                    extras = "+".join(s for s in stages_run
                                      if s not in ("stabilize",))
                    record_backend(
                        job, "chord_detect", primary,
                        level="sota" if "crema" in stages_run else "primary",
                        note=f"refine chain: {extras or 'stabilize-only'}",
                    )
                    for s in stages_skip:
                        record_fallback(job, "chord_detect",
                                        missing=s.get("stage", "?"),
                                        reason=s.get("reason", ""))
                    # Slash-chord cross-check against the bass stem (stems
                    # mode). When CREMA reports "C/E" but the bass stem is
                    # actually playing G, we strip the slash so the user
                    # doesn't transcribe a hallucinated bass note.
                    bass_path = job.artifacts.get("stem_bass")
                    if bass_path:
                        try:
                            from ..pipeline.chord_bass_check import (
                                cross_check_slash_bass,
                            )
                            check_rep = await run_blocking(
                                cross_check_slash_bass,
                                chord_events, Path(bass_path),
                            )
                            job.meta["chord_bass_check"] = check_rep
                            await _emit(
                                job, "log", "analyze",
                                _aggregate_progress(completed, 0.0),
                                "slash-bass cross-check: "
                                f"confirmed={check_rep.get('confirmed', 0)} "
                                f"downgraded={check_rep.get('downgraded', 0)} "
                                f"ambiguous={check_rep.get('ambiguous', 0)}",
                            )
                        except Exception as _bc:
                            await _emit(
                                job, "log", "analyze",
                                _aggregate_progress(completed, 0.0),
                                f"slash-bass check skipped: {_bc!r}",
                            )

                    chord_dir = settings.output_dir / job.id / "chords"
                    ensure_dir(chord_dir)
                    chord_path = chord_dir / "chords.json"
                    await run_blocking(write_chords_json, chord_events, chord_path)
                    job.artifacts["chords_json"] = str(chord_path)
                    job.meta["chord_count"] = len(chord_events)
                    # Detect modulations (key shifts) from the chord stream.
                    # Worship's last-chorus semitone lift, pop pre-chorus
                    # lifts, etc. — flagged so the UI can render markers.
                    try:
                        from ..pipeline.analyze import detect_modulations
                        mods = detect_modulations(chord_events)
                        if mods:
                            job.meta["modulations"] = mods
                    except Exception as e:
                        await _emit(job, "log", "analyze",
                                    _aggregate_progress(completed, 0.0),
                                    f"modulation detect failed: {e!r}")
                    await _emit(job, "log", "analyze",
                                _aggregate_progress(completed, 0.0),
                                f"{len(chord_events)} chord segments detected + refined")

                    # ──────────────────────────────────────────────────
                    # 4th BPM source: chord-change rate.
                    # ──────────────────────────────────────────────────
                    # Chord recognition is the most reliable stage of the
                    # pipeline (audited at 1.00 transposition-invariant on
                    # 5 worship/pop tracks). The interval between chord
                    # changes therefore gives us a very clean second
                    # opinion on whether the onset-based BPM fusion
                    # picked the right metric octave.
                    #
                    # Worship / pop convention: chords change every 1
                    # bar (most common) or 2 bars (slow ballad bridges).
                    # That means avg_chord_duration ≈ 60 / BPM × 4 for
                    # 4/4. We evaluate three octave hypotheses against
                    # the chord rate; if the existing fused BPM disagrees
                    # with chord-rate by more than a factor of √2, we
                    # snap to the closer chord-rate-implied octave.
                    try:
                        # Use chord-change boundaries (skip the trailing N
                        # which contributes no rhythmic information).
                        durs = []
                        for e in chord_events:
                            label = getattr(e, "label", None) or ""
                            if not label or label.upper() in ("N", "X", "N.C."):
                                continue
                            d = float(getattr(e, "end_sec", 0)) - float(getattr(e, "start_sec", 0))
                            if 0.2 < d < 30.0:    # sanity bound (chord rarely shorter than half-beat or longer than 30s)
                                durs.append(d)
                        if len(durs) >= 6:
                            import numpy as _np
                            avg_chord_dur = float(_np.median(durs))
                            # Multi-hypothesis chord-rate. We can't assume
                            # one chord = one bar — worship/pop songs use
                            # half-bar chord changes (especially 2-chord
                            # bridges) AND 2-bar / 4-bar holds (slow
                            # ballads, intro pads). So we generate every
                            # plausible "N bars per chord" candidate
                            # (N in {0.25, 0.5, 1, 2, 4}) and pick whichever
                            # lands closest to the drum-stem pulse (the
                            # most reliable octave reference we have).
                            # Formula assumes 4/4: BPM = (4 / N) / avg_dur × 60.
                            chord_bpm_hyp = {
                                f"{n}_bar_per_chord": (4.0 / n) * 60.0 / avg_chord_dur
                                for n in (0.25, 0.5, 1.0, 2.0, 4.0)
                            }
                            in_band = {k: v for k, v in chord_bpm_hyp.items()
                                       if 50.0 <= v <= 200.0}
                            current = float(job.meta.get("bpm") or rnn_bpm)
                            # Anchor selection — promoted from a blind
                            # "drums wins" rule to a *consensus* rule.
                            # v8/v9 observed that drums-onset BPM has its
                            # own systemic bias (hi-hat 8th-note pulse
                            # dominates the IOI histogram on hat-heavy
                            # tracks, so drums comes back at 2× the
                            # quarter pulse). Now we only trust drums when
                            # at least one other detector lands within
                            # ±7% (log₂ ≤ 0.1) — that's strong agreement
                            # that the drums octave is correct. Otherwise
                            # we fall back to the median of the onset
                            # sources, which avoids the v8 "everything
                            # doubled because drums said so" failure.
                            def _log_ratio(a, b):
                                return abs(_np.log2(a / b)) if a > 0 and b > 0 else 99.0
                            # Confirm drums ONLY against madmom's RNN/DBN —
                            # NOT librosa. librosa autocorrelation shares
                            # the drums-onset family's eighth-note bias, so
                            # a drums↔librosa "agreement" is two detectors
                            # making the same mistake. madmom RNN + DBN are
                            # an independent algorithm family, so agreement
                            # there is a genuine octave confirmation.
                            drums_confirmed = (
                                50.0 <= drums_bpm <= 200.0 and any(
                                    _log_ratio(drums_bpm, b) < 0.1
                                    for b in (rnn_bpm, dbn_bpm) if b > 0
                                )
                            )
                            onset_sources = [b for b in (rnn_bpm, dbn_bpm, lib_bpm)
                                             if 40.0 <= b <= 200.0]
                            if drums_confirmed:
                                anchor = drums_bpm
                            elif onset_sources:
                                anchor = float(_np.median(onset_sources))
                            else:
                                anchor = current
                            if in_band:
                                chord_bpm = min(
                                    in_band.values(),
                                    key=lambda v: abs(_np.log2(v / anchor))
                                )
                                # log2 distance: 0 = identical, ±1 = octave.
                                log_diff_anchor = float(abs(_np.log2(chord_bpm / anchor)))
                                log_diff_current = float(abs(_np.log2(chord_bpm / current)))
                                # If chord-rate (anchored to drums when
                                # possible) disagrees with the current
                                # fused BPM by more than ~√2, snap. This
                                # is the fix for "BREAK EVERY CHAIN 56 →
                                # 113" (drums fires every quarter note
                                # @113 BPM, chord-rate's 2-bar hypothesis
                                # matches drums; current 56 BPM is 1
                                # octave low; snap to 113).
                                if log_diff_current > 0.5:
                                    job.meta["bpm"] = float(chord_bpm)
                                    job.meta["bpm_confidence"] = max(
                                        float(job.meta.get("bpm_confidence") or 0),
                                        0.92,
                                    )
                                # Stash diagnostics.
                                bs = dict(job.meta.get("bpm_sources") or {})
                                bs["chord_rate_avg_dur_sec"] = round(avg_chord_dur, 3)
                                bs["chord_rate_hypotheses"] = {
                                    k: round(v, 2) for k, v in chord_bpm_hyp.items()
                                }
                                bs["chord_rate_anchor"] = round(anchor, 2)
                                bs["chord_rate_picked"] = round(chord_bpm, 2)
                                bs["chord_rate_log_diff_anchor"] = round(log_diff_anchor, 3)
                                bs["chord_rate_log_diff_current"] = round(log_diff_current, 3)
                                bs["final"] = round(float(job.meta["bpm"]), 2)
                                job.meta["bpm_sources"] = bs
                                await _emit(
                                    job, "log", "analyze",
                                    _aggregate_progress(completed, 0.0),
                                    f"chord-rate BPM check: avg={avg_chord_dur:.2f}s, "
                                    f"picked={chord_bpm:.1f} (anchor={anchor:.1f}), "
                                    f"final BPM={job.meta['bpm']:.1f}",
                                )
                    except Exception as _e:
                        # Chord-rate cross-check is best-effort — failures
                        # leave the onset-based fused BPM in place.
                        pass

                    # ── Octave candidates for the UI's "is this the right
                    # tempo?" picker. BPM octave (×2 / ÷2) is a genuine MIR
                    # ambiguity that no single detector resolves reliably —
                    # so we surface the half / double of our best estimate
                    # alongside it. The user confirms by ear against the
                    # click track (no absolute pitch needed) and PATCH
                    # /jobs/{id}/bpm flips to the chosen octave.
                    try:
                        _final = float(job.meta.get("bpm") or 0)
                        if _final > 0:
                            # BPM is conventionally an integer (metronome
                            # marks, lead sheets). The detectors return
                            # fractional values (61.52, 139.67) because
                            # they average inter-beat intervals — but the
                            # user-facing number should read as a clean
                            # integer. We keep the precise float in
                            # bpm_sources["final_precise"] for any
                            # downstream tempo-stretch math that needs it.
                            bs = dict(job.meta.get("bpm_sources") or {})
                            bs["final_precise"] = round(_final, 2)
                            job.meta["bpm_sources"] = bs
                            job.meta["bpm"] = int(round(_final))
                            cand = sorted({
                                int(round(_final / 2.0)),
                                int(round(_final)),
                                int(round(_final * 2.0)),
                            })
                            job.meta["bpm_octave_candidates"] = [
                                c for c in cand if 30 <= c <= 240
                            ]
                    except Exception as e:
                        log.debug("orchestrator.analyze: bpm octave candidates skipped (%r)", e)
                except Exception as e:
                    await _emit(job, "log", "analyze",
                                _aggregate_progress(completed, 0.0),
                                f"chord detection skipped: {e!r}")

        # --- 7. Transform (optional pitch/tempo) -----------------------
        need_transform = abs(opts.semitones) > 1e-6 or abs(opts.tempo_ratio - 1.0) > 1e-6 \
            or (opts.source_bpm > 0 and opts.target_bpm > 0)
        if need_transform:
            await _emit(job, "stage", "transform", _aggregate_progress(completed, 0.0),
                        "Applying pitch / tempo transform")
            semitones = opts.semitones
            tempo_ratio = opts.tempo_ratio
            if opts.source_bpm > 0 and opts.target_bpm > 0:
                tempo_ratio = bpm_to_tempo_ratio(opts.source_bpm, opts.target_bpm)
            tf_dir = settings.stems_dir / job.id / "transformed"
            ensure_dir(tf_dir)
            # stem_kind picks the most natural Rubber Band preset per content
            # type. Transform both stems BEFORE committing either, so a failure
            # on one can't leave a half-applied key change (instrumental in the
            # new key, vocals in the old). Never let it sink the finished MR.
            try:
                tf_inst = await run_blocking(
                    transform_audio, current_inst, tf_dir / "instrumental.wav",
                    semitones, tempo_ratio, "auto", "instrumental",
                )
                tf_voc = await run_blocking(
                    transform_audio, current_voc, tf_dir / "vocals.wav",
                    semitones, tempo_ratio, "auto", "vocals",
                )
                current_inst = tf_inst.out_path
                current_voc = tf_voc.out_path
                completed.append("transform")
                await _emit(job, "log", "transform",
                            _aggregate_progress(completed, 0.0),
                            f"transform: inst engine={tf_inst.engine} "
                            f"voc engine={tf_voc.engine} | "
                            f"semitones={semitones:+.2f} tempo_ratio={tempo_ratio:.4f}")
            except Exception as e:
                await _emit(job, "log", "transform",
                            _aggregate_progress(completed, 0.0),
                            f"pitch/tempo transform failed, kept original "
                            f"key/tempo: {e!r}")

        # --- 7a. Monitor track (voice cues + click) --------------------
        if opts.voice_cues or opts.click_track or opts.monitor_track:
            await _emit(job, "stage", "monitor", _aggregate_progress(completed, 0.0),
                        "Building monitor track (voice cues + click)")
            try:
                meter_arg = opts.meter if opts.meter else "auto"
                # Convert numeric meter override to int; 'auto' stays string.
                if meter_arg != "auto":
                    try:
                        meter_arg = int(meter_arg)
                    except ValueError:
                        meter_arg = "auto"
                sec_res = await run_blocking(
                    analyze_sections, current_inst, meter_arg,
                )
                duration = float(sec_res.beat_grid.beats_sec[-1]
                                 if sec_res.beat_grid.beats_sec
                                 else decode_result.duration_sec)

                # Persist sections.json for downstream UI use.
                import json as _json
                sec_dir = settings.output_dir / job.id / "sections"
                ensure_dir(sec_dir)
                sec_json = sec_dir / "sections.json"
                sec_json.write_text(
                    _json.dumps({
                        "bpm": sec_res.beat_grid.bpm,
                        "meter": sec_res.beat_grid.meter,
                        "time_signature": sec_res.beat_grid.time_signature,
                        "is_compound": sec_res.beat_grid.is_compound,
                        "beats_sec": sec_res.beat_grid.beats_sec,
                        "downbeats_sec": sec_res.beat_grid.downbeats_sec,
                        "sections": [
                            {"start_sec": s.start_sec, "end_sec": s.end_sec,
                             "label": s.label}
                            for s in sec_res.sections
                        ],
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                job.artifacts["sections_json"] = str(sec_json)
                job.meta["time_signature"] = sec_res.beat_grid.time_signature
                await _emit(job, "log", "monitor",
                            _aggregate_progress(completed, 0.0),
                            f"sections={len(sec_res.sections)} "
                            f"bpm={sec_res.beat_grid.bpm:.1f} "
                            f"meter={sec_res.beat_grid.time_signature}")

                cue_overlay = None
                click_overlay = None
                if opts.voice_cues:
                    cue_res = await run_blocking(
                        build_voice_cue_overlay,
                        sec_res.sections, sec_res.beat_grid, duration,
                        decode_result.sample_rate, opts.voice_cue_lang,
                        None,
                    )
                    cue_overlay = cue_res.audio
                    await _emit(job, "log", "monitor",
                                _aggregate_progress(completed, 0.0),
                                f"voice cues placed: {cue_res.cues_placed}")
                if opts.click_track:
                    click_dir = settings.output_dir / job.id / "click"
                    ensure_dir(click_dir)
                    click_path = click_dir / "click.wav"
                    click_res = await run_blocking(
                        generate_click_track,
                        sec_res.beat_grid, duration, click_path,
                        decode_result.sample_rate,
                    )
                    job.artifacts["click_track"] = str(click_res.out_path)
                    # Reload as overlay for the monitor mix.
                    import soundfile as _sf
                    import numpy as _np
                    arr, _ = _sf.read(str(click_path), dtype="float32",
                                      always_2d=True)
                    if arr.shape[1] == 1:
                        arr = _np.repeat(arr, 2, axis=1)
                    click_overlay = arr
                    await _emit(job, "log", "monitor",
                                _aggregate_progress(completed, 0.0),
                                f"click track: {click_res.beats} beats "
                                f"({click_res.downbeats} downbeats)")

                if opts.monitor_track and (cue_overlay is not None
                                           or click_overlay is not None):
                    mon_dir = settings.output_dir / job.id / "monitor"
                    ensure_dir(mon_dir)
                    mon_path = mon_dir / "monitor.wav"
                    await run_blocking(
                        write_monitor_track,
                        current_inst, cue_overlay, click_overlay,
                        mon_path, decode_result.sample_rate,
                    )
                    job.artifacts["monitor_track"] = str(mon_path)
                    await _emit(job, "log", "monitor",
                                _aggregate_progress(completed, 0.0),
                                "monitor.wav (instrumental + cues + click) ready")
                completed.append("monitor")
            except Exception as e:
                await _emit(job, "log", "monitor",
                            _aggregate_progress(completed, 0.0),
                            f"monitor stage failed: {e!r}")

        # --- 7a. Lyrics (faster-whisper word-level transcription) -------
        if opts.make_lyrics:
            await _emit(job, "stage", "lyrics", _aggregate_progress(completed, 0.0),
                        "Transcribing vocal lyrics (word-level)")
            try:
                lyr_dir = settings.output_dir / job.id / "lyrics"
                ensure_dir(lyr_dir)
                lyr_res = await run_blocking_timed(
                    transcribe_lyrics,
                    current_voc, lyr_dir,
                    opts.lyrics_lang or "auto",
                    opts.lyrics_domain or "",
                    opts.lyrics_model or "small",
                    True,                          # use_cuda
                    timeout=_stage_timeout("lyrics", 900.0),
                    stage="lyrics",
                )
                job.artifacts["lyrics_json"] = str(lyr_res.json_path)
                job.meta["lyrics_language"] = lyr_res.language
                job.meta["lyrics_avg_confidence"] = lyr_res.avg_confidence
                job.meta["lyrics_word_count"] = len(lyr_res.words)

                # Post-process: WhisperX forced alignment first (when
                # installed) then onset-peak nudge for the residual drift.
                try:
                    from ..pipeline.lyrics_align import (
                        forced_align_words,
                        polish_word_timestamps,
                    )
                    lang = lyr_res.language or "ko"
                    fa_stats = await run_blocking(
                        forced_align_words, lyr_res.words, current_voc,
                        lang, "cuda",
                    )
                    if fa_stats.get("aligned", 0) > 0:
                        job.meta["lyrics_forced_align"] = fa_stats
                    elif fa_stats.get("skipped"):
                        job.meta["lyrics_forced_align"] = fa_stats
                    stats = await run_blocking(
                        polish_word_timestamps, lyr_res.words, current_voc,
                    )
                    if stats.get("nudged", 0) > 0:
                        # Re-emit the lyrics.json with the nudged timings.
                        import json as _json
                        from dataclasses import asdict as _asdict
                        payload = _json.loads(
                            Path(lyr_res.json_path).read_text(encoding="utf-8")
                        )
                        payload["words"] = [_asdict(w) for w in lyr_res.words]
                        payload["alignment_polish"] = stats
                        Path(lyr_res.json_path).write_text(
                            _json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    job.meta["lyrics_alignment_polish"] = stats
                except Exception as _ap:
                    job.meta["lyrics_alignment_polish_error"] = repr(_ap)[:200]
                completed.append("lyrics")
                if not lyr_res.words:
                    # Whisper ran cleanly but the vocal stem had no detectable
                    # singing (instrumental track, very quiet backing, etc.).
                    # Mark this state explicitly so the UI can show "no vocal
                    # track" instead of looking like a transcription failure.
                    job.meta["lyrics_empty"] = True
                    await _emit(job, "log", "lyrics",
                                _aggregate_progress(completed, 0.0),
                                "보컬 트랙이 비어있어 가사 인식 결과가 없습니다 "
                                "(instrumental 곡일 수 있음).")
                else:
                    await _emit(job, "log", "lyrics",
                                _aggregate_progress(completed, 0.0),
                                f"{len(lyr_res.words)} words "
                                f"({lyr_res.language}, conf {lyr_res.avg_confidence:.2f}). "
                                f"사용자 편집 후 악보 재생성 가능.")
            except ImportError as e:
                # Most common: faster-whisper not installed. Tell the user
                # exactly how to fix it instead of a generic "skipped".
                job.meta["lyrics_error"] = str(e)
                await _emit(job, "log", "lyrics",
                            _aggregate_progress(completed, 0.0),
                            f"가사 인식 비활성: {e}. "
                            f"`uv pip install faster-whisper` 후 재변환하세요.")
            except Exception as e:
                job.meta["lyrics_error"] = repr(e)[:200]
                await _emit(job, "log", "lyrics",
                            _aggregate_progress(completed, 0.0),
                            f"가사 인식 실패: {e!r}")

        # --- 7b. Score (optional AI transcription) ---------------------
        if opts.make_score:
            await _emit(job, "stage", "score", _aggregate_progress(completed, 0.0),
                        "Transcribing to MIDI + MusicXML")
            score_dir = settings.output_dir / job.id / "score"
            ensure_dir(score_dir)

            # Pull chord_events + bpm so the score has chord symbols above the staff.
            chord_events_for_score: list[dict] | None = None
            chord_json_path = job.artifacts.get("chords_json")
            if chord_json_path:
                try:
                    import json as _json
                    data = _json.loads(Path(chord_json_path).read_text(encoding="utf-8"))
                    chord_events_for_score = data.get("events") or None
                except Exception:
                    chord_events_for_score = None
            score_bpm = float(job.meta.get("bpm") or 0.0)

            # Load lyrics events for lead-sheet style.
            lyrics_words_for_score: list[dict] | None = None
            lyrics_json_path = job.artifacts.get("lyrics_json")
            if lyrics_json_path:
                try:
                    words = load_lyrics_json(Path(lyrics_json_path))
                    lyrics_words_for_score = [
                        {"word": w.word, "start_sec": w.start_sec,
                         "end_sec": w.end_sec, "confidence": w.confidence,
                         "verse": 1}
                        for w in words
                    ]
                except Exception:
                    lyrics_words_for_score = None

            # AUX cues (if the user already authored some) — attach to the vocals score.
            aux_cues_for_score: list[dict] | None = None
            aux_json_path = job.artifacts.get("aux_cues_json")
            if aux_json_path:
                try:
                    import json as _json
                    aux_cues_for_score = _json.loads(
                        Path(aux_json_path).read_text(encoding="utf-8")
                    ).get("cues") or None
                except Exception:
                    aux_cues_for_score = None

            # Section markers (intro/verse/chorus/bridge/…) — attach to
            # every score so drum/TAB/SATB readers still see the form.
            # Also pull the downbeat grid so the per-measure timemap rides
            # on the actual audio downbeats instead of a constant BPM.
            sections_for_score: list[dict] | None = None
            downbeats_for_score: list[float] | None = None
            sections_json_path = job.artifacts.get("sections_json")
            if sections_json_path:
                try:
                    import json as _json
                    _sj = _json.loads(
                        Path(sections_json_path).read_text(encoding="utf-8")
                    )
                    sections_for_score = _sj.get("sections") or None
                    db = _sj.get("downbeats_sec") or []
                    if isinstance(db, list) and len(db) >= 2:
                        downbeats_for_score = [float(x) for x in db]
                except Exception:
                    sections_for_score = None
                    downbeats_for_score = None
            # Map each requested score stem to an audio path we already have.
            stem_to_audio: dict[str, "Path"] = {}
            if "vocals" in opts.score_stems:
                stem_to_audio["vocals"] = current_voc
            if "instrumental" in opts.score_stems:
                stem_to_audio["instrumental"] = current_inst
            # 6-stem mode: pull individual stems from artifacts.
            for stem_name in ("piano", "guitar", "bass", "other"):
                if stem_name in opts.score_stems:
                    p = job.artifacts.get(f"stem_{stem_name}")
                    if p:
                        from pathlib import Path as _P
                        stem_to_audio[stem_name] = _P(p)

            # Record which transcription backend will run for each stem so
            # the user can see whether they got SOTA accuracy or a fallback.
            try:
                from importlib import util as _iu
                _backend_for_stem = {
                    "piano": ("piano_transcription_inference",
                              "polyphonic ~80-85% F1"),
                    "bass":  ("crepe", "low-freq pitch ~90-92% F1"),
                    "drums": ("omnizart", "drum kit ~88% F1"),
                }
                for _sn in stem_to_audio.keys():
                    pref = _backend_for_stem.get(_sn)
                    if pref and _iu.find_spec(pref[0].replace("-", "_")) is not None:
                        record_backend(job, f"transcribe_{_sn}", pref[0],
                                       level="sota", note=pref[1])
                    elif _sn == "drums":
                        # Drums has no Python-3.11 SOTA path — heuristic only.
                        record_backend(job, "transcribe_drums",
                                       "heuristic_spectral",
                                       level="heuristic",
                                       note="onset+centroid decision tree ~70-75% F1")
                        record_fallback(job, "transcribe_drums", "omnizart",
                                        reason="Python 3.11 incompatible")
                    else:
                        record_backend(job, f"transcribe_{_sn}", "basic_pitch",
                                       level="primary",
                                       note="80-85% F1 (general)")
                        if pref:
                            record_fallback(job, f"transcribe_{_sn}",
                                            pref[0],
                                            reason="package not installed")
            except Exception as e:
                log.debug("orchestrator.score: transcribe backend-report skipped (%r)", e)

            for stem_name, audio_path in stem_to_audio.items():
                try:
                    tr = await run_blocking_timed(
                        transcribe, audio_path, score_dir, stem_name,
                        timeout=_stage_timeout("transcribe", 600.0),
                        stage=f"transcribe:{stem_name}",
                    )
                    # Only attach lyrics to the vocals score — drum/bass/piano
                    # scores don't carry words.
                    lyr_for_this = (
                        lyrics_words_for_score if stem_name == "vocals" else None
                    )
                    # Per-stem notation override; falls back to the global
                    # `score_style`, then to NOTATION_BY_STEM auto-pick.
                    per_stem_style = (
                        opts.score_styles_per_stem.get(stem_name, "")
                        or opts.score_style
                        or ""
                    )
                    # Only attach AUX cues to the vocals score (lead sheet is where
                    # patch hints live in the standard practice chart).
                    aux_for_this = (
                        aux_cues_for_score if stem_name == "vocals" else None
                    )
                    sc = await run_blocking(
                        lambda: build_score(
                            tr.midi_path, score_dir,
                            stem_kind=stem_name,
                            title=f"{stem_name} - {job.id}",
                            write_svg=True,
                            write_pdf=True,
                            chord_events=chord_events_for_score,
                            bpm=score_bpm,
                            lyrics_words=lyr_for_this,
                            notation_style=per_stem_style,
                            aux_cues=aux_for_this,
                            sections=sections_for_score,
                            time_signature=job.meta.get("time_signature") or None,
                            downbeats_sec=downbeats_for_score,
                            key_name=job.meta.get("key_name") or None,
                        ),
                    )
                    job.artifacts[f"score_{stem_name}_midi"] = str(tr.midi_path)
                    job.artifacts[f"score_{stem_name}_musicxml"] = str(sc.musicxml_path)
                    for i, svg_p in enumerate(sc.svg_paths, start=1):
                        job.artifacts[f"score_{stem_name}_svg_p{i}"] = str(svg_p)
                    if sc.pdf_path:
                        job.artifacts[f"score_{stem_name}_pdf"] = str(sc.pdf_path)
                    if sc.timemap_path:
                        job.artifacts[f"score_{stem_name}_timemap"] = str(sc.timemap_path)
                    job.meta[f"score_{stem_name}_pages"] = sc.pages
                    job.meta[f"score_{stem_name}_measures"] = sc.measures
                    # Melody pitch range (5th–95th percentile) — drives the
                    # frontend's audience-range hint on KeyControl.
                    if tr.low_midi is not None and tr.high_midi is not None:
                        job.meta[f"{stem_name}_low_midi"] = tr.low_midi
                        job.meta[f"{stem_name}_high_midi"] = tr.high_midi
                    await _emit(job, "log", "score",
                                _aggregate_progress(completed, 0.0),
                                f"{stem_name}: {tr.note_count} notes, "
                                f"{sc.measures} measures, {sc.pages} pages")
                except Exception as e:
                    await _emit(job, "log", "score",
                                _aggregate_progress(completed, 0.0),
                                f"{stem_name}: transcription failed ({e!r})")
            completed.append("score")

        # --- 8. Encode --------------------------------------------------
        await _emit(job, "stage", "encode", _aggregate_progress(completed, 0.0),
                    f"Encoding {opts.format.upper()} @ {opts.sample_rate}Hz / {opts.bit_depth}-bit")
        out_dir = settings.output_dir / job.id
        ensure_dir(out_dir)
        enc_inst = await run_blocking(
            encode_fn, current_inst, out_dir / "instrumental",
            opts.format, opts.sample_rate, opts.bit_depth,
        )
        enc_voc = await run_blocking(
            encode_fn, current_voc, out_dir / "vocals",
            opts.format, opts.sample_rate, opts.bit_depth,
        )
        job.artifacts["instrumental_final"] = str(enc_inst.out_path)
        job.artifacts["vocals_final"] = str(enc_voc.out_path)
        completed.append("encode")

        # --- Storage mirror (Phase B) -----------------------------------
        # When STORAGE_BACKEND is non-local, upload each artifact and
        # store the remote URL alongside the path. Local stays a no-op
        # so Phase A behaviour is identical.
        try:
            await _mirror_artifacts_to_storage(job)
        except Exception as e:
            # Mirroring is best-effort; failures don't fail the job.
            await _emit(job, "log", "storage",
                        _aggregate_progress(completed, 0.0),
                        f"storage mirror skipped: {e!r}")

        # --- Backend summary (what actually ran vs install hints) -------
        try:
            summary = freeze_backend_summary(job)
            warnings = build_dependency_warnings(job)
            if warnings:
                # Surface a single combined log line — the UI reads
                # backend_summary.install_hints for the full list.
                missing_list = ", ".join(w["missing"] for w in warnings[:4])
                await _emit(job, "log", "encode",
                            _aggregate_progress(completed, 0.0),
                            f"정확도 향상 권장 패키지: {missing_list} "
                            f"({len(warnings)} 항목) — backend_summary 참조")
            job.meta["backend_summary"] = summary
        except Exception as _e:
            job.meta["backend_summary_error"] = repr(_e)[:200]

        # --- Done -------------------------------------------------------
        job.status = "done"
        job.progress = 1.0
        job.stage = "done"
        job.finished_at = time.time()
        await _emit(job, "done", "done", 1.0, "Job completed",
                    instrumental=str(enc_inst.out_path),
                    vocals=str(enc_voc.out_path))

    except asyncio.CancelledError:
        job.status = "cancelled"
        job.finished_at = time.time()
        await _emit(job, "error", job.stage or "?", job.progress, "Cancelled")
        raise
    except Exception as e:
        job.status = "error"
        job.error = repr(e)
        job.finished_at = time.time()
        await _emit(job, "error", job.stage or "?", job.progress, f"FAILED: {e!r}")
        try:
            from ..core.observability import capture_exception
            capture_exception(e, job_id=job.id, stage=job.stage)
        except Exception:
            pass
    finally:
        # Persist the terminal job state so it survives a server restart.
        try:
            from ..core.jobs import registry as _registry
            _registry.persist(job)
        except Exception:
            pass
        # Clean up intermediate work files (decode master, per-model raw
        # stems) regardless of success/failure — these are large and never
        # served to the user. The final encoded outputs live in output_dir
        # and are preserved. Controlled by RECHORD_KEEP_WORKDIR=1 for
        # debugging a failed job.
        try:
            import os as _os
            import shutil as _shutil
            if _os.environ.get("RECHORD_KEEP_WORKDIR", "").strip() != "1":
                wd = settings.work_dir / job.id
                if wd.exists():
                    _shutil.rmtree(wd, ignore_errors=True)
                # Per-model raw separator scratch under stems_dir that the
                # ensemble already consumed — keep the final ensemble/polish
                # dirs (they may back a stems-mode download) but drop the
                # transient post-pass scratch.
                for scratch in (f"{job.id}_post", f"{job.id}_bv"):
                    sp = settings.stems_dir / scratch
                    if sp.exists():
                        _shutil.rmtree(sp, ignore_errors=True)
        except Exception:
            pass
        # Always release GPU memory + run gc so the next job starts clean.
        try:
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except Exception:
                pass
        except Exception:
            pass
