"""Legal docs API — serves the canonical markdown from ``docs/legal/``.

The signup-consent UI links to ``/legal/terms``, ``/legal/privacy``, and
``/legal/copyright`` so users can review what they're agreeing to. To
keep markdown as the single source of truth (no copy-paste drift between
markdown and a separate React page) we serve the .md content via this
read-only endpoint; the frontend renders it with react-markdown.

No auth — terms must be readable before sign-in.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status


log = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["legal"])

# Whitelist + slug → filename mapping. Only these IDs are exposed; an
# attacker can't request "../config.py" through this endpoint.
_DOCS = {
    "terms":     "terms_of_service.md",
    "privacy":   "privacy_policy.md",
    "copyright": "copyright_notice.md",
    "consent":   "consent_ui_spec.md",   # dev reference, harmless to expose
}

# docs/legal/ lives at repo root, two levels above backend/app/api/.
_LEGAL_DIR = Path(__file__).resolve().parents[3] / "docs" / "legal"


@router.get("/{doc_id}")
async def get_legal_doc(doc_id: str) -> dict:
    """Return the markdown source of one legal doc by slug.

    Response: ``{ id, filename, markdown, bytes }``.
    """
    filename = _DOCS.get(doc_id)
    if filename is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown legal doc: {doc_id!r}. Valid: {sorted(_DOCS.keys())}",
        )
    path = _LEGAL_DIR / filename
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.error("legal doc missing on disk: %s", path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{filename} not found on disk (deploy/Dockerfile may have skipped docs/)",
        ) from None
    return {
        "id": doc_id,
        "filename": filename,
        "markdown": text,
        "bytes": len(text.encode("utf-8")),
    }


@router.get("")
async def list_legal_docs() -> dict:
    """Discoverable index of available legal docs."""
    return {
        "docs": [
            {"id": k, "filename": v, "url": f"/legal/{k}"}
            for k, v in _DOCS.items()
        ],
    }
