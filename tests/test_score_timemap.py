"""Unit tests for the score timemap extractor — runs without music21 in
the heavy way; uses a minimal duck-typed score object.

Verifies the timemap math (quarterLength → seconds @ given BPM) and
edge cases (missing parts, empty score, fractional measures).
"""

from __future__ import annotations

from backend.app.pipeline.score import _extract_measure_timemap


class _DummyMeasure:
    def __init__(self, ql: float):
        self.duration = type("D", (), {"quarterLength": ql})()


class _DummyPart:
    def __init__(self, measures):
        self._m = measures

    def getElementsByClass(self, _name):
        return self._m


class _DummyScore:
    def __init__(self, parts):
        self.parts = parts


def _score_with_measures(qls):
    return _DummyScore([_DummyPart([_DummyMeasure(q) for q in qls])])


def test_empty_score_returns_empty_list():
    score = _DummyScore([_DummyPart([])])
    assert _extract_measure_timemap(score, bpm=120.0) == []


def test_four_four_at_120_bpm():
    # 4 measures of 4/4 at 120 BPM → each measure = 4 * 0.5s = 2.0s.
    score = _score_with_measures([4, 4, 4, 4])
    tm = _extract_measure_timemap(score, bpm=120.0)
    assert len(tm) == 4
    assert tm[0]["start_sec"] == 0.0
    assert tm[0]["end_sec"] == 2.0
    assert tm[1]["start_sec"] == 2.0
    assert tm[3]["end_sec"] == 8.0


def test_three_four_at_120_bpm():
    # 3/4 at 120 = 1.5s/measure.
    score = _score_with_measures([3, 3])
    tm = _extract_measure_timemap(score, bpm=120.0)
    assert tm[0]["end_sec"] == 1.5
    assert tm[1]["end_sec"] == 3.0


def test_zero_bpm_falls_back_to_120():
    # Defensive: must not divide by zero.
    score = _score_with_measures([4])
    tm = _extract_measure_timemap(score, bpm=0.0)
    assert tm and tm[0]["end_sec"] > 0


def test_no_parts_attribute_returns_empty():
    class _NoParts:
        def getElementsByClass(self, _name):
            return []
    assert _extract_measure_timemap(_NoParts(), bpm=120.0) == []
