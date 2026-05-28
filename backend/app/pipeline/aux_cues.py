"""AUX/second-keyboard patch cues per measure range.

Worship / live performance workflow: the AUX player (보통 키보드2 또는
secondary synth)는 곡 흐름에서 음색이 자주 바뀝니다 — Intro Organ, Chorus
Pad, Bridge Synth Lead 처럼. Multitracks Playback 류의 패치 큐 시트를
우리가 직접 채워 악보 위에 표기합니다.

데이터 구조는 단순:
    [
      {start_measure, end_measure, patch, note},
      ...
    ]

자동 음색 추정은 일반적으로 부정확하므로 v1에서는 **사용자 직접 입력**.
나중에 spectral classifier를 붙여 초안을 제안하고 사용자가 보정하는
방향으로 확장 가능.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


Patch = Literal[
    "organ", "pad", "synth_lead", "string", "brass", "bell",
    "piano", "epiano", "choir", "guitar_atmos", "fx", "silent", "custom",
]

# Korean labels for the UI (frontend mirrors this list).
PATCH_LABEL_KO: dict[str, str] = {
    "organ": "오르간",
    "pad": "패드",
    "synth_lead": "신스 리드",
    "string": "스트링",
    "brass": "브라스",
    "bell": "벨",
    "piano": "피아노",
    "epiano": "일렉 피아노",
    "choir": "콰이어",
    "guitar_atmos": "기타 앰비언스",
    "fx": "FX",
    "silent": "쉼표",
    "custom": "직접 입력",
}


@dataclass
class AuxCue:
    start_measure: int
    end_measure: int
    patch: str
    note: str = ""              # free-text annotation (예: "warm pad, light mod")


def write_aux_cues(cues: list[AuxCue] | list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    normalized: list[dict] = []
    for c in cues:
        if isinstance(c, AuxCue):
            normalized.append(asdict(c))
        elif isinstance(c, dict):
            normalized.append({
                "start_measure": int(c.get("start_measure", 1)),
                "end_measure": int(c.get("end_measure", c.get("start_measure", 1))),
                "patch": str(c.get("patch", "pad")),
                "note": str(c.get("note", "")),
            })
    out_path.write_text(
        json.dumps({"version": 1, "cues": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def load_aux_cues(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("cues") or [])


def attach_aux_cues_to_score(score, cues: list[dict]) -> None:
    """Add ``[AUX: ...]`` rehearsal-mark style text above measure N of the
    top staff. Verovio renders it as a system-text annotation."""
    if not cues:
        return
    try:
        from music21 import expressions
    except Exception:
        return
    try:
        parts = list(score.parts) or [score]
    except AttributeError:
        parts = [score]
    if not parts:
        return
    top = parts[0]

    # Index measures so we can attach cues to the right one.
    measures = list(top.getElementsByClass("Measure"))
    if not measures:
        return

    for c in cues:
        m_idx = max(1, int(c.get("start_measure", 1)))
        if m_idx > len(measures):
            continue
        label_ko = PATCH_LABEL_KO.get(c.get("patch", ""), c.get("patch", ""))
        note = (c.get("note") or "").strip()
        text = f"AUX · {label_ko}" + (f" — {note}" if note else "")
        try:
            te = expressions.TextExpression(text)
            te.placement = "above"
            te.style.fontWeight = "bold"
            measures[m_idx - 1].insert(0, te)
        except Exception:
            continue
