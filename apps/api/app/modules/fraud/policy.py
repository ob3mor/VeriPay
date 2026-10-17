"""Policy loader for the EVC engine.

The policy (``policy_v1.json``) carries the feature weights, thresholds,
severity factors and the machine-enforced floors — and a ``policy_version``
that is stored ON every assessment (inside ``fraud_assessments.evc`` and
``feature_snapshot``), so any score can be traced to the exact policy that
produced it.

Governance: the business-invariant floors (ARCHITECTURE §8.4/§8.5) are
hardcoded invariants below and CROSS-CHECKED against the policy at load time.
A policy file that weakens them (e.g. lowers the ``bank_account_unverified``
floor below ``high`` or raises the ``missing_evidence`` cap above ``medium``)
is refused — the invariants are not editable through configuration.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.errors import AppError, ErrorCode

POLICY_PATH = Path(__file__).with_name("policy_v1.json")

# The severity lattice used for ordering and floor/cap clamping.
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# --- Hard invariants (docs/ARCHITECTURE.md §8; NOT policy-editable) ----------
# R5: the pay-to-destination finding may never be downgraded below high.
INVARIANT_SEVERITY_FLOORS = {"bank_account_unverified": "high"}
# R4: absence is never proof of fraud — missing-evidence severity is capped.
INVARIANT_SEVERITY_CAPS = {"missing_evidence": "medium"}
# Overrides that force a human review no matter what the score says.
INVARIANT_OVERRIDE_MINIMUM_RESULT = {
    "bank_account_unverified": "review_required",
    "unknown_vendor": "review_required",
    "ocr_uncertain": "review_required",
}
# §8 forcing rules: these signal types set invoices.status = needs_review.
# missing_evidence / unverified_input / field_provenance_conflict are
# informational (no forcing — "humans decide whether to look").
INVARIANT_FORCING_SIGNALS = {
    "duplicate_candidate": True,
    "amount_mismatch": True,
    "bank_account_unverified": True,
    "unknown_vendor": True,
    "ocr_uncertain": True,
}
# Criticality: this many DISTINCT high-severity confirmed discrepancies force
# risk_level = critical (R6 auto-case). Kept as a constant so a policy edit
# cannot silence the R6 trigger.
INVARIANT_CRITICAL_MIN_HIGH_SIGNALS = 2

RESULT_STATES = ("no_material_discrepancies", "review_required", "high_risk_discrepancy")
# result-state rank used for max()/clamping everywhere.
RESULT_ORDER = {name: i for i, name in enumerate(RESULT_STATES)}

FEATURE_KEYS = (
    "bank_account_consistency",
    "identity_consistency",
    "duplicate_indicators",
    "po_mismatch",
    "historical_anomalies",
    "untrusted_source_indicators",
)

UNCERTAINTY_STATES = ("verified_agreement", "confirmed_discrepancy", "insufficient_evidence")


@dataclass(frozen=True)
class Policy:
    """Immutable view of the loaded policy file."""

    raw: dict

    @property
    def policy_version(self) -> str:
        return self.raw["policy_version"]

    def weight(self, feature: str) -> float:
        return float(self.raw["weights"][feature])

    @property
    def weights(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.raw["weights"].items()}

    @property
    def review_threshold(self) -> float:
        return float(self.raw["thresholds"]["review_required"])

    @property
    def high_threshold(self) -> float:
        return float(self.raw["thresholds"]["high_risk"])

    def severity_factor(self, severity: str) -> float:
        return float(self.raw["severity_factors"][severity])

    def default_severity(self, signal: str) -> str:
        return self.raw["signals"]["default_severities"][signal]

    def floor_for(self, signal: str) -> str | None:
        return self.raw["signals"]["severity_floors"].get(signal)

    def cap_for(self, signal: str) -> str | None:
        return self.raw["signals"]["severity_caps"].get(signal)

    def override_minimum_result(self, signal: str) -> str | None:
        return self.raw["signals"]["override_minimum_result"].get(signal)

    def forcing_signals(self) -> dict[str, bool]:
        """§8 forcing map: signal types whose presence sets needs_review."""
        return {
            k: bool(v)
            for k, v in self.raw["signals"]["forcing"].items()
            if v
        }

    @property
    def duplicates(self) -> dict:
        return self.raw["duplicate_detection"]

    @property
    def history(self) -> dict:
        return self.raw["history"]

    @property
    def critical_min_high_signals(self) -> int:
        return int(self.raw["critical_rule"]["min_high_signals"])


def _validate(policy: dict) -> None:
    """Refuse any policy that is malformed or weakens a hard invariant."""
    try:
        weights = policy["weights"]
        thresholds = policy["thresholds"]
        factors = policy["severity_factors"]
        signals = policy["signals"]
    except (KeyError, TypeError) as exc:
        raise AppError(
            ErrorCode.INTERNAL,
            f"Fraud policy {POLICY_PATH.name} is missing a required section ({exc}).",
        ) from exc

    if set(weights) != set(FEATURE_KEYS):
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy weights must define exactly the six EVC features.",
        )
    if any(not (0.0 < float(v) <= 100.0) for v in weights.values()):
        raise AppError(ErrorCode.INTERNAL, "Fraud policy weights must be in (0, 100].")
    if abs(sum(float(v) for v in weights.values()) - 100.0) > 1e-9:
        raise AppError(ErrorCode.INTERNAL, "Fraud policy weights must sum to 100.")

    review = float(thresholds["review_required"])
    high = float(thresholds["high_risk"])
    if not (0.0 < review < high <= 100.0):
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy thresholds must satisfy 0 < review_required < high_risk <= 100.",
        )

    if set(factors) != {"low", "medium", "high"}:
        raise AppError(ErrorCode.INTERNAL, "Fraud policy severity_factors must be low/medium/high.")
    if not (0.0 <= factors["low"] <= factors["medium"] <= factors["high"] <= 1.0):
        raise AppError(
            ErrorCode.INTERNAL, "Fraud policy severity_factors must be monotonic in [0, 1]."
        )

    # --- invariant cross-checks (the point of loading through this module) ---
    if signals.get("severity_floors") != INVARIANT_SEVERITY_FLOORS:
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy severity floors diverge from the hardcoded invariants "
            "(bank_account_unverified floor high — ARCHITECTURE §8.5); policy refused.",
        )
    if signals.get("severity_caps") != INVARIANT_SEVERITY_CAPS:
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy severity caps diverge from the hardcoded invariants "
            "(missing_evidence cap medium — ARCHITECTURE §8.4); policy refused.",
        )
    if signals.get("override_minimum_result") != INVARIANT_OVERRIDE_MINIMUM_RESULT:
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy override minimum results diverge from the hardcoded "
            "invariants; policy refused.",
        )
    if signals.get("forcing") != INVARIANT_FORCING_SIGNALS:
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy forcing map diverges from the §8 forcing rules "
            "(duplicate_candidate/amount_mismatch/bank_account_unverified/"
            "unknown_vendor/ocr_uncertain force review); policy refused.",
        )
    if int(policy["critical_rule"]["min_high_signals"]) != INVARIANT_CRITICAL_MIN_HIGH_SIGNALS:
        raise AppError(
            ErrorCode.INTERNAL,
            "Fraud policy critical_rule diverges from the hardcoded R6 trigger; policy refused.",
        )


@lru_cache
def load_policy() -> Policy:
    """Load and validate the policy once per process. Tests can call
    ``reload_policy()`` after changing settings/files."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    _validate(policy)
    return Policy(raw=policy)


def reload_policy() -> Policy:
    load_policy.cache_clear()
    return load_policy()
