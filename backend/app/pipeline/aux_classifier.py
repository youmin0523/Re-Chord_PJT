"""AUX/second-keyboard patch auto-classifier.

Given the instrumental wav and a beat grid (from sections.py), chunk the
audio per measure and predict an AUX patch category (organ, pad, synth_lead,
string, brass, bell, piano, epiano, choir, guitar_atmos, fx, silent) using
LAION-CLAP embeddings.

Two prediction modes, exposed via :func:`classify_measures`:

* **Reference-DB mode** (preferred when ``data/reference_db/aux/`` exists):
  cosine top-k against a pre-built embedding bank of legal sources
  (NSynth, Arachno SF2, Polyphone CC sf2, Surge XT / Dexed / Vital renders).
  Each reference vector carries a category label; we vote on the top-k
  neighbours weighted by similarity.

* **Zero-shot CLAP-text mode** (fallback when no DB present): cosine against
  CLAP text embeddings of the 12 category names + descriptors. Works without
  a reference build at the cost of ~10pp lower accuracy.

The output is a list of :class:`AuxCue` candidates already merged into
contiguous ranges, ready for :func:`pipeline.aux_cues.write_aux_cues`.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# Category vocabulary mirrors aux_cues.PATCH_LABEL_KO (minus "silent"/"custom").
AUX_CATEGORIES: tuple[str, ...] = (
    "organ", "pad", "synth_lead", "string", "brass", "bell",
    "piano", "epiano", "choir", "guitar_atmos", "fx",
)

# Text prompts used for zero-shot mode. Multiple phrasings per category
# give CLAP more surface to match against; we mean-pool the prompts.
ZERO_SHOT_PROMPTS: dict[str, list[str]] = {
    "organ":        ["hammond organ", "B3 organ with leslie", "church pipe organ"],
    "pad":          ["warm synth pad", "atmospheric ambient pad", "slow synth string pad"],
    "synth_lead":   ["synth lead melody", "saw lead synthesizer", "bright analog synth lead"],
    "string":       ["orchestral strings ensemble", "violin section", "string quartet sustained"],
    "brass":        ["brass section", "trumpet and trombone ensemble", "horn section"],
    "bell":         ["bell tone", "tubular bells", "music box bells"],
    "piano":        ["acoustic grand piano", "upright piano", "concert piano"],
    "epiano":       ["fender rhodes electric piano", "wurlitzer electric piano", "DX7 electric piano"],
    "choir":        ["choir aah voices", "vocal choir ensemble", "church choir"],
    "guitar_atmos": ["clean electric guitar atmosphere", "ambient guitar swell", "delayed reverberant guitar pad"],
    "fx":           ["sound effect texture", "atmospheric sweep fx", "synth effect transition"],
}

# Confidence cliffs — below this the classifier emits 'silent'/skips.
MIN_RMS_DBFS = -45.0          # below this the chunk is treated as silent
MIN_CONFIDENCE_FOR_CUE = 0.18  # below: don't bother, leave the cue out


@dataclass
class AuxCandidate:
    """One measure-level prediction before contiguous-range merging."""
    measure: int                   # 1-indexed
    start_sec: float
    end_sec: float
    patch: str                     # AUX_CATEGORIES + "silent"
    confidence: float              # 0..1 (top similarity * margin)
    runner_up: str = ""            # second-best label, for UI hints


@dataclass
class AuxAutoResult:
    cues: list[dict]               # contiguous-range cues (start_measure, end_measure, patch, note)
    candidates: list[AuxCandidate]  # raw per-measure predictions
    mode: str                      # "reference_db" | "zero_shot"
    db_size: int                   # number of reference vectors used (0 in zero-shot)


# ── reference DB I/O ─────────────────────────────────────────────────────────

@dataclass
class ReferenceDB:
    embeddings: np.ndarray         # (N, 512) float32, L2-normalised
    categories: list[str]          # N labels, one of AUX_CATEGORIES
    sources: list[str]             # N source tags ("nsynth", "arachno", ...)
    instruments: list[str]         # N raw instrument names (for debugging)


def load_reference_db(db_dir: Path) -> ReferenceDB | None:
    """Load embeddings + metadata from ``data/reference_db/aux/``.

    Returns ``None`` if the DB hasn't been built yet (no embeddings.npy).
    """
    db_dir = Path(db_dir)
    emb_path = db_dir / "embeddings.npy"
    meta_path = db_dir / "metadata.json"
    if not emb_path.exists() or not meta_path.exists():
        return None
    emb = np.load(str(emb_path))
    if emb.dtype != np.float32:
        emb = emb.astype(np.float32, copy=False)
    # Re-normalise defensively — the build script writes normalised vectors but
    # float16 → float32 round-trips can drift slightly.
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb = emb / norms

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cats = list(meta.get("categories") or [])
    srcs = list(meta.get("sources") or [])
    insts = list(meta.get("instruments") or [""] * len(cats))
    if len(cats) != emb.shape[0] or len(srcs) != emb.shape[0]:
        raise ValueError(
            f"reference DB metadata mismatch: emb={emb.shape[0]}, "
            f"cats={len(cats)}, sources={len(srcs)}"
        )
    return ReferenceDB(emb, cats, srcs, insts)


# ── CLAP loader (lazy singleton — model is ~2GB) ─────────────────────────────

_CLAP_MODEL = None


def _get_clap():
    """Lazy-load LAION-CLAP. Importing laion_clap pulls torch+transformers.

    We use the default ``amodel='HTSAT-tiny'`` because that matches the
    pretrained ``630k-audioset-best.pt`` checkpoint that ``load_ckpt()``
    downloads. Specifying ``HTSAT-base`` would cause state-dict key
    mismatches and 100% embedding failure.
    """
    global _CLAP_MODEL
    if _CLAP_MODEL is not None:
        return _CLAP_MODEL
    try:
        import laion_clap  # type: ignore
        import torch  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "laion-clap not installed. Run: uv pip install laion-clap"
        ) from e
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = laion_clap.CLAP_Module(enable_fusion=False, device=device)
        # Load default checkpoint from HF. On first call this downloads ~2GB.
        model.load_ckpt()
    _CLAP_MODEL = model
    return model


def _embed_audio(audio: np.ndarray, sr: int) -> np.ndarray:
    """Compute one CLAP audio embedding for a mono (or stereo→mono) chunk.

    Returns an L2-normalised (512,) float32 vector. Internally CLAP wants
    48 kHz mono float32.
    """
    import librosa
    clap = _get_clap()
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32, copy=False)
    if sr != 48000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=48000)
    # CLAP expects (B, T) with T at least ~1s. Pad short chunks.
    min_len = 48000
    if audio.shape[0] < min_len:
        audio = np.pad(audio, (0, min_len - audio.shape[0]))
    batch = audio[np.newaxis, :]
    emb = clap.get_audio_embedding_from_data(x=batch, use_tensor=False)
    v = np.asarray(emb, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if n > 0:
        v = v / n
    return v


def _embed_texts(prompts_by_cat: dict[str, list[str]]) -> dict[str, np.ndarray]:
    """Compute mean-pooled CLAP text embedding per category. L2-normalised."""
    clap = _get_clap()
    flat: list[tuple[str, str]] = []
    for cat, prompts in prompts_by_cat.items():
        for p in prompts:
            flat.append((cat, p))
    texts = [t for _, t in flat]
    raw = clap.get_text_embedding(texts, use_tensor=False)
    raw = np.asarray(raw, dtype=np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    raw = raw / norms

    out: dict[str, np.ndarray] = {}
    by_cat: dict[str, list[np.ndarray]] = {}
    for (cat, _), vec in zip(flat, raw):
        by_cat.setdefault(cat, []).append(vec)
    for cat, vs in by_cat.items():
        m = np.mean(vs, axis=0)
        n = float(np.linalg.norm(m))
        out[cat] = m / n if n > 0 else m
    return out


# ── chunking + voting ────────────────────────────────────────────────────────

def _measure_windows(
    downbeats_sec: list[float],
    duration_sec: float,
    beats_per_window: int = 1,
) -> list[tuple[int, float, float]]:
    """Return (measure_index_1based, start_sec, end_sec) for each measure.

    ``beats_per_window`` is in *measures*: use 1 for every-measure prediction,
    2 for half-time prediction (more stable, faster).
    """
    db = list(downbeats_sec)
    if not db:
        return []
    if db[-1] < duration_sec:
        db = db + [duration_sec]
    windows = []
    for i in range(0, len(db) - 1, beats_per_window):
        end_idx = min(i + beats_per_window, len(db) - 1)
        start = float(db[i])
        end = float(db[end_idx])
        if end - start < 0.4:
            continue
        windows.append((i + 1, start, end))
    return windows


def _rms_dbfs(audio: np.ndarray) -> float:
    """RMS level of a mono/stereo float32 chunk in dBFS."""
    if audio.size == 0:
        return -120.0
    x = audio if audio.ndim == 1 else audio.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))
    return 20.0 * np.log10(rms + 1e-12)


# Categories with fewer than this many reference vectors are considered
# UNRELIABLE — leave-one-out testing (2026-05-27) showed epiano (n=3),
# synth_lead (n=8), and fx (n=16) classify at 0-25% because there aren't
# enough exemplars to anchor them in CLAP space. We don't hide them, but
# we discount their confidence so the UI flags them and the cue-merge
# step (MIN_CONFIDENCE_FOR_CUE) drops the shakiest ones.
MIN_RELIABLE_REFS = 40


def _category_counts(db: ReferenceDB) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in db.categories:
        counts[c] = counts.get(c, 0) + 1
    return counts


def _top_k_vote(
    query: np.ndarray,
    db: ReferenceDB,
    k: int = 16,
) -> tuple[str, float, str]:
    """Weighted-vote top-k nearest against the reference DB.

    Returns (best_category, confidence, runner_up_category).
    Confidence = (top1 mass - runner-up mass) ∈ [0, 1], then discounted
    by a reliability factor when the winning category is under-populated
    in the reference DB (see MIN_RELIABLE_REFS).
    """
    sims = db.embeddings @ query                                      # (N,)
    idx = np.argpartition(-sims, kth=min(k, sims.shape[0] - 1))[:k]
    weights = sims[idx]
    # Map negative similarities to 0 so they don't pull a category up.
    weights = np.clip(weights, 0.0, None)
    tally: dict[str, float] = {}
    for i, w in zip(idx, weights):
        tally[db.categories[i]] = tally.get(db.categories[i], 0.0) + float(w)
    total = sum(tally.values()) or 1.0
    ordered = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
    if not ordered:
        return ("fx", 0.0, "")
    best, best_mass = ordered[0]
    runner = ordered[1][0] if len(ordered) > 1 else ""
    runner_mass = ordered[1][1] if len(ordered) > 1 else 0.0
    confidence = max(0.0, (best_mass - runner_mass) / total)

    # Reliability discount for under-populated categories. Cache the
    # per-category counts on the DB object so we compute them once.
    counts = getattr(db, "_cat_counts", None)
    if counts is None:
        counts = _category_counts(db)
        try:
            db._cat_counts = counts            # type: ignore[attr-defined]
        except Exception:
            pass
    n_best = counts.get(best, 0)
    if n_best < MIN_RELIABLE_REFS:
        # Scale confidence down proportionally to how thin the category is.
        # n=3 → ×0.075, n=16 → ×0.4, n=39 → ×0.975. Effectively pushes most
        # of these below MIN_CONFIDENCE_FOR_CUE so they don't get emitted
        # as confident cues.
        confidence *= n_best / MIN_RELIABLE_REFS

    return (best, float(confidence), runner)


def _zero_shot_match(
    query: np.ndarray,
    text_emb: dict[str, np.ndarray],
) -> tuple[str, float, str]:
    """Cosine match against pre-computed text-prompt embeddings."""
    items = sorted(text_emb.items())
    cats = [c for c, _ in items]
    M = np.stack([v for _, v in items])                                # (C, 512)
    sims = M @ query                                                    # (C,)
    order = np.argsort(-sims)
    best_idx = int(order[0])
    runner_idx = int(order[1]) if order.shape[0] > 1 else best_idx
    # Map [−1, 1] similarity to a [0, 1] confidence with a soft margin.
    margin = float(sims[best_idx] - sims[runner_idx])
    confidence = max(0.0, min(1.0, sims[best_idx] * 0.5 + margin * 2.0))
    return (cats[best_idx], confidence, cats[runner_idx])


# ── public API ───────────────────────────────────────────────────────────────

def classify_measures(
    audio_path: Path,
    downbeats_sec: list[float],
    duration_sec: float,
    *,
    db_dir: Path | None = None,
    measures_per_window: int = 1,
    top_k: int = 16,
) -> AuxAutoResult:
    """Predict AUX patch labels per measure for one audio file.

    ``downbeats_sec`` typically comes from ``sections.SectionsResult.beat_grid``.
    """
    import soundfile as sf

    audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio_mono = audio.mean(axis=1)
    else:
        audio_mono = audio

    # Pick mode: reference DB if available, else zero-shot CLAP-text.
    db = load_reference_db(db_dir) if db_dir is not None else None
    text_emb: dict[str, np.ndarray] | None = None
    mode = "reference_db" if db is not None else "zero_shot"
    if db is None:
        text_emb = _embed_texts(ZERO_SHOT_PROMPTS)

    windows = _measure_windows(
        downbeats_sec, duration_sec,
        beats_per_window=measures_per_window,
    )
    candidates: list[AuxCandidate] = []
    for m_idx, start, end in windows:
        s = int(start * sr)
        e = int(end * sr)
        chunk = audio_mono[s:e]
        if chunk.size == 0:
            continue
        if _rms_dbfs(chunk) < MIN_RMS_DBFS:
            candidates.append(AuxCandidate(
                measure=m_idx, start_sec=start, end_sec=end,
                patch="silent", confidence=1.0, runner_up="",
            ))
            continue
        try:
            q = _embed_audio(chunk, sr)
        except Exception:
            continue
        if db is not None:
            patch, conf, runner = _top_k_vote(q, db, k=top_k)
        else:
            assert text_emb is not None
            patch, conf, runner = _zero_shot_match(q, text_emb)
        candidates.append(AuxCandidate(
            measure=m_idx, start_sec=start, end_sec=end,
            patch=patch, confidence=conf, runner_up=runner,
        ))

    cues = _merge_contiguous(candidates)
    return AuxAutoResult(
        cues=cues, candidates=candidates,
        mode=mode, db_size=(0 if db is None else int(db.embeddings.shape[0])),
    )


def _merge_contiguous(cands: list[AuxCandidate]) -> list[dict]:
    """Collapse consecutive same-patch measures into a single cue range."""
    out: list[dict] = []
    cur: dict | None = None
    for c in cands:
        if c.confidence < MIN_CONFIDENCE_FOR_CUE and c.patch != "silent":
            # Low confidence: don't emit; let the previous cue end.
            if cur is not None:
                out.append(cur)
                cur = None
            continue
        if cur is None or c.patch != cur["patch"] or c.measure != cur["end_measure"] + 1:
            if cur is not None:
                out.append(cur)
            cur = {
                "start_measure": c.measure,
                "end_measure": c.measure,
                "patch": c.patch,
                "note": f"AI 초안 · conf {c.confidence:.2f}"
                        + (f" (vs {c.runner_up})" if c.runner_up else ""),
                # Surface the raw numbers so the UI can visualise reliability
                # instead of having to parse the note text.
                "confidence": round(float(c.confidence), 3),
                "runner_up": c.runner_up or "",
                "confidence_min_track": round(float(c.confidence), 3),
            }
        else:
            cur["end_measure"] = c.measure
            # When a high-confidence run also covers a low-confidence patch
            # of the same name, remember the *lowest* confidence in the
            # span — that's what the UI's reliability badge should show.
            cur["confidence_min_track"] = min(
                cur.get("confidence_min_track",
                        cur.get("confidence", float(c.confidence))),
                float(c.confidence),
            )
            cur["confidence"] = cur["confidence_min_track"]
    if cur is not None:
        out.append(cur)
    # Drop trailing 'silent' runs at the very start/end — those are usually
    # intro/outro silence the user doesn't need patch hints for.
    while out and out[0]["patch"] == "silent":
        out.pop(0)
    while out and out[-1]["patch"] == "silent":
        out.pop()
    return out
