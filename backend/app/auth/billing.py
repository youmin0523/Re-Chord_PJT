"""Subscription tiers + quota enforcement (Phase B).

Phase A returns ``Quota.unlimited()`` for every user. Phase B reads
the tier from the user's subscription state (DB row populated by
billing webhook) and applies the per-tier limits.

Tier matrix (initial proposal — adjust before launch):

    Free      :  3 jobs/day  · 4 min max · Quick MR + Karaoke only
    Studio    : 50 jobs/day  · 15 min max · all modes + score/lyrics
    Pro       : unlimited    · 30 min max · + 5.1 surround + DSD + Pro models
    Enterprise: unlimited    · 60 min max · + multi-tenant + audit log
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .auth import User


TIER_FREE = "free"
TIER_STUDIO = "studio"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"


@dataclass
class Quota:
    tier: str
    max_jobs_per_day: int            # -1 = unlimited
    max_duration_sec: int            # per-job cap
    allowed_modes: tuple[str, ...]
    allow_premium_models: bool        # SOTA Pro models from HF
    allow_premium_outputs: bool       # 5.1 surround / DSD / autotune

    @classmethod
    def unlimited(cls) -> "Quota":
        return cls(
            tier="phase_a",
            max_jobs_per_day=-1,
            max_duration_sec=60 * 60,    # 1 hour
            allowed_modes=("quick_mr", "karaoke", "stems", "pro"),
            allow_premium_models=True,
            allow_premium_outputs=True,
        )

    @classmethod
    def for_tier(cls, tier: str) -> "Quota":
        if tier == TIER_FREE:
            return cls(
                tier=tier, max_jobs_per_day=3, max_duration_sec=4 * 60,
                allowed_modes=("quick_mr", "karaoke"),
                allow_premium_models=False, allow_premium_outputs=False,
            )
        if tier == TIER_STUDIO:
            return cls(
                tier=tier, max_jobs_per_day=50, max_duration_sec=15 * 60,
                allowed_modes=("quick_mr", "karaoke", "stems", "pro"),
                allow_premium_models=False, allow_premium_outputs=False,
            )
        if tier == TIER_PRO:
            return cls(
                tier=tier, max_jobs_per_day=-1, max_duration_sec=30 * 60,
                allowed_modes=("quick_mr", "karaoke", "stems", "pro"),
                allow_premium_models=True, allow_premium_outputs=True,
            )
        if tier == TIER_ENTERPRISE:
            return cls.unlimited()
        return cls(  # safety net
            tier="unknown", max_jobs_per_day=1, max_duration_sec=4 * 60,
            allowed_modes=("quick_mr",),
            allow_premium_models=False, allow_premium_outputs=False,
        )


def get_quota(user: User) -> Quota:
    """Resolve the user's effective quota."""
    # Phase A: every authenticated context gets unlimited.
    if not os.environ.get("AUTH_PROVIDER"):
        return Quota.unlimited()
    if user.is_guest:
        return Quota.for_tier(TIER_FREE)
    # Phase B: would read from DB:
    #   row = await session.get(Subscription, user.id)
    #   return Quota.for_tier(row.tier)
    # Until that DB lookup is wired we honour AUTH_PROVIDER but stay free.
    return Quota.for_tier(TIER_FREE)
