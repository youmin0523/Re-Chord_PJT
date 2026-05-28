"""Phase B authentication / billing layer.

Phase A runs guest-mode (no auth, no billing). Phase B activates this
package when ``AUTH_PROVIDER`` env var is set:

  AUTH_PROVIDER=clerk          → Clerk JWT verification (default for SaaS)
  AUTH_PROVIDER=supabase       → Supabase Auth (JWT verification, alternative)
  AUTH_PROVIDER=                → no-op (Phase A guest mode)

All endpoints currently call ``get_current_user()`` which returns a
``GuestUser`` when no provider is configured. When the provider is on,
the same function decodes the bearer JWT, validates against the
provider's JWKS, and returns the resolved user. Endpoint signatures
don't change between phases — this is the whole point.

Billing follows the same pattern: ``billing.get_quota(user)`` returns
the unlimited Phase A quota in guest mode, the user's subscription tier
in Phase B.
"""

from .auth import GuestUser, User, get_current_user, auth_dependency
from .billing import get_quota, Quota

__all__ = [
    "User",
    "GuestUser",
    "get_current_user",
    "auth_dependency",
    "get_quota",
    "Quota",
]
