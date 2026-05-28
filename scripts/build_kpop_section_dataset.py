"""LLM-assisted K-Pop section dataset builder.

Run this against a folder of K-Pop MR / vocal pairs and it produces a
JSONL dataset of (audio_path, sections[]) records that can be fed back
into the platform as ground truth for fine-tuning the section
classifier.

Pipeline (per track):

    1. Run our existing analyze_sections() to get candidate boundaries
       and rule-based labels.
    2. Pull lyrics via transcribe_lyrics (if not already cached).
    3. Send (boundaries + chord progression + lyric snippet + position)
       to the local LLM via Ollama.
    4. Ask the LLM to verify / correct each label using K-Pop song-form
       knowledge.
    5. Persist the (LLM-confirmed) record to ``data/kpop_sections.jsonl``.

This builds a SELF-DISTILLATION dataset: the LLM acts as the labeller,
the rule-based detector is the bootstrap source. After 100-200 tracks
the JSONL is large enough to train a lightweight refinement classifier
that's faster than calling the LLM per-song at inference time.

Usage::

    python scripts/build_kpop_section_dataset.py path/to/kpop_folder
    python scripts/build_kpop_section_dataset.py --resume     # skip already-labeled
    python scripts/build_kpop_section_dataset.py --limit 50  # process at most 50

Requires:
    - Ollama running locally (otherwise we fall back to rule-only labels
      and mark confidence=low — useful for crowd-sourced correction later).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def _audio_files_in(folder: Path) -> list[Path]:
    exts = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    )


def _already_labeled(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    seen: set[str] = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if "audio_path" in rec:
                seen.add(rec["audio_path"])
        except Exception:
            continue
    return seen


def _process_one(audio_path: Path) -> dict:
    """Analyse sections + lyrics + chords + LLM refinement for one track."""
    from backend.app.pipeline.sections import analyze_sections
    from backend.app.pipeline.lyrics import transcribe_lyrics, LANG_AUTO
    from backend.app.pipeline.chords import analyze_chords
    import tempfile

    t0 = time.time()
    result: dict = {
        "audio_path": str(audio_path),
        "ts_built": int(t0),
        "sections": [],
        "time_signature": "4/4",
        "errors": [],
    }

    # Lyrics first — chord/section refiners benefit from them.
    lyrics_words = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lr = transcribe_lyrics(
                audio_path, Path(tmp), language=LANG_AUTO,
                domain_prompt="kpop_ko", model_size="small",
            )
            lyrics_words = [
                {"word": w.word, "start_sec": w.start_sec,
                 "end_sec": w.end_sec, "confidence": w.confidence}
                for w in lr.words
            ]
            result["language"] = lr.language
            result["lyrics_avg_confidence"] = lr.avg_confidence
    except Exception as e:
        result["errors"].append(f"lyrics: {e!r}")

    # Chord detection.
    chord_events_dict = None
    try:
        chord_events = analyze_chords(audio_path)
        chord_events_dict = [
            {"start_sec": c.start_sec, "end_sec": c.end_sec,
             "root": c.root, "quality": c.quality,
             "label": c.label, "confidence": c.confidence}
            for c in chord_events
        ]
        result["chord_count"] = len(chord_events_dict)
    except Exception as e:
        result["errors"].append(f"chords: {e!r}")

    # Sections — auto meter + SSM + lyric + LLM refinement.
    try:
        sec = analyze_sections(
            audio_path, meter="auto",
            lyrics_words=lyrics_words,
            chord_events=chord_events_dict,
            refine=True,
        )
        result["sections"] = [
            {"start_sec": s.start_sec, "end_sec": s.end_sec, "label": s.label}
            for s in sec.sections
        ]
        result["bpm"] = sec.beat_grid.bpm
        result["meter"] = sec.beat_grid.meter
        result["time_signature"] = sec.beat_grid.time_signature
        result["is_compound"] = sec.beat_grid.is_compound
    except Exception as e:
        result["errors"].append(f"sections: {e!r}")

    result["elapsed_sec"] = round(time.time() - t0, 1)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path, help="folder of K-Pop audio files")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data" / "kpop_sections.jsonl",
                    help="output JSONL path")
    ap.add_argument("--resume", action="store_true",
                    help="skip tracks already present in the output JSONL")
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N tracks this run (0 = no cap)")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    audio = _audio_files_in(args.folder)
    if not audio:
        print(f"no audio files in {args.folder}", file=sys.stderr)
        sys.exit(2)
    print(f"found {len(audio)} candidate files in {args.folder}")

    seen = _already_labeled(args.out) if args.resume else set()
    queue = [p for p in audio if str(p) not in seen]
    if args.limit > 0:
        queue = queue[:args.limit]
    print(f"processing {len(queue)} (resume={args.resume}, limit={args.limit})")

    with args.out.open("a", encoding="utf-8") as fp:
        for i, p in enumerate(queue, start=1):
            print(f"\n[{i}/{len(queue)}] {p.name}")
            try:
                rec = _process_one(p)
            except Exception as e:
                rec = {"audio_path": str(p), "errors": [f"fatal: {e!r}"]}
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            secs = rec.get("sections") or []
            print(f"  → {len(secs)} sections, ts={rec.get('time_signature')}, "
                  f"bpm={rec.get('bpm', '?')}, errors={len(rec.get('errors') or [])}")

    print(f"\ndone. JSONL appended at: {args.out}")


if __name__ == "__main__":
    main()
