# scripts/

Operational scripts grouped by purpose. Every script can be run from the
repository root with `uv run python scripts/<name>.py` (or `.ps1` for the
Windows-specific ones). Many of them expect the backend `.venv` to be
ready — run `uv sync --extra sota_models --extra aux_classifier --extra
monitoring` first.

> Heads-up: most measurement scripts download datasets (MUSDB18, RWC,
> internal worship corpus) on first run. Set `RECHORD_DATA_DIR` to point
> the cache somewhere with enough free space (≥30 GB).

---

## Diagnostics & onboarding

| Script | What it does | When to run |
|--------|--------------|-------------|
| `doctor.py` | Probes Python version, ffmpeg, GPU/CUDA, model presence, write permissions. Pretty table output. | First-day setup, after any `uv sync`, before a release. |
| `verify_session.py` | Smoke-tests a fresh API session end-to-end (create job → poll → download artifact). | When a new env is provisioned, before pointing real users at it. |

---

## Model installation

| Script | What it does | When to run |
|--------|--------------|-------------|
| `install_models.py` | Idempotent downloader for the bundled separator + transcription weights. Skips already-present files. | First-day setup or after wiping `data/models`. |
| `install_sota.ps1` | Windows-only PowerShell installer for `crepe`/`madmom` (the deps that need `--no-build-isolation` + MSVC). | Once per Windows dev box. |
| `fetch_sota_separator.py` | Pulls the SOTA Roformer / MDX checkpoints (~3-4 GB total) from HuggingFace. | Before any commercial deploy — the gate refuses fallbacks. |
| `probe_separator_hub.py` | Lists what's in the HF separator hub and what's already downloaded. | Debugging "model X missing" reports. |

---

## Accuracy gates (run on every release)

| Script | Measures | Typical runtime |
|--------|----------|-----------------|
| `run_accuracy_suite.py` | Bundles the synth + real-world measurements below. CI uses the synth-only path; this is the local "everything green" check. | ~25 min on RTX 5070. |
| `measure_accuracy.py` | Synth-signal sanity (key/BPM/onsets on programmed fixtures). | ~2 min. |
| `measure_real_accuracy.py` / `measure_real_accuracy_v4.py` | URL-grounded measurement on the published corpus. v4 is the current one. | ~12 min (depends on network). |
| `measure_sdr_musdb.py` | Separation SDR on MUSDB18 (7s windows). Baseline source for the README's "15.06 / 10.66 dB" claim. | ~8 min on RTX 5070. |
| `measure_chord_accuracy.py` | Chord-recognition F1 on internal corpus, slash-chord aware. | ~3 min. |
| `measure_slash_chord_accuracy.py` | Slash bass cross-check against the dedicated fixture set. | ~1 min. |
| `measure_section_accuracy.py` | Section boundary IoU on K-Pop dataset. | ~4 min. |
| `measure_lyrics_align_iou.py` | Word-level lyric alignment IoU on synth lyrics. | ~2 min. |
| `measure_transcribe_f1.py` | Stem-by-stem transcription F1 (basic_pitch + drum heuristics). | ~6 min. |
| `measure_drums_f1.py` | Drum-specific F1 (kick/snare/hihat) with the GM mapping check. | ~2 min. |
| `measure_autotune_accuracy.py` | Pitch-correction shift accuracy on programmed off-pitch fixtures. | ~3 min. |
| `measure_tension_detection.py` | Tension-chord detection (9/11/13 + altered) on synth corpus. | ~1 min. |
| `measure_transform_accuracy.py` | Key/tempo transform fidelity (cents drift, transient blur). | ~2 min. |
| `measure_aux_accuracy.py` | AUX patch classifier on the CLAP reference DB. Phase 1 baseline = 98.3%. | ~3 min. |
| `remeasure_separation.py` | Re-runs separation measurements with current model weights and writes back to `tests/fixtures/accuracy_thresholds.json` (with `--write`). | After upgrading a separator model. |

`tests/fixtures/accuracy_thresholds.json` is the gate input — keep it in
sync. `pytest tests/test_accuracy_thresholds.py` fails if any metric
drops below the documented `min`.

---

## Dataset builders (one-time)

| Script | Output | Notes |
|--------|--------|-------|
| `build_aux_reference_db.py` | CLAP-embedded patch reference DB for AUX classification. Reads from `data/aux/raw`. | Re-run after adding new patches to the corpus. |
| `build_kpop_section_dataset.py` | Section-labelled K-Pop snippets used by `measure_section_accuracy`. | Run once per fresh download of the raw audio. |
| `build_synth_4stem_corpus.py` | Programmed 4-stem fixtures (drums/bass/piano/vocals) with known ground truth. Powers the synth accuracy gate. | Re-run after changing the fixture spec. |
| `fetch_research_datasets.py` | Pulls MUSDB18, RWC, etc. into the configured data dir. | Once per fresh machine; ~20 GB. |
| `autofill_ground_truth.py` | Fills missing key/BPM ground truth on the worship corpus using a confidence threshold. Manual review required after running. | Quarterly, when the worship corpus grows. |
| `enrich_translations_via_youtube.py` | Pulls auto-captions for the worship corpus to seed lyric alignment ground truth. | Manual; rate-limited. |

---

## What the scripts are *not*

* They are **not** part of the user-facing API surface. Nothing in
  `scripts/` is callable from the frontend.
* The `measure_*` scripts read raw audio from `data/` — they will not
  download user uploads, and they do not depend on a running backend
  (except `measure_real_accuracy_v4.py` which uses the live `/jobs`
  endpoint).
* Long-running scripts (`run_accuracy_suite.py`, the SDR measurer)
  are CPU/GPU heavy. Don't run them concurrently with `uvicorn` on the
  same machine unless you've over-provisioned GPU memory.

---

## Common workflows

**"Why is my measurement dropping?"** Run `doctor.py` → check
`/ops/install_hints` → re-run the specific `measure_*` script with
`--verbose` to see fixture-by-fixture deltas.

**"I'm shipping a new release."** `run_accuracy_suite.py` → if green,
`pytest tests/test_accuracy_thresholds.py` → tag.

**"I added a separator model and want to compare."** Update the model
registry → `fetch_sota_separator.py` → `remeasure_separation.py --write`
→ inspect the new thresholds → commit `tests/fixtures/accuracy_thresholds.json`.
