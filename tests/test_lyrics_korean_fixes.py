"""Unit tests for worship Korean doctrine fixes.

The substitution table in lyrics.py is destructive — it must only fire
on whole-word matches, never on partial overlap. This test pins the
behaviour so a careless edit can't accidentally rewrite secular Korean.
"""

from __future__ import annotations

import pytest

from backend.app.pipeline.lyrics import (
    DOMAIN_PROMPTS,
    apply_korean_worship_fixes,
)


@pytest.mark.parametrize("orig,expected", [
    # Doctrine substitutions — must fire.
    ("하느님", "하나님"),
    ("예수",   "예수님"),
    ("할레루야", "할렐루야"),
    ("할레루이아", "할렐루야"),
    ("할렐루이아", "할렐루야"),
    ("호산나라", "호산나"),
    ("아멘아멘", "아멘 아멘"),
    # Idempotent — already canonical.
    ("하나님",   "하나님"),
    ("예수님",   "예수님"),
    ("할렐루야", "할렐루야"),
    # Partial matches must NOT fire (only whole-token replacement).
    ("하느님은", "하느님은"),
    ("예수께서", "예수께서"),
    # Secular Korean untouched.
    ("사랑해",   "사랑해"),
    ("그대",     "그대"),
    ("",         ""),
])
def test_korean_doctrine_fixes(orig, expected):
    assert apply_korean_worship_fixes(orig) == expected


def test_worship_priming_contains_critical_vocabulary():
    """The priming string must mention 하나님 (not 하느님) so Whisper's
    bias shifts in the right direction even before our post-process fires."""
    prompt = DOMAIN_PROMPTS["worship_ko"]
    assert "하나님" in prompt
    assert "하느님" not in prompt
    assert "주님" in prompt
    assert "예수님" in prompt
    assert "할렐루야" in prompt
    assert "아멘" in prompt


def test_worship_priming_variants_exist():
    """Hymn and modern CCM sub-domains must be selectable."""
    assert "worship_ko_hymn" in DOMAIN_PROMPTS
    assert "worship_ko_modern" in DOMAIN_PROMPTS
    # Hymn should mention archaic worship vocabulary.
    assert "찬송" in DOMAIN_PROMPTS["worship_ko_hymn"]
    # Modern should mention contemporary CCM keywords.
    assert "임재" in DOMAIN_PROMPTS["worship_ko_modern"]
