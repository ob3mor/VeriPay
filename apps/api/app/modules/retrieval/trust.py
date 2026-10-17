"""Trust tiers — the explicit score multiplier over retrieval results.

The tier ladder (Prompt-03): approved/verified > previously reviewed >
unverified upload > stale > missing. A tier NEVER hides a record from search
and NEVER rewrites its content — it only scales the fused retrieval score, so
an unverified upload cannot outrank the human-approved vendor master on equal
retrieval evidence, and can never be *promoted into* it (merging stays a
human confirm flow; R3/R5 invariants).

Tiers are computed at index build time from the source rows' own state
(verification status, human review records) — never from the match score.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from app.core.config import get_settings


class TrustTier(StrEnum):
    """The five-tier ladder; the ORDER of members is the trust order."""

    TRUSTED_REGISTRY = "trusted_registry"  # human-approved registry records
    PREVIOUSLY_REVIEWED = "previously_reviewed"  # touched by human review
    UNVERIFIED_UPLOAD = "unverified_upload"  # machine output, not yet reviewed
    STALE = "stale"  # trusted/old records past the freshness horizon
    MISSING = "missing"  # an absent relationship (graph gaps only)

    @property
    def multiplier(self) -> float:
        """Explicit, inspectable score multiplier — never tuned per-request."""
        return TRUST_MULTIPLIERS[self]


# Explicit, test-asserted multipliers. Nothing may write these from request
# data; the ladder is code, not configuration.
TRUST_MULTIPLIERS: dict["TrustTier", float] = {
    TrustTier.TRUSTED_REGISTRY: 1.0,
    TrustTier.PREVIOUSLY_REVIEWED: 0.9,
    TrustTier.UNVERIFIED_UPLOAD: 0.7,
    TrustTier.STALE: 0.5,
    TrustTier.MISSING: 0.3,
}

# Tiers that decay to ``stale`` when the record has not been touched within
# the freshness horizon. Unverified uploads are already below the line.
_STALE_DECAYABLE = (TrustTier.TRUSTED_REGISTRY, TrustTier.PREVIOUSLY_REVIEWED)


def effective_tier(base: TrustTier, updated_at: datetime | None) -> TrustTier:
    """Downgrade a decayable tier to STALE past the freshness horizon.

    ``updated_at`` is the record's own ``record_version`` — staleness is a
    property of the record, never of the query.
    """
    if base not in _STALE_DECAYABLE or updated_at is None:
        return base
    settings = get_settings()
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    horizon = datetime.now(timezone.utc) - timedelta(days=settings.retrieval_stale_days)
    if updated_at < horizon:
        return TrustTier.STALE
    return base


def trust_score(score: float, tier: TrustTier) -> float:
    """Fused retrieval score scaled by the tier multiplier."""
    return score * tier.multiplier
