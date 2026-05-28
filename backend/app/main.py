"""FastAPI application entry point."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .api import billing as billing_api
from .api import chat as chat_api
from .api import consents as consents_api
from .api import feedback as feedback_api
from .api import formats as formats_api
from .api import jobs as jobs_api
from .api import notes as notes_api
from .api import performance as performance_api
from .api import setlists as setlists_api
from .api import uploads as uploads_api
from .config import settings
from .core.observability import setup_logging
from .core.paths import ensure_dir
from .core.queue import get_queue, init_queue
from .workers.orchestrator import run_job

setup_logging()


async def _scheduled_prewarm_loop():
    """Run /ops/prewarm logic on a schedule so the first job after a long
    idle period doesn't eat the cold-start cost.

    Cadence is controlled by env:
       RECHORD_PREWARM_AT_BOOT=1     prewarm immediately at startup (default: 1)
       RECHORD_PREWARM_EVERY_MIN=N   re-warm every N minutes (default: 0 = off)

    All-or-nothing failure is fine — each warmer is independent and the
    next tick retries. Cancellation propagates through asyncio.CancelledError.
    """
    import asyncio as _asyncio
    import os as _os
    boot = (_os.environ.get("RECHORD_PREWARM_AT_BOOT", "1").strip() == "1")
    every_min_str = _os.environ.get("RECHORD_PREWARM_EVERY_MIN", "0").strip()
    try:
        every_min = max(0, int(every_min_str))
    except ValueError:
        every_min = 0

    async def _warm():
        # Re-use the route handler so we have a single source of truth.
        try:
            await ops_prewarm(None)
        except Exception:
            pass

    if boot:
        _asyncio.create_task(_warm())
    if every_min <= 0:
        return
    try:
        while True:
            await _asyncio.sleep(every_min * 60)
            await _warm()
    except _asyncio.CancelledError:
        return


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    for d in (settings.uploads_dir, settings.work_dir, settings.stems_dir,
              settings.output_dir, settings.models_dir, settings.logs_dir):
        ensure_dir(d)
    # Restore finished jobs from disk so a restart doesn't wipe history.
    try:
        from .core.jobs import registry as _registry
        n = _registry.restore_from_disk()
        if n:
            import logging
            logging.getLogger("rechord").info("restored %d jobs from disk", n)
    except Exception:
        pass
    queue = init_queue(run_job, concurrency=settings.max_concurrent_jobs)
    await queue.start()
    prewarm_task = _asyncio.create_task(_scheduled_prewarm_loop())
    try:
        yield
    finally:
        prewarm_task.cancel()
        try:
            await prewarm_task
        except _asyncio.CancelledError:
            pass
        await get_queue().stop()


app = FastAPI(
    title="Re:Chord API",
    version="0.3.0",
    summary="AR → MR conversion + key/tempo/chord/section analysis + worship & live tools.",
    description=(
        "Re:Chord backend. Endpoints are grouped by tag below — start with **jobs** "
        "(create + monitor a conversion), then explore the **post-process** tools "
        "(mastering, autotune, worship, surround/DSD) on the resulting artifacts.\n\n"
        "**Phase A** (current) runs entirely on the local machine; the in-process "
        "registry is the source of truth. **Phase B** (SaaS) will swap to "
        "PostgreSQL — see `backend/app/db/`.\n\n"
        "WebSocket progress stream: `ws://host/jobs/{id}/progress`."
    ),
    contact={"name": "Re:Chord", "url": "https://github.com/"},
    license_info={"name": "Personal project"},
    openapi_tags=[
        {"name": "jobs",     "description": "Create + monitor conversion jobs. Core REST + WebSocket."},
        {"name": "uploads",  "description": "Upload local audio/video files for processing."},
        {"name": "formats",  "description": "Enumerate supported encode formats / sample-rates / bit-depths."},
        {"name": "setlists", "description": "Group jobs into named setlists (worship sets, concerts)."},
        {"name": "notes",    "description": "Per-job rehearsal annotations (note / cue / warning / skip)."},
        {"name": "post-process",
         "description": "Mastering (LUFS+EQ), Auto-tune, Worship (pedal-tone + segue), "
                        "Binaural, 5.1 surround, DSD, AUX cue auto-suggest."},
        {"name": "chat",
         "description": "OpenAI worship/music co-pilot — song id, lead sheets, "
                        "Korean translations, file/URL analysis, voice input, tool calling."},
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_api.router)
app.include_router(uploads_api.router)
app.include_router(formats_api.router)
app.include_router(setlists_api.router)
app.include_router(notes_api.router)
app.include_router(performance_api.router)
app.include_router(billing_api.router)
app.include_router(chat_api.router)
app.include_router(consents_api.router)
app.include_router(feedback_api.router)


@app.get("/ops/install_hints", tags=["ops"])
async def ops_install_hints() -> dict:
    """Report which optional SOTA packages are still missing locally.

    Returns the same payload the orchestrator's freeze_backend_summary()
    embeds in job.meta.backend_summary.install_hints, but available *before*
    a job runs so the UI onboarding card can guide the user.

    Response: {"missing": [...], "all_installed": bool, "by_stage": {...}}
    """
    from .pipeline.backend_report import _SOTA_DEPS, _is_installed
    out: list[dict] = []
    by_stage: dict[str, list[dict]] = {}
    for stage, deps in _SOTA_DEPS.items():
        for d in deps:
            mod = d.missing.replace("-", "_")
            if mod == "ollama":
                continue
            installed = _is_installed(mod)
            entry = {
                "stage": stage,
                "package": d.missing,
                "install": d.install_cmd,
                "accuracy_impact": d.impact,
                "installed": installed,
            }
            by_stage.setdefault(stage, []).append(entry)
            if not installed:
                out.append(entry)
    return {
        "missing": out,
        "all_installed": len(out) == 0,
        "by_stage": by_stage,
        "doc_url": "https://github.com/anthropics/claude-code/issues",
    }


@app.get("/health")
async def health() -> dict:
    """Liveness + tool-version probe."""
    from .core.ops import probe_tool_versions
    tools = probe_tool_versions()
    return {
        "status": "ok",
        "version": "0.3.0",
        "tools": [
            {"name": t.name, "version": t.version, "available": t.available}
            for t in tools
        ],
    }


@app.get("/ops/disk")
async def ops_disk() -> dict:
    """Free disk space + the budget our pipeline expects."""
    from .core.ops import disk_preflight
    from .config import settings
    out: dict[str, dict] = {}
    for mode in ("quick_mr", "karaoke", "stems", "pro"):
        chk = disk_preflight(settings.data_dir, mode=mode)
        out[mode] = {
            "free_gb": round(chk.free_gb, 2),
            "required_gb": chk.required_gb,
            "ok": chk.ok,
        }
    return {"data_dir": str(settings.data_dir), "by_mode": out}


@app.post("/ops/cleanup")
async def ops_cleanup(max_age_hours: float = 72.0, dry_run: bool = True) -> dict:
    """Sweep old artifacts from the work / stems / output dirs."""
    from .core.ops import cleanup_old_artifacts
    from .config import settings
    res = cleanup_old_artifacts(
        [settings.work_dir, settings.stems_dir, settings.output_dir],
        max_age_hours=max_age_hours, dry_run=dry_run,
    )
    return {
        "dry_run": dry_run,
        "files_removed": res.files_removed,
        "bytes_freed": res.bytes_freed,
        "sample": res.paths[:10],
    }


@app.post("/ops/prewarm")
async def ops_prewarm(models: list[str] | None = None) -> dict:
    """Pre-load heavy ML models so the first user-facing call doesn't pay
    the cold-start cost (CLAP ~2 GB, PTI ~150 MB, Whisper-turbo, …).

    Default: warm all that are available. Pass ``models=["clap"]`` to
    warm just one. Each warmer is independent — failure of one doesn't
    abort the others. Returns a per-model status table.
    """
    import asyncio as _asyncio
    target = (set(models) if models
              else {"clap", "pti", "whisper", "crepe", "madmom"})
    result: dict[str, dict] = {}

    def warm_clap():
        from .pipeline.aux_classifier import _get_clap
        _get_clap()
        return {"ok": True}

    def warm_pti():
        # Triggers PTI's checkpoint download/load.
        from piano_transcription_inference import PianoTranscription  # type: ignore
        PianoTranscription(device="cpu")  # lazy; switches to cuda when used
        return {"ok": True}

    def warm_whisper():
        # Default model is large-v3-turbo (~1.6 GB) — load once so the
        # first lyrics request doesn't pay the conversion cost.
        from faster_whisper import WhisperModel  # type: ignore
        from .pipeline.lyrics import _model_cache_dir
        WhisperModel("large-v3-turbo", device="cpu", compute_type="int8",
                     download_root=str(_model_cache_dir()))
        return {"ok": True}

    def warm_crepe():
        import crepe  # type: ignore  # noqa: F401
        return {"ok": True}

    def warm_madmom():
        # Pulls madmom's CNN key + RNN beat + DBN downbeat pretrained
        # checkpoints (bundled with the wheel, but pyo3-style lazy unpack).
        from . import pipeline  # numpy_compat shim
        _ = pipeline  # silence unused-import lint
        from madmom.features.key import CNNKeyRecognitionProcessor  # type: ignore
        from madmom.features.beats import RNNBeatProcessor  # type: ignore
        from madmom.features.downbeats import RNNDownBeatProcessor  # type: ignore
        CNNKeyRecognitionProcessor()
        RNNBeatProcessor()
        RNNDownBeatProcessor()
        return {"ok": True}

    warmers = {"clap": warm_clap, "pti": warm_pti,
               "whisper": warm_whisper, "crepe": warm_crepe,
               "madmom": warm_madmom}
    loop = _asyncio.get_running_loop()
    for name in target:
        fn = warmers.get(name)
        if not fn:
            result[name] = {"ok": False, "error": "unknown model"}
            continue
        try:
            await loop.run_in_executor(None, fn)
            result[name] = {"ok": True}
        except Exception as e:
            result[name] = {"ok": False, "error": repr(e)[-200:]}
    return {"warmed": result, "took_models": list(target)}
