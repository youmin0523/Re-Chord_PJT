# SOTA Model Activation Guide

What is installed vs what needs extra work, on this Windows + Python 3.11
+ CUDA 12.8 environment.

## ✅ Active on this machine (verified)

| Model | Used by | Source |
|---|---|---|
| **CREPE** 0.0.16 | `transcribe_backends/jdc_pe.py` (bass), `autotune.py`, `performance.py` (grading) | pip, MIT |
| **CREMA** | `chord_crema.py` | pip, Apache-2.0 |
| **pyworld** 0.3.5 | `transform_world.py` (large vocal pitch shift) | pip, MIT |
| **piano_transcription_inference** 0.0.6 | `transcribe_backends/mt3.py` (Tier 1 piano) | pip, Apache-2.0 |
| **laion-clap** 1.1.7 | `aux_classifier.py` (AUX patch matching) | pip, CC BY-NC 4.0 |
| **Ollama llama3.2:1b** | `chord_llm.py`, `sections_advanced.py` (LLM refinement) | local binary at `bin/ollama/` |
| **fluidsynth** 2.5.4 | `scripts/sources/render_sf2.py` (AUX reference DB build) | `bin/fluidsynth.exe` |
| **rubberband** 3.3.0 (R3) | `transform.py` | `bin/rubberband-r3.exe` |
| **fpcalc** 1.5.1 (chromaprint) | `core/ops.py` (duplicate detection) | `bin/fpcalc.exe` |
| **7 SOTA Roformer weights** (~6 GB) | `separate.py` Pro mode ensemble | HF Hub via `fetch_sota_separator.py` |

## ⚠️ Not installed on this machine — works on a different env

### `omnizart` (alternative piano polyphonic / drum)

Cannot install on Python 3.11. Its transitive `spleeter` depends on
`llvmlite` which has wheels for **Python ≤ 3.10 only**.

To activate:
```powershell
# Create a separate Python 3.10 venv just for omnizart inference:
uv venv --python 3.10 .venv-omnizart
.venv-omnizart\Scripts\Activate.ps1
uv pip install omnizart
```

Then run omnizart out-of-process via subprocess. Our dispatcher in
`transcribe_backends/mt3.py` falls back to PTI (`piano_transcription_inference`)
which gives comparable accuracy (~80-85% F1) on Python 3.11, so omnizart
is **not blocking** any user-facing functionality.

### `transkun` (alternative piano polyphonic)

Requires Microsoft Visual C++ Build Tools to compile the `ncls` native
extension on Windows. To activate:

1. Install [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
   with the "Desktop development with C++" workload.
2. Restart shell so `cl.exe` is on PATH.
3. `uv pip install transkun`

Again — not blocking. PTI fills the same slot.

## 🚫 Not in this build of ffmpeg

### DSD encoding (`dsd_lsbf_planar`)

The bundled gyan.dev ffmpeg 8.1 doesn't include the DSD encoder. Our
`pipeline/spatial.py::dsd_supported()` detects this upfront and the
`/jobs/{id}/dsd` endpoint returns 503 with a clear message instead of
500.

To enable DSD output:
- Replace with [BtbN nightly](https://github.com/BtbN/FFmpeg-Builds/releases)
  which is compiled with `--enable-encoder=dsd_lsbf_planar`, OR
- Compile your own ffmpeg with that flag.

## 🎤 Backing-vocal vs lead-vocal separation (not active)

Worship and pop frequently want **lead vocal isolated from backing vocals**
(BGV / 코러스) — different than the standard "vocals vs instrumental" split
that `htdemucs_6s` and our BS-Roformer ensemble already deliver.

Current state in our stack:
- `htdemucs_6s` and the BS-Roformer weights ship a single `vocals` stem.
  Lead and backing harmonies come out **mixed together**.
- A separate "lead vs BGV" classifier would have to operate on that single
  vocals stem, splitting it into two outputs.

Research options surveyed (none currently activated):

| Approach | Status | Why it isn't on by default |
|---|---|---|
| **Mel-Roformer "Karaoke" (anvuew)** weights — trained to split lead from BGV | available on HF Hub | quality is uneven on Korean worship/CCM mixes; needs A/B testing first |
| **MMD-extracted residual** (subtract the centred lead from full vocals → harmonies) | trivial to implement | only works when the lead really is centred; modern productions wide-pan the lead |
| **VocalSplit / VocalRemover-BGV branch** (community fork) | unmaintained | abandoned in 2023; weights work but no warranty |
| **Hand-trained student model** on isolated CCLI multitracks | hypothetically best | requires licensed multitrack data we don't have rights to use |

Decision: leave the feature **unimplemented** in Phase A. When a user
asks "can I isolate just the BGV", direct them to the existing 6-stem
output and explain that lead/BGV is a research-grade problem. Re-evaluate
in Phase B when (a) we have a representative test corpus and (b) the
Roformer karaoke weights have matured.

UI surface today: the Stems mixer can mute the unified `vocals` channel,
which is the closest band-friendly approximation. Document this on the
Stems-mode help tooltip rather than promising a feature we can't ship.

## 📦 Phase B SaaS-only

| Package | Activated by | Notes |
|---|---|---|
| `celery[redis]` + `redis-py` | `CELERY_BROKER_URL` env | docker-compose includes a redis service |
| `sqlalchemy[asyncio]` + `asyncpg` + `alembic` | `DATABASE_URL` env | `uv pip install -e ".[saas]"` |
| `boto3` | `STORAGE_BACKEND=r2` or `s3` env | `uv pip install boto3` |
| `python-jose` | `AUTH_PROVIDER=clerk` or `supabase` env | for JWT verification |

Phase A devs never need any of these.
