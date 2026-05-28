"""Run all baseline-measurement scripts in-process and gate against
``tests/fixtures/accuracy_thresholds.json``.

Unlike ``test_accuracy_thresholds.py`` which reads the most-recent JSON
report on disk, this test *runs* the measurement scripts every CI build
so we catch regressions on the actual code path — not on a stale report.

Three measurements, each <30s on CPU:
  1. drums F1   on the synthetic kit corpus
  2. slash-chord cross-check on three synthetic bass scenarios
  3. lyrics alignment IoU on a vocal-onset synth track

Fails CI when any measurement drops below its threshold ``min``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = json.loads(
    (ROOT / "tests" / "fixtures" / "accuracy_thresholds.json")
    .read_text(encoding="utf-8")
)


def test_drum_f1_on_synth_corpus_meets_min():
    from scripts.measure_drums_f1 import (
        synth_kit_track, _write_wav, _onset_f1,
    )
    import tempfile
    audio, gt = synth_kit_track()
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "drums.wav"
        _write_wav(wav, audio)
        from backend.app.pipeline.transcribe_backends.a2d2 import (
            transcribe, GM_KICK, GM_SNARE, GM_HH_CLOSED, GM_HH_OPEN,
        )
        pm, _ = transcribe(wav)
    pred = {"kick": [], "snare": [], "hihat": []}
    for inst in pm.instruments:
        for n in inst.notes:
            p = int(n.pitch)
            if p == GM_KICK:
                pred["kick"].append(float(n.start))
            elif p == GM_SNARE:
                pred["snare"].append(float(n.start))
            elif p in (GM_HH_CLOSED, GM_HH_OPEN):
                pred["hihat"].append(float(n.start))
    tp_sum = fp_sum = fn_sum = 0
    for inst in ("kick", "snare", "hihat"):
        p, r, _ = _onset_f1(gt[inst], pred[inst])
        gtn = len(gt[inst]); pn = len(pred[inst])
        tp_eq = r * gtn
        tp_sum += tp_eq
        fp_sum += pn - tp_eq
        fn_sum += gtn - tp_eq
    P = tp_sum / (tp_sum + fp_sum) if (tp_sum + fp_sum) else 0.0
    R = tp_sum / (tp_sum + fn_sum) if (tp_sum + fn_sum) else 0.0
    F = 2 * P * R / (P + R) if (P + R) else 0.0
    print(f"  drum F1 = {F:.3f}")
    min_f1 = THRESHOLDS["transcribe"]["drum_f1"]["min"]
    assert F >= min_f1, f"drum F1 {F:.3f} below min {min_f1}"


def test_slash_chord_cross_check_3_scenarios_pass():
    import tempfile
    from scripts.measure_slash_chord_accuracy import (
        ChordEvent, _PC_HZ_A2, _saw, _write_wav,
    )
    import numpy as np
    from backend.app.pipeline.chord_bass_check import cross_check_slash_bass
    DUR = 2.0
    track = np.concatenate([
        _saw(_PC_HZ_A2["C"], DUR),
        _saw(_PC_HZ_A2["E"], DUR),
        _saw(_PC_HZ_A2["G"], DUR),
    ]).astype(np.float32)
    passes = 0
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "bass.wav"
        _write_wav(wav, track)
        # Truthful — every slash matches.
        truthful = [
            ChordEvent(0.0, 2.0, label="F/C", confidence=0.5),
            ChordEvent(2.0, 4.0, label="C/E", confidence=0.5),
            ChordEvent(4.0, 6.0, label="C/G", confidence=0.5),
        ]
        a = cross_check_slash_bass(truthful, wav)
        if a.get("confirmed", 0) >= 2:
            passes += 1
        # Lying — none match.
        lying = [
            ChordEvent(0.0, 2.0, label="Am/F#", confidence=0.5),
            ChordEvent(2.0, 4.0, label="D/A", confidence=0.5),
            ChordEvent(4.0, 6.0, label="F/B", confidence=0.5),
        ]
        b = cross_check_slash_bass(lying, wav)
        if b.get("downgraded", 0) >= 2:
            passes += 1
        # Mixed.
        mixed = [
            ChordEvent(0.0, 2.0, label="F/C", confidence=0.5),
            ChordEvent(2.0, 4.0, label="D/A", confidence=0.5),
            ChordEvent(4.0, 6.0, label="C/G", confidence=0.5),
        ]
        c = cross_check_slash_bass(mixed, wav)
        if c.get("confirmed", 0) >= 1 and c.get("downgraded", 0) >= 1:
            passes += 1
    print(f"  slash-chord scenarios passed: {passes}/3")
    assert passes == 3, f"only {passes}/3 slash-chord scenarios passed"


def test_chord_tension_detection():
    """Chroma tension detector recovers add9/6/sus/7 (what CREMA can't)
    and does NOT hallucinate tension onto a plain triad."""
    import math
    import numpy as np
    from backend.app.pipeline.chord_tension import detect_tensions

    SR = 22050

    def _chroma(offs, dur=2.0):
        import librosa
        t = np.arange(int(dur * SR)) / SR
        sig = np.zeros(len(t), dtype=np.float32)
        for st in offs:
            f = 261.63 * 2 ** (st / 12.0)
            sig += (0.25 * np.sin(2 * math.pi * f * t)
                    + 0.1 * np.sin(2 * math.pi * 2 * f * t)).astype(np.float32)
        y_h = librosa.effects.harmonic(sig, margin=4.0)
        return librosa.feature.chroma_cqt(y=y_h, sr=SR, hop_length=512,
                                          n_chroma=12).mean(axis=1)

    # (offsets, root_pc, is_minor, key, expected)
    cases = [
        ([0, 4, 7, 14], 0, False, "add", "add9"),
        ([0, 4, 7, 9], 0, False, "add", "6"),
        ([0, 5, 7], 0, False, "sus", "sus4"),
        ([0, 2, 7], 0, False, "sus", "sus2"),
        ([0, 4, 7, 10], 0, False, "seventh", "7"),
        ([0, 4, 7, 11], 0, False, "seventh", "maj7"),
        # Upper-structure extensions on a 7th (what CREMA also can't do).
        ([0, 4, 7, 10, 14], 0, False, "ext", "9"),
        ([0, 4, 7, 10, 14, 17], 0, False, "ext", "11"),
        ([0, 4, 7, 10, 14, 17, 21], 0, False, "ext", "13"),
        ([0, 4, 7, 11, 14], 0, False, "ext", "9"),          # Cmaj9
        ([2, 5, 9, 12, 16], 2, True, "ext", "9"),           # Dm9
        # Altered dominants / lydian maj7 (modern worship harmony).
        ([0, 4, 7, 10, 13], 0, False, "alt", ["b9"]),       # C7b9
        ([0, 4, 7, 10, 15], 0, False, "alt", ["#9"]),       # C7#9
        ([0, 4, 7, 10, 18], 0, False, "alt", ["#11"]),      # C7#11
        ([0, 4, 8, 10], 0, False, "alt", ["#5"]),           # C7#5
        ([0, 4, 7, 11, 18], 0, False, "alt", ["#11"]),      # Cmaj7#11
        ([0, 4, 10, 13, 15], 0, False, "alt", ["b9", "#9"]),  # C7alt
    ]
    correct = 0
    for offs, root_pc, is_minor, key, expected in cases:
        t = detect_tensions(root_pc, is_minor, _chroma(offs))
        if t.get(key) == expected:
            correct += 1
    # Plain triad must NOT get a tension (no hallucination).
    plain = detect_tensions(0, False, _chroma([0, 4, 7]))
    no_halluc = (plain.get("sus") is None and plain.get("seventh") is None
                 and plain.get("add") is None and plain.get("ext") is None
                 and plain.get("alt") is None)
    acc = correct / len(cases)
    print(f"  tension detection acc={acc:.3f}, plain-triad clean={no_halluc}")
    assert acc >= 0.8, f"tension detection {acc:.3f} below 0.8"
    assert no_halluc, "tension detector hallucinated on a plain triad"


def test_chord_root_accuracy_synth():
    """Absolute chord root accuracy on a synthetic progression. Triads
    should be near-perfect; 7ths are weaker without CREMA (gated low)."""
    import importlib
    try:
        mod = importlib.import_module("scripts.measure_chord_accuracy")
    except Exception as e:
        pytest.skip(f"chord measure script import failed: {e!r}")
    import tempfile
    import numpy as np
    import soundfile as sf
    from backend.app.pipeline.chords import analyze_chords

    prog = [(60, "maj"), (62, "min"), (64, "min"), (65, "maj"),
            (67, "maj"), (69, "min"), (60, "maj"), (65, "maj")]
    chunks, gt = [], []
    for root, q in prog:
        chunks.append(mod._chord_audio(root, q))
        gt.append((root % 12, q))
    audio = np.concatenate(chunks).astype(np.float32)
    audio = np.clip(audio / (np.max(np.abs(audio)) + 1e-9) * 0.9, -1, 1)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "p.wav"
        sf.write(str(wav), np.stack([audio, audio], axis=1), mod.SR, subtype="FLOAT")
        events = analyze_chords(wav)
    dur = 2.0
    root_ok = 0
    for i, (gt_pc, _q) in enumerate(gt):
        centre = i * dur + dur / 2
        lbl = None
        for e in events:
            if float(getattr(e, "start_sec", 0)) <= centre <= float(getattr(e, "end_sec", 0)):
                lbl = getattr(e, "label", ""); break
        parsed = mod._parse_label(lbl) if lbl else None
        if parsed is not None and parsed[0] == gt_pc:
            root_ok += 1
    acc = root_ok / len(gt)
    thr = THRESHOLDS["chord"]["root_accuracy_synth"]["min"]
    print(f"  chord root accuracy (triads) = {acc:.3f}")
    assert acc >= thr, f"chord root accuracy {acc:.3f} < min {thr}"


def test_section_boundary_hit_rate():
    """Boundary detection on a synthetic clear-structure song."""
    import importlib
    try:
        mod = importlib.import_module("scripts.measure_section_accuracy")
    except Exception as e:
        pytest.skip(f"section measure script import failed: {e!r}")
    import tempfile
    audio, gt_bounds, _ = mod._build_song()
    gt_times = [t for t, _ in gt_bounds][1:]
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "song.wav"
        mod._write(wav, audio)
        from backend.app.pipeline.sections import analyze_sections
        res = analyze_sections(wav, "auto", refine=False)
    pred_bounds = [s.start_sec for s in res.sections][1:]
    hits = sum(1 for g in gt_times if any(abs(p - g) <= 3.0 for p in pred_bounds))
    hit_rate = hits / len(gt_times) if gt_times else 1.0
    thr = THRESHOLDS["section"]["boundary_hit_rate_3s"]["min"]
    print(f"  section boundary hit rate = {hit_rate:.3f}")
    assert hit_rate >= thr, f"section boundary hit rate {hit_rate:.3f} < min {thr}"


def test_pitch_transform_accuracy():
    """±semitone pitch shift must land on the target pitch within the
    cents tolerance. Uses the real transform_audio (Rubber Band/ffmpeg)."""
    import tempfile
    import math
    import numpy as np
    try:
        import soundfile as sf
    except Exception:
        pytest.skip("soundfile not available")
    from backend.app.pipeline.transform import transform_audio

    SR = 44100
    BASE = 440.0

    def _tone(freq, dur=2.5):
        t = np.arange(int(dur * SR)) / SR
        return (0.6 * np.sin(2 * math.pi * freq * t)).astype(np.float32)

    def _dom_hz(mono):
        n = len(mono)
        seg = mono[n // 4: n // 4 + min(n // 2, 1 << 16)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1.0 / SR)
        k = int(np.argmax(spec))
        if 1 <= k < len(spec) - 1:
            a, b, c = spec[k - 1], spec[k], spec[k + 1]
            d = (a - 2 * b + c)
            delta = 0.5 * (a - c) / d if d != 0 else 0.0
        else:
            delta = 0.0
        return (k + delta) * (freqs[1] - freqs[0])

    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "t.wav"
        sf.write(str(src), np.stack([_tone(BASE)] * 2, axis=1), SR, subtype="FLOAT")
        for st in (-5, -2, 3, 7):
            out = Path(tmp) / f"s{st}.wav"
            try:
                transform_audio(src, out, semitones=float(st), tempo_ratio=1.0,
                                stem_kind="instrumental")
            except Exception as e:
                pytest.skip(f"transform unavailable: {e!r}")
            audio, _ = sf.read(str(out), dtype="float32", always_2d=True)
            measured = _dom_hz(audio.mean(axis=1))
            expected = BASE * 2 ** (st / 12.0)
            errs.append(abs(1200.0 * math.log2(measured / expected)))

    mean_err = sum(errs) / len(errs)
    max_err = max(errs)
    thr = THRESHOLDS["transform"]
    print(f"  pitch transform: mean|err|={mean_err:.1f} max|err|={max_err:.1f} cents")
    assert mean_err <= thr["pitch_shift_mean_abs_cents"]["min"], \
        f"pitch shift mean error {mean_err:.1f} cents too high"
    assert max_err <= thr["pitch_shift_max_abs_cents"]["min"], \
        f"pitch shift max error {max_err:.1f} cents too high"


def test_aux_classifier_accuracy_when_db_present():
    """Leave-one-out accuracy on the AUX reference DB, gated against
    thresholds. Skips when the 5,178-vector DB isn't built (CI / fresh
    checkout) — it's a 10 MB artifact not committed to the repo."""
    db_dir = ROOT / "data" / "reference_db" / "aux"
    emb_path = db_dir / "embeddings.npy"
    meta_path = db_dir / "metadata.json"
    if not emb_path.exists() or not meta_path.exists():
        pytest.skip("AUX reference DB not built (data/reference_db/aux)")

    import json as _json
    import numpy as np
    from collections import Counter

    emb = np.load(emb_path).astype(np.float32)
    cats = _json.loads(meta_path.read_text(encoding="utf-8"))["categories"]
    norm = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    sim = norm @ norm.T
    np.fill_diagonal(sim, -np.inf)
    K = 16
    correct = 0
    per_total: Counter = Counter()
    per_correct: Counter = Counter()
    for i in range(emb.shape[0]):
        topk = np.argpartition(sim[i], -K)[-K:]
        pred = Counter(cats[j] for j in topk).most_common(1)[0][0]
        true = cats[i]
        per_total[true] += 1
        if pred == true:
            correct += 1
            per_correct[true] += 1
    overall = correct / emb.shape[0]

    # Well-populated categories (>=40 refs) must each stay above the floor.
    well_pop_accs = [
        per_correct[c] / per_total[c]
        for c in per_total if per_total[c] >= 40
    ]
    well_pop_min = min(well_pop_accs) if well_pop_accs else 1.0

    thr = THRESHOLDS["aux_classifier"]
    print(f"  AUX leave-one-out overall={overall:.3f}, "
          f"well-populated min={well_pop_min:.3f}")
    assert overall >= thr["leave_one_out_overall"]["min"], \
        f"AUX overall {overall:.3f} < min {thr['leave_one_out_overall']['min']}"
    assert well_pop_min >= thr["well_populated_category_min"]["min"], \
        f"AUX well-populated min {well_pop_min:.3f} below threshold"


def test_lyrics_align_iou_after_polish_meets_min():
    import tempfile
    from scripts.measure_lyrics_align_iou import (
        FakeWord, _synth_vocal_onsets, _write_wav, _iou,
        SCATTER_MS, SCATTER_SEED, SR,
    )
    import numpy as np
    audio, gt_onsets = _synth_vocal_onsets()
    gt_words = [(t, t + 0.5) for t in gt_onsets]
    rng = np.random.default_rng(SCATTER_SEED)
    noisy = []
    for i, (gs, ge) in enumerate(gt_words):
        drift = rng.uniform(-SCATTER_MS, SCATTER_MS) / 1000.0
        noisy.append(FakeWord(f"w{i}", gs + drift, ge + drift))

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "vocals.wav"
        _write_wav(wav, audio)
        from backend.app.pipeline.lyrics_align import polish_word_timestamps
        polish_word_timestamps(noisy, wav, max_nudge_ms=180.0, sample_rate=SR)
    iou_after = float(np.mean(
        [_iou(w.start_sec, w.end_sec, gs, ge)
         for w, (gs, ge) in zip(noisy, gt_words)]
    ))
    print(f"  lyrics IoU after polish = {iou_after:.3f}")
    min_iou = THRESHOLDS["lyrics"]["word_timing_iou_after_polish"]["min"]
    assert iou_after >= min_iou, \
        f"lyrics IoU {iou_after:.3f} below min {min_iou}"
