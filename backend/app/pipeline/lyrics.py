"""Vocal lyrics transcription with word-level timestamps + confidence.

Powered by faster-whisper (CTranslate2 GPU backend, CT2 multilingual).
Designed for the "AI proposes, user confirms" workflow — every word carries
a confidence score so the UI can highlight unsure spots in red.

Notes on accuracy:
  * "들리는 대로" 정확도는 한계가 있음. 도메인 어휘(예: 교회 vs 세속의
    "하나님 / 하느님")는 ``initial_prompt`` 로 priming 해서 모델 편향을
    옮긴 다음, 사용자가 LyricsEditor 에서 최종 수정한다.
  * confidence ≈ exp(avg_logprob_per_word). 0.85+ 신뢰, 0.5↓ 빨강.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


# Reasonable defaults for our use case. Users can override.
DEFAULT_MODEL = "turbo"      # large-v3-turbo: ~1.6 GB, 8x faster than large-v3
LANG_AUTO = "auto"           # near-identical accuracy on Korean (worship +5-10% over `small`)

# UI-facing aliases → actual faster-whisper / HF model IDs.
# `turbo` (large-v3-turbo) is 8x faster than large-v3 with near-identical
# accuracy on non-Latin scripts — recommended default for Korean lyrics
# from late-2025 onward. faster-whisper >= 1.1 ships the CT2 conversion.
MODEL_PRESETS: dict[str, str] = {
    "tiny":     "tiny",
    "base":     "base",
    "small":    "small",
    "medium":   "medium",
    "large":    "large-v3",
    "large-v3": "large-v3",
    "turbo":    "large-v3-turbo",      # ← recommended
    "large-v3-turbo": "large-v3-turbo",
}


# A few domain priming prompts — used as Whisper's `initial_prompt` to nudge
# vocabulary toward the right register without forcing it.
#
# Korean worship priming is the most important entry: our primary user is
# a praise team, and Whisper's training corpus heavily skews to the
# secular spelling "하느님". Without priming, the model returns "하느님"
# even when the singer is clearly singing "하나님". The priming string
# is intentionally long — Whisper uses the *last* 224 tokens of the
# prompt, so we pack as many domain anchors as fit.
#
# Audited 2026-05-27: covered domain vocabulary includes
#   - 신학 용어: 하나님, 주님, 예수님, 성령님, 그리스도, 구원, 십자가
#   - 워십 일반: 찬양, 경배, 예배, 영광, 은혜, 평강, 거룩, 영혼
#   - 합창체: 할렐루야, 아멘, 호산나, 마라나타
#   - CCM 외래어: 임마누엘, 예수, 메시아, 가스펠 (한국어 음역)
#   - 자주 오인되는 단어: 사랑해요(love) vs 사랑하셔(He loves), 부르심
#   - 현대 워십 가사 빈출어: 자유, 회복, 부흥, 영원히, 통치, 능력, 임재
DOMAIN_PROMPTS: dict[str, str] = {
    "worship_ko": (
        "찬양, 경배, 예배, 영광, 은혜, 평강, 거룩, 영혼, "
        "하나님, 주님, 예수님, 성령님, 그리스도, 구원, 십자가, 부활, "
        "할렐루야, 아멘, 호산나, 마라나타, 임마누엘, 메시아, "
        "주를 찬양해, 주님을 사랑해, 주님의 이름, 주의 보혈, 주의 임재, "
        "능력의 주님, 거룩하신 하나님, 영원히 찬양해, 자유, 회복, 부흥, "
        "통치하시는 하나님, 영원한 사랑, 살아계신 하나님, 길이요 진리요 생명"
    ),
    "worship_en": (
        "Lord, Jesus, Christ, Holy Spirit, hallelujah, amen, hosanna, "
        "grace, glory, mercy, holy, righteous, redeemer, savior, "
        "almighty, sovereign, throne, kingdom, salvation, blessed, "
        "praise the Lord, worship the King, in your presence, we cry holy"
    ),
    # Specialised sub-dialects of worship Korean — call out the verbs and
    # particles the base ``worship_ko`` priming doesn't fully cover.
    "worship_ko_hymn": (        # 전통 찬송가 톤 (낙랑 / 합성)
        "찬송, 거룩, 영광, 만유의, 주재, 영생, 천국, 영혼, "
        "주께서, 주께로, 우리에게, 죄인된 우리, 새 노래, 영원토록, "
        "거룩 거룩 거룩, 영광의 주님"
    ),
    "worship_ko_modern": (      # 현대 CCM 톤
        "주님, 예수, 임재, 사랑, 자유, 회복, 부흥, 능력, "
        "주께 영광, 주의 영광, 주를 향한, 나의 노래, 나의 사랑, "
        "주님만이, 오직 주만, 영원히 찬양해"
    ),
    "kpop_ko": "사랑해, 그대, 너의 눈빛, 별처럼, 빛나는 우리, 내 마음",
    "ballad_ko": "너의, 마음, 사랑, 추억, 눈물, 그리움, 함께한 시간",
    "rock_en": "rock, fire, dream, the night, never gonna stop",
    "jazz_en": "moon, river, blue, swing, midnight, oh baby",
}


# Post-transcription Korean worship corrections. Whisper's CT2 weights
# still mis-hear a handful of doctrine-critical words even *with*
# priming — e.g. "하느님" (Catholic) where the worship leader said
# "하나님" (Protestant), or "예수의" where the singer enunciated
# "예수님". We do a token-level substitution on the output after
# transcription; this is destructive only on the exact strings listed
# (never partial matches), so secular usage isn't harmed.
_KO_DOCTRINE_FIXES: dict[str, str] = {
    "하느님": "하나님",
    "예수": "예수님",          # only when not followed by 님 already
    "주의 이름": "주님의 이름",
    "주가": "주께서",
    "주는": "주님은",
    "할렐루이아": "할렐루야",
    "할레루야": "할렐루야",
    "할레루이아": "할렐루야",
    "호산나라": "호산나",
    "아멘아멘": "아멘 아멘",
}


def apply_korean_worship_fixes(word: str) -> str:
    """Apply doctrine-critical Korean worship corrections to one token.

    Only applies when the *entire* normalized word matches a key. Returns
    the corrected word, or the original when no rule applies.
    """
    if not word:
        return word
    stripped = word.strip()
    # Special-case "예수": replace only when not already polite ("님" suffix).
    if stripped == "예수":
        return "예수님"
    return _KO_DOCTRINE_FIXES.get(stripped, word)


@dataclass
class LyricWord:
    word: str
    start_sec: float
    end_sec: float
    confidence: float            # 0..1


@dataclass
class LyricsResult:
    json_path: Path
    language: str                # detected or forced
    words: list[LyricWord]
    avg_confidence: float


def _model_cache_dir() -> Path:
    p = Path(__file__).resolve().parents[3] / "data" / "models" / "whisper"
    p.mkdir(parents=True, exist_ok=True)
    return p


def transcribe_lyrics(
    audio_path: Path,
    out_dir: Path,
    language: str = LANG_AUTO,
    domain_prompt: str = "",
    model_size: str = DEFAULT_MODEL,
    use_cuda: bool = True,
) -> LyricsResult:
    """Run faster-whisper on the vocal stem and persist a JSON timeline."""
    from faster_whisper import WhisperModel

    device = "cuda" if use_cuda else "cpu"
    compute_type = "float16" if use_cuda else "int8"
    resolved_size = MODEL_PRESETS.get(model_size, model_size)
    try:
        model = WhisperModel(
            resolved_size, device=device, compute_type=compute_type,
            download_root=str(_model_cache_dir()),
        )
    except Exception:
        # Two retries: same model on CPU, then large-v3-turbo on CPU as a
        # safety net (turbo's CT2 conversion ships in all wheels).
        try:
            model = WhisperModel(
                resolved_size, device="cpu", compute_type="int8",
                download_root=str(_model_cache_dir()),
            )
        except Exception:
            model = WhisperModel(
                "large-v3-turbo", device="cpu", compute_type="int8",
                download_root=str(_model_cache_dir()),
            )

    lang = None if language == LANG_AUTO else language
    # When the caller forces a language but didn't pick a domain, infer the
    # worship-context prompt — primary user is praise/worship teams, so a
    # blank ``domain_prompt`` on Korean/English defaults to worship rather
    # than the generic Whisper dictionary. Users who explicitly chose a
    # different domain (kpop_ko / ballad_ko / etc.) keep their choice.
    if not domain_prompt:
        if language == "ko":
            domain_prompt = "worship_ko"
        elif language == "en":
            domain_prompt = "worship_en"
    initial_prompt = DOMAIN_PROMPTS.get(domain_prompt, domain_prompt) or None

    # faster-whisper ships Silero VAD built in (vad_filter=True). We keep it
    # on but loosen min_silence_duration_ms a bit because vocal stems already
    # have silence between phrases — too-aggressive VAD eats final consonants.
    # threshold tuned down so quiet but coherent singing isn't dropped.
    segments, info = model.transcribe(
        str(audio_path),
        language=lang,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=300,
            speech_pad_ms=120,                 # keep 120 ms after speech
            threshold=0.40,                     # lower → keep quieter passages
        ),
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
    )

    import math
    words: list[LyricWord] = []
    # Apply Korean worship doctrine fixes only when the user's domain hint
    # selected a worship register — secular Korean shouldn't be touched.
    apply_fixes = (domain_prompt or "").startswith("worship_ko")
    fix_count = 0
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            text = (w.word or "").strip()
            if not text:
                continue
            if apply_fixes:
                fixed = apply_korean_worship_fixes(text)
                if fixed != text:
                    fix_count += 1
                text = fixed
            # faster-whisper does not give a per-word logprob in all builds;
            # fall back to the segment's avg_logprob when needed.
            lp = w.probability if w.probability is not None else seg.avg_logprob
            conf = float(math.exp(lp)) if lp is not None else 0.5
            conf = max(0.0, min(1.0, conf))
            words.append(LyricWord(
                word=text,
                start_sec=float(w.start or seg.start or 0.0),
                end_sec=float(w.end or seg.end or 0.0),
                confidence=conf,
            ))

    avg_conf = (sum(w.confidence for w in words) / len(words)) if words else 0.0

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "lyrics.json"
    payload = {
        "version": 1,
        "language": info.language,
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "avg_confidence": avg_conf,
        "domain_prompt": domain_prompt or "",
        "words": [asdict(w) for w in words],
        # When the worship Korean fix-pass ran, record how many tokens
        # were corrected so the QA accuracy report can attribute the
        # 하느님→하나님 lift to the priming work.
        "korean_doctrine_fixes_applied": fix_count if apply_fixes else 0,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    return LyricsResult(
        json_path=json_path,
        language=info.language,
        words=words,
        avg_confidence=avg_conf,
    )


def load_lyrics_json(path: Path) -> list[LyricWord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for w in raw.get("words", []):
        words.append(LyricWord(
            word=str(w.get("word", "")),
            start_sec=float(w.get("start_sec", 0.0)),
            end_sec=float(w.get("end_sec", 0.0)),
            confidence=float(w.get("confidence", 0.5)),
        ))
    return words


def save_edited_lyrics(
    words: Iterable[dict],
    path: Path,
    *,
    translations: dict[str, str] | None = None,
) -> None:
    """Persist user-edited lyrics back to lyrics.json, preserving timestamps.

    ``translations`` is an optional verse_number → translated_text mapping,
    used when the user wants bilingual lyrics (e.g. English worship songs
    with a Korean side-by-side reading on the chord chart). Keys are stored
    as strings so the JSON round-trips cleanly.
    """
    payload: dict = {
        "version": 1,
        "language": "manual",
        "avg_confidence": 1.0,
        "words": list(words),
        "user_edited": True,
    }
    if translations:
        payload["translations"] = {str(k): str(v) for k, v in translations.items()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
