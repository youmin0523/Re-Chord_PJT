"""Pin the robust confidence-token parser + stripper.

The LLM emits <confidence> in several formats; the parser must handle
all of them and never crash on malformed input. The stripper must remove
the token cleanly from display text.
"""

from __future__ import annotations

import pytest

from backend.app.chat.openai_client import (
    parse_confidence,
    strip_confidence_token,
)


@pytest.mark.parametrize("text,expected", [
    ("answer <confidence>0.85</confidence>", 0.85),
    ("<confidence>0.9999</confidence>", 0.9999),       # multi-digit
    ("<confidence>85%</confidence>", 0.85),            # percent form
    ("<confidence> .7 </confidence>", 0.7),            # leading-dot + spaces
    ("<confidence>1</confidence>", 1.0),               # bare integer 1
    ("<confidence>85</confidence>", 0.85),             # bare int >1 → /100
    ("<CONFIDENCE>0.5</CONFIDENCE>", 0.5),             # case-insensitive
    # Last token wins when multiple appear.
    ("<confidence>0.3</confidence> ... <confidence>0.9</confidence>", 0.9),
])
def test_parse_confidence_formats(text, expected):
    got = parse_confidence(text)
    assert got == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("text", [
    "",
    "no token here",
    "<confidence></confidence>",
    "<confidence>.</confidence>",
    "<confidence>abc</confidence>",
])
def test_parse_confidence_returns_none_on_missing_or_garbage(text):
    assert parse_confidence(text) is None


def test_parse_confidence_clamps_to_unit_range():
    assert parse_confidence("<confidence>250%</confidence>") == 1.0
    assert parse_confidence("<confidence>0.0</confidence>") == 0.0


def test_strip_confidence_token_removes_markup():
    text = "이 곡은 '주 은혜임을' 입니다. <confidence>0.92</confidence>"
    stripped = strip_confidence_token(text)
    assert "<confidence>" not in stripped
    assert "0.92" not in stripped
    assert "주 은혜임을" in stripped


def test_strip_confidence_token_noop_when_absent():
    text = "그냥 일반 답변입니다."
    assert strip_confidence_token(text) == text
