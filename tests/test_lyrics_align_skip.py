"""Pin the graceful-skip contract for forced_align_words().

When WhisperX isn't installed (the common case on Python 3.11 + no-GPU
machines), forced_align_words MUST return a non-fatal skip payload — never
raise. The orchestrator stores the payload in job.meta and the UI shows
"skipped: whisperx not installed" without failing the run.
"""

from __future__ import annotations

from pathlib import Path


def test_skip_when_words_empty(tmp_path):
    from backend.app.pipeline.lyrics_align import forced_align_words
    rv = forced_align_words([], tmp_path / "no.wav")
    assert rv["aligned"] == 0
    assert "no input" in rv["skipped"]


def test_skip_when_audio_missing(tmp_path):
    from backend.app.pipeline.lyrics_align import forced_align_words

    class W:
        word = "ko"
        start_sec = 0.0
        end_sec = 0.5
        confidence = 0.8

    rv = forced_align_words([W()], tmp_path / "absent.wav")
    assert rv["aligned"] == 0
    assert "no input" in rv["skipped"]


def test_skip_when_whisperx_unavailable(tmp_path):
    """If whisperx isn't installed (likely on this dev env), the function
    must skip with a clear reason instead of raising."""
    from backend.app.pipeline.lyrics_align import (
        forced_align_words, is_whisperx_available,
    )
    # Build a valid (empty-content) wav so audio-missing branch doesn't fire.
    import wave
    p = tmp_path / "tiny.wav"
    with wave.open(str(p), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 22050)        # 1 s of silence

    class W:
        word = "ko"
        start_sec = 0.0
        end_sec = 0.5
        confidence = 0.8

    rv = forced_align_words([W()], p)
    if is_whisperx_available():
        # If the dev machine happens to have whisperx, the test still
        # passes as long as the function didn't raise.
        assert "aligned" in rv
    else:
        assert rv["aligned"] == 0
        assert "whisperx not installed" in rv["skipped"]
