"""Pin the chatbot job-context prompt injection.

The audit found the assistant kept answering from stale analysis after a
user edited the meter/key. We now (a) carry time_signature + transpose +
modulations in the snapshot, and (b) instruct the model to treat the
snapshot as the authoritative *current* state.
"""

from __future__ import annotations

from backend.app.chat.prompts import _job_context_block, build_system_prompt
from backend.app.chat.schemas import JobContextSnapshot


def test_block_empty_when_no_context():
    assert _job_context_block(None) == ""


def test_block_includes_time_signature():
    ctx = JobContextSnapshot(job_id="j1", key_name="G major", bpm=92.0,
                             time_signature="6/8")
    block = _job_context_block(ctx)
    assert "6/8" in block
    assert "G major" in block
    assert "92" in block


def test_block_includes_transpose_and_modulation():
    ctx = JobContextSnapshot(
        job_id="j2", key_name="D major", transpose_semitones=2,
        modulations="마지막 후렴 +1 반음",
    )
    block = _job_context_block(ctx)
    assert "+2" in block
    assert "마지막 후렴" in block


def test_block_instructs_snapshot_authority():
    """The prompt must tell the model to prefer the snapshot over its own
    prior knowledge (the fix for the stale-answer bug)."""
    ctx = JobContextSnapshot(job_id="j3", key_name="C major")
    block = _job_context_block(ctx)
    assert "현재" in block
    assert "우선" in block or "기준" in block


def test_build_system_prompt_embeds_job_block():
    ctx = JobContextSnapshot(job_id="j4", key_name="A minor",
                             time_signature="3/4")
    sys_prompt = build_system_prompt(locale="ko", job_context=ctx)
    assert "A minor" in sys_prompt
    assert "3/4" in sys_prompt


def test_available_stems_surfaced():
    ctx = JobContextSnapshot(job_id="j5",
                             available_stems="vocals, drums, bass, piano")
    block = _job_context_block(ctx)
    assert "vocals" in block and "piano" in block
