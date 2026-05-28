"""NumPy compatibility shim for legacy SOTA libraries (madmom, allin1, ...).

NumPy 1.20+ removed the deprecated scalar aliases ``np.float`` / ``np.int`` /
``np.bool`` / ``np.object`` / ``np.complex`` / ``np.long`` / ``np.unicode`` /
``np.str`` (now raise AttributeError). madmom 0.16.1 — last released 2018 —
uses them in 24+ files across audio/features/evaluation/utils. Patching each
call site is fragile and gets undone whenever madmom is reinstalled.

We restore the aliases by setting them on ``numpy`` itself before any legacy
module imports. Each alias points at the equivalent Python builtin (which is
exactly what NumPy used to do internally — the deprecation was purely about
removing redundancy, not about behavior).

Import this module **before** importing madmom, autochord, or allin1.
``backend.app.pipeline.__init__`` does this transparently for the worker
processes that orchestrate the pipeline.
"""

from __future__ import annotations

import numpy as _np


_LEGACY_ALIASES: dict[str, type] = {
    "float": float,
    "int": int,
    "bool": bool,
    "object": object,
    "complex": complex,
    "long": int,
    "unicode": str,
    "str": str,
}

for _name, _builtin in _LEGACY_ALIASES.items():
    if not hasattr(_np, _name):
        setattr(_np, _name, _builtin)
