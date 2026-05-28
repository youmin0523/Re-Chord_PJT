"""Static descriptor for UI selectors (formats, modes, models)."""

from __future__ import annotations

from fastapi import APIRouter

from ..pipeline.encode import ALLOWED_BIT_DEPTHS, ALLOWED_SR
from ..pipeline.separate import MODELS as MODEL_FILES


router = APIRouter(prefix="/formats", tags=["formats"])


@router.get("")
async def formats() -> dict:
    """Everything the frontend needs to render Export + Mode pickers."""
    return {
        "output_formats": [
            {
                "name": fmt,
                "sample_rates": sorted(ALLOWED_SR[fmt]),
                "bit_depths": sorted(ALLOWED_BIT_DEPTHS[fmt]) or ["lossy"],
            }
            for fmt in ("wav", "flac", "aiff", "mp3", "aac")
        ],
        "modes": [
            {"id": "quick_mr", "label": "Quick MR",
             "desc": "Vocal -> instrumental, minimal options.",
             "default_models": ["mdx23c_instvoc_hq"]},
            {"id": "karaoke", "label": "Karaoke",
             "desc": "MR + key/tempo control + chord/section markers.",
             "default_models": ["mdx23c_instvoc_hq", "bs_roformer_1297",
                                "htdemucs_ft", "melband_kim_inst_v2"]},
            {"id": "stems", "label": "Stems",
             "desc": "6-stem multi-track export (vocals/drums/bass/guitar/piano/other).",
             "default_models": ["htdemucs_6s"]},
            {"id": "pro", "label": "Pro",
             "desc": "All knobs exposed: model picker, ensemble method, fine pitch/tempo, formant.",
             "default_models": ["mdx23c_instvoc_hq", "bs_roformer_1297",
                                "htdemucs_ft", "melband_kim_inst_v2"]},
        ],
        "models": [
            {"alias": alias, "filename": filename}
            for alias, filename in MODEL_FILES.items()
        ],
        "ensemble_methods": ["min", "mag_avg", "mean"],
    }
