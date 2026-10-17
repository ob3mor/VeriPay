"""Server-side revocation registry for access tokens (sign-out support).

Phase 1 tokens are stateless HS256 JWTs; ``POST /api/v1/auth/logout`` revokes
the presented token's ``jti`` claim here until that token's ``exp``, and
``tenancy.deps.get_current_user`` consults this registry on every
authenticated request. Sign-out therefore invalidates a stolen or leaked
bearer token server-side instead of only clearing the client's copy.

Known limitation, deliberate for Phase 1: state is **per-process** and lost on
restart. The API deploys as a single instance on the free-tier profiles, so a
revoked token cannot be re-presented to a different replica; a multi-instance
deployment must swap this for a shared store (Redis/DB) — this module is the
seam. Entries self-prune as their expiry passes, so the map stays bounded.
"""

import time
from threading import Lock


class TokenRevocationRegistry:
    """Remembers revoked ``jti`` values until the token's expiry passes."""

    def __init__(self) -> None:
        self._expires_at: dict[str, float] = {}
        self._lock = Lock()

    def revoke(self, jti: str, expires_at: float) -> None:
        """Revoke ``jti`` until the Unix timestamp ``expires_at``.

        Tokens that already expired are ignored — they can never be presented
        again, so there is nothing to remember.
        """
        now = time.time()
        with self._lock:
            if expires_at <= now:
                return
            self._expires_at[jti] = max(expires_at, self._expires_at.get(jti, 0.0))

    def is_revoked(self, jti: str) -> bool:
        now = time.time()
        with self._lock:
            if not self._expires_at:
                return False
            # Opportunistic sweep: drop expired entries so the map stays small.
            for stale in [j for j, exp in self._expires_at.items() if exp <= now]:
                del self._expires_at[stale]
            return jti in self._expires_at

    def reset(self) -> None:
        """Forget all revocations (test isolation)."""
        with self._lock:
            self._expires_at.clear()


# Process-wide singleton used by the auth route and tenancy dependencies.
revoked_tokens = TokenRevocationRegistry()
