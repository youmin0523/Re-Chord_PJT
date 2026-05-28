"""Command-line entry point for development and pipeline smoke tests.

Usage:
  uv run mr ingest --input <url-or-path>
  uv run mr decode --input <path-to-master-wav>
  uv run mr pipeline --input <url-or-path>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .config import settings
from .core.paths import new_job_id, ensure_dir
from .pipeline.ingest import ingest, IngestResult
from .pipeline.decode import decode_to_master, DecodeResult
from .pipeline.separate import separate_two_stem, separate_multi_model, SeparateResult, MODELS
from .pipeline.ensemble import ensemble_stems, mixback
from .pipeline.analyze import analyze, semitones_between
from .pipeline.transform import transform_audio, bpm_to_tempo_ratio
from .pipeline.encode import encode, ALLOWED_SR, ALLOWED_BIT_DEPTHS
from .pipeline.transcribe import transcribe
from .pipeline.score import build_score


app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console(legacy_windows=False, force_terminal=True)


def _print_ingest(r: IngestResult) -> None:
    t = Table(title=f"Ingest result [{r.job_id}]", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("kind", r.kind)
    t.add_row("origin", r.origin)
    t.add_row("source", str(r.source))
    t.add_row("container", r.container)
    t.add_row("audio_codec", r.audio_codec)
    t.add_row("sample_rate", f"{r.sample_rate} Hz")
    t.add_row("channels", str(r.channels))
    t.add_row("bit_rate", str(r.bit_rate) if r.bit_rate else "n/a")
    t.add_row("duration", f"{r.duration_sec:.2f} s")
    console.print(t)


def _print_decode(r: DecodeResult) -> None:
    t = Table(title=f"Decode result [{r.job_id}]", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("master", str(r.master))
    t.add_row("sample_rate", f"{r.sample_rate} Hz")
    t.add_row("channels", str(r.channels))
    t.add_row("duration", f"{r.duration_sec:.2f} s")
    size_mb = r.master.stat().st_size / (1024 * 1024)
    t.add_row("file_size", f"{size_mb:.2f} MB")
    console.print(t)


def _print_separate(r: SeparateResult) -> None:
    t = Table(title=f"Separate result [{r.job_id}] - {r.model}", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    for stem, path in r.stems.items():
        size_mb = path.stat().st_size / (1024 * 1024) if path.exists() else 0
        t.add_row(stem, f"{path} ({size_mb:.1f} MB)")
    t.add_row("elapsed", f"{r.elapsed_sec:.2f} s")
    t.add_row("input_duration", f"{r.input_duration_sec:.2f} s")
    t.add_row("realtime_factor", f"{r.realtime_factor:.2f}x")
    console.print(t)


@app.command("ingest")
def ingest_cmd(
    input: str = typer.Option(..., "--input", "-i", help="URL or file path"),
    job_id: str = typer.Option(None, "--job-id", help="Override job id"),
) -> None:
    """Stage 1: download (URL) or validate (file) the source media."""
    jid = job_id or new_job_id()
    ensure_dir(settings.uploads_dir)
    r = ingest(input, jid)
    _print_ingest(r)


@app.command("decode")
def decode_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Path to an ingested source"),
    source_sr: int = typer.Option(0, "--source-sr", help="Force source sr (else probed)"),
    job_id: str = typer.Option(None, "--job-id", help="Override job id"),
) -> None:
    """Stage 2: decode the source to a working stereo float32 wav."""
    jid = job_id or new_job_id()
    work_dir = settings.work_dir / jid
    src = Path(input)
    if source_sr <= 0:
        from .pipeline.ingest import ffprobe_streams, pick_audio_stream
        probe = ffprobe_streams(src)
        source_sr = int(pick_audio_stream(probe).get("sample_rate") or 48000)
    r = decode_to_master(src, work_dir, source_sr=source_sr, job_id=jid)
    _print_decode(r)


@app.command("separate")
def separate_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Path to a decoded master wav"),
    model: str = typer.Option("mdx23c_instvoc_hq", "--model", "-m",
                              help=f"Model alias or filename. Aliases: {', '.join(MODELS)}"),
    job_id: str = typer.Option(None, "--job-id", help="Override job id"),
) -> None:
    """Stage 3: run a single 2-stem separation model on the master wav."""
    jid = job_id or new_job_id()
    model_filename = MODELS.get(model, model)
    src = Path(input)
    r = separate_two_stem(src, jid, model_filename=model_filename)
    _print_separate(r)


@app.command("ensemble")
def ensemble_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Path to a decoded master wav"),
    models: str = typer.Option(
        "mdx23c_instvoc_hq,bs_roformer_1297,htdemucs_ft",
        "--models",
        help="Comma-separated model aliases or filenames to run sequentially.",
    ),
    method: str = typer.Option("mag_avg", "--method",
                               help="Combination method: mag_avg | min | mean"),
    mixback_enable: bool = typer.Option(True, "--mixback/--no-mixback",
                                        help="Add residual back to stems for natural detail"),
    inst_share: float = typer.Option(0.5, "--inst-share",
                                     help="Fraction of residual added to instrumental (0..1)"),
    target_sr: int = typer.Option(48000, "--target-sr",
                                  help="Resample all stems to this rate"),
    job_id: str = typer.Option(None, "--job-id", help="Override job id"),
    skip_separate: bool = typer.Option(
        False, "--skip-separate",
        help="Reuse existing per-model stems under the job's stems dir.",
    ),
) -> None:
    """Stage 3+4: multi-model separation, ensemble combination, optional mixback."""
    jid = job_id or new_job_id()
    aliases = [m.strip() for m in models.split(",") if m.strip()]
    src = Path(input)

    if skip_separate:
        per_model: list[SeparateResult] = []
        from .pipeline.separate import MODELS as _M
        for alias in aliases:
            fname = _M.get(alias, alias)
            model_dir = settings.stems_dir / jid / fname.rsplit(".", 1)[0]
            stems: dict[str, Path] = {}
            for p in model_dir.glob("*.wav"):
                low = p.name.lower()
                if "(vocals)" in low or "_vocals_" in low:
                    stems["vocals"] = p
                elif "(instrumental)" in low or "_instrumental_" in low:
                    stems["instrumental"] = p
            synth = model_dir / "_synth_instrumental.wav"
            if "instrumental" not in stems and synth.exists():
                stems["instrumental"] = synth
            per_model.append(SeparateResult(
                job_id=jid, model=fname, stems=stems,
                elapsed_sec=0.0, input_duration_sec=0.0,
            ))
        total_elapsed = 0.0
        console.print(f"[yellow]--skip-separate[/yellow]: reused stems from {settings.stems_dir / jid}")
    else:
        console.print(f"[bold cyan]Running {len(aliases)} models sequentially:[/bold cyan] {aliases}")
        per_model = separate_multi_model(src, jid, aliases)
        total_elapsed = 0.0
        for r in per_model:
            _print_separate(r)
            total_elapsed += r.elapsed_sec

    # Build htdemucs's instrumental in --skip-separate mode if it's missing.
    for r in per_model:
        if "instrumental" not in r.stems and "vocals" in r.stems:
            model_dir = next(iter(r.stems.values())).parent
            non_vocal = sorted(
                p for p in model_dir.glob("*.wav")
                if "(vocals)" not in p.name.lower() and "instrumental" not in p.name.lower()
                and not p.name.startswith("_synth_")
            )
            if non_vocal:
                synth = model_dir / "_synth_instrumental.wav"
                from .pipeline.separate import _sum_stems_to_wav
                _sum_stems_to_wav(non_vocal, synth)
                r.stems["instrumental"] = synth

    inst_sources = [r.stems["instrumental"] for r in per_model if "instrumental" in r.stems]
    voc_sources = [r.stems["vocals"] for r in per_model if "vocals" in r.stems]

    out_dir = settings.stems_dir / jid / f"ensemble_{method}"
    ensure_dir(out_dir)

    console.print(f"\n[bold cyan]Combining with method={method!r} (target_sr={target_sr})[/bold cyan]"
                  f"  inst_sources={len(inst_sources)}  voc_sources={len(voc_sources)}")
    inst_result = ensemble_stems(
        inst_sources, out_dir / "instrumental.wav",
        method=method, target_sr=target_sr,  # type: ignore[arg-type]
    )
    voc_result = ensemble_stems(
        voc_sources, out_dir / "vocals.wav",
        method=method, target_sr=target_sr,  # type: ignore[arg-type]
    )

    final_inst = inst_result.out_path
    final_voc = voc_result.out_path

    if mixback_enable:
        mb_dir = settings.stems_dir / jid / f"ensemble_{method}_mixback{int(inst_share * 100):03d}"
        ensure_dir(mb_dir)
        console.print(f"[bold cyan]Mixback[/bold cyan] inst_share={inst_share:.2f}")
        out_paths = mixback(
            original_master=src,
            instrumental=inst_result.out_path,
            vocals=voc_result.out_path,
            out_inst=mb_dir / "instrumental.wav",
            out_voc=mb_dir / "vocals.wav",
            inst_share=inst_share,
            target_sr=target_sr,
        )
        final_inst = out_paths["instrumental"]
        final_voc = out_paths["vocals"]

    summary = Table(title=f"Final ensemble [{jid}] - method={method}, mixback={mixback_enable}", show_header=False)
    summary.add_column("Field", style="bold")
    summary.add_column("Value", overflow="fold")
    summary.add_row("instrumental", str(final_inst))
    summary.add_row("vocals", str(final_voc))
    summary.add_row("n_sources_inst", str(inst_result.n_sources))
    summary.add_row("n_sources_voc", str(voc_result.n_sources))
    summary.add_row("sample_rate", f"{inst_result.sample_rate} Hz")
    summary.add_row("duration", f"{inst_result.duration_sec:.2f} s")
    if total_elapsed > 0:
        summary.add_row("total_separation_time", f"{total_elapsed:.2f} s")
        if per_model:
            in_dur = per_model[0].input_duration_sec
            if in_dur > 0:
                summary.add_row("aggregate_realtime_factor", f"{in_dur / total_elapsed:.2f}x")
    console.print(summary)


@app.command("analyze")
def analyze_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Audio file to analyze"),
) -> None:
    """Stage 5a: detect musical key and BPM."""
    src = Path(input)
    r = analyze(src)
    t = Table(title=f"Analyze result - {src.name}", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("key", f"{r.key_name}  (confidence {r.key_confidence:.2f})")
    t.add_row("bpm", f"{r.bpm:.2f}  (confidence {r.bpm_confidence:.2f})")
    t.add_row("duration", f"{r.duration_sec:.2f} s")
    console.print(t)


@app.command("transform")
def transform_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Audio file (wav) to transform"),
    output: str = typer.Option(..., "--output", "-o", help="Output wav path"),
    semitones: float = typer.Option(0.0, "--semitones", "-k",
                                    help="Pitch shift (semitones, e.g. +2, -1.5)"),
    tempo_ratio: float = typer.Option(1.0, "--tempo-ratio",
                                      help="Tempo multiplier (1.0 unchanged, 1.2 = +20%%)"),
    source_bpm: float = typer.Option(0.0, "--source-bpm",
                                     help="If given with --target-bpm, computes tempo_ratio"),
    target_bpm: float = typer.Option(0.0, "--target-bpm", help="Desired BPM"),
    target_key: str = typer.Option("", "--target-key",
                                   help="Pitch class (e.g. 'D'). If given with --source-key, computes semitones"),
    source_key: str = typer.Option("", "--source-key", help="Source pitch class (e.g. 'C')"),
    engine: str = typer.Option("auto", "--engine",
                               help="auto (R3 if rubberband-cli present, else R2) | finer | faster"),
    stem_kind: str = typer.Option("generic", "--stem-kind",
                                  help="instrumental | vocals | drums | bass | harmonic | mix | generic"),
    preserve_formants: bool = typer.Option(None, "--formants/--no-formants",
                                           help="Override preset formant preservation."),
) -> None:
    """Stage 5b: pitch / tempo transform (R3 finer when available)."""
    if source_key and target_key:
        semitones = float(semitones_between(source_key, target_key))
        console.print(f"[cyan]Computed semitones from key map: {source_key} -> {target_key} = {semitones:+.0f}[/cyan]")
    if source_bpm > 0 and target_bpm > 0:
        tempo_ratio = bpm_to_tempo_ratio(source_bpm, target_bpm)
        console.print(f"[cyan]Computed tempo ratio: {source_bpm:.1f} -> {target_bpm:.1f} = {tempo_ratio:.4f}x[/cyan]")

    r = transform_audio(
        Path(input), Path(output),
        semitones=semitones, tempo_ratio=tempo_ratio,
        engine=engine,  # type: ignore[arg-type]
        stem_kind=stem_kind,  # type: ignore[arg-type]
        preserve_formants=preserve_formants,
    )
    t = Table(title="Transform result", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("out_path", str(r.out_path))
    t.add_row("semitones", f"{r.semitones:+.4f}")
    t.add_row("tempo_ratio", f"{r.tempo_ratio:.4f}x")
    t.add_row("engine", r.engine)
    t.add_row("stem_kind", r.stem_kind)
    t.add_row("elapsed", f"{r.elapsed_sec:.2f} s")
    console.print(t)


@app.command("encode")
def encode_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Audio file (wav) to encode"),
    output: str = typer.Option(..., "--output", "-o", help="Output path (extension auto-fixed)"),
    format: str = typer.Option("wav", "--format", "-f",
                               help="wav | flac | aiff | mp3 | aac"),
    sample_rate: int = typer.Option(48000, "--sr",
                                    help="Target sr. wav/flac/aiff: 44100|48000|88200|96000; mp3/aac: 44100|48000"),
    bit_depth: str = typer.Option("24", "--bit",
                                  help="16 | 24 | 32f (ignored for mp3/aac)"),
) -> None:
    """Stage 7: encode to final user-facing format."""
    r = encode(
        Path(input), Path(output),
        format=format,  # type: ignore[arg-type]
        sample_rate=sample_rate,
        bit_depth=bit_depth,  # type: ignore[arg-type]
    )
    t = Table(title=f"Encode result - {r.format}", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("out_path", str(r.out_path))
    t.add_row("format", r.format)
    t.add_row("sample_rate", f"{r.sample_rate} Hz")
    t.add_row("bit_depth", str(r.bit_depth or "lossy"))
    t.add_row("file_size", f"{r.file_size_bytes / (1024 * 1024):.2f} MB")
    console.print(t)


@app.command("transcribe")
def transcribe_cmd(
    input: str = typer.Option(..., "--input", "-i", help="Audio file (wav) to transcribe"),
    output: str = typer.Option(..., "--output", "-o", help="Output directory"),
    stem_kind: str = typer.Option(
        "vocals", "--stem-kind",
        help="vocals | piano | guitar | bass | other | instrumental | mix",
    ),
) -> None:
    """Stage 9a: audio -> MIDI via basic-pitch."""
    r = transcribe(Path(input), Path(output), stem_kind=stem_kind)  # type: ignore[arg-type]
    t = Table(title=f"Transcribe result - {stem_kind}", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("midi", str(r.midi_path))
    if r.note_events_csv:
        t.add_row("csv", str(r.note_events_csv))
    t.add_row("notes", str(r.note_count))
    t.add_row("duration", f"{r.duration_sec:.2f} s")
    t.add_row("elapsed", f"{r.elapsed_sec:.2f} s")
    console.print(t)


@app.command("score")
def score_cmd(
    input: str = typer.Option(..., "--input", "-i", help="MIDI file (.mid)"),
    output: str = typer.Option(..., "--output", "-o", help="Output directory"),
    title: str = typer.Option("", "--title", help="Score title"),
    svg: bool = typer.Option(True, "--svg/--no-svg", help="Also render an SVG preview"),
) -> None:
    """Stage 9b: MIDI -> MusicXML (+ optional SVG via Verovio)."""
    r = build_score(Path(input), Path(output), title=title, write_svg=svg)
    t = Table(title=f"Score result - {r.title}", show_header=False)
    t.add_column("Field", style="bold")
    t.add_column("Value", overflow="fold")
    t.add_row("musicxml", str(r.musicxml_path))
    t.add_row("svg", str(r.svg_path) if r.svg_path else "(skipped)")
    t.add_row("parts", str(r.parts))
    t.add_row("measures", str(r.measures))
    console.print(t)


@app.command("formats")
def formats_cmd() -> None:
    """Show the supported output format / sr / bit-depth matrix."""
    t = Table(title="Supported output formats")
    t.add_column("Format")
    t.add_column("Sample rates (Hz)")
    t.add_column("Bit depths")
    for fmt in ("wav", "flac", "aiff", "mp3", "aac"):
        srs = ", ".join(str(s) for s in sorted(ALLOWED_SR[fmt]))
        bits = ", ".join(sorted(ALLOWED_BIT_DEPTHS[fmt])) or "lossy"
        t.add_row(fmt, srs, bits)
    console.print(t)


@app.command("pipeline")
def pipeline_cmd(
    input: str = typer.Option(..., "--input", "-i", help="URL or file path"),
    job_id: str = typer.Option(None, "--job-id", help="Override job id"),
    summary_json: bool = typer.Option(False, "--json", help="Print machine-readable summary"),
) -> None:
    """Run stages 1 + 2 (ingest then decode) end-to-end."""
    jid = job_id or new_job_id()
    ensure_dir(settings.uploads_dir)
    ing = ingest(input, jid)
    _print_ingest(ing)
    work_dir = settings.work_dir / jid
    dec = decode_to_master(ing.source, work_dir, source_sr=ing.sample_rate, job_id=jid)
    _print_decode(dec)

    if summary_json:
        console.print_json(json.dumps({
            "job_id": jid,
            "ingest": {
                "kind": ing.kind, "origin": ing.origin, "source": str(ing.source),
                "container": ing.container, "audio_codec": ing.audio_codec,
                "sample_rate": ing.sample_rate, "channels": ing.channels,
                "duration_sec": ing.duration_sec,
            },
            "decode": {
                "master": str(dec.master),
                "sample_rate": dec.sample_rate,
                "duration_sec": dec.duration_sec,
            },
        }))


if __name__ == "__main__":
    app()
