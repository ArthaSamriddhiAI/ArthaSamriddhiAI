"""The 9-bucket grid (Section 5.4) and the deterministic investor→bucket mapping.

Buckets are the cross-product of three risk profiles and three time horizons:

    | Risk         | ST       | MT       | LT       |
    |--------------|----------|----------|----------|
    | Conservative | CON_ST   | CON_MT   | CON_LT   |
    | Moderate     | MOD_ST   | MOD_MT   | MOD_LT   |
    | Aggressive   | AGG_ST   | AGG_MT   | AGG_LT   |

The mapping is deterministic and one-to-one. An investor whose `risk_profile` or
`time_horizon` changes triggers a re-mapping event (Section 6.3).

Wealth tier is **not** a bucket axis (per Section 5.4) — it's an execution-time
filter applied per investor for AUM-based vehicle eligibility.
"""

from __future__ import annotations

from artha.common.types import Bucket, RiskProfile, TimeHorizon

_BUCKET_FOR: dict[tuple[RiskProfile, TimeHorizon], Bucket] = {
    (RiskProfile.CONSERVATIVE, TimeHorizon.SHORT_TERM): Bucket.CON_ST,
    (RiskProfile.CONSERVATIVE, TimeHorizon.MEDIUM_TERM): Bucket.CON_MT,
    (RiskProfile.CONSERVATIVE, TimeHorizon.LONG_TERM): Bucket.CON_LT,
    (RiskProfile.MODERATE, TimeHorizon.SHORT_TERM): Bucket.MOD_ST,
    (RiskProfile.MODERATE, TimeHorizon.MEDIUM_TERM): Bucket.MOD_MT,
    (RiskProfile.MODERATE, TimeHorizon.LONG_TERM): Bucket.MOD_LT,
    (RiskProfile.AGGRESSIVE, TimeHorizon.SHORT_TERM): Bucket.AGG_ST,
    (RiskProfile.AGGRESSIVE, TimeHorizon.MEDIUM_TERM): Bucket.AGG_MT,
    (RiskProfile.AGGRESSIVE, TimeHorizon.LONG_TERM): Bucket.AGG_LT,
}


_REVERSE: dict[Bucket, tuple[RiskProfile, TimeHorizon]] = {
    bucket: components for components, bucket in _BUCKET_FOR.items()
}


BUCKET_RISK_PROFILE: dict[Bucket, RiskProfile] = {b: rp for b, (rp, _) in _REVERSE.items()}
BUCKET_TIME_HORIZON: dict[Bucket, TimeHorizon] = {b: th for b, (_, th) in _REVERSE.items()}


def derive_bucket(risk_profile: RiskProfile, time_horizon: TimeHorizon) -> Bucket:
    """Return the canonical bucket for the given (risk profile, time horizon) pair.

    Deterministic — the mapping never changes. An investor's bucket changes only
    when their active-layer fields change.
    """
    return _BUCKET_FOR[(risk_profile, time_horizon)]


def bucket_components(bucket: Bucket) -> tuple[RiskProfile, TimeHorizon]:
    """Inverse of `derive_bucket`. Useful for surfaces that need to render the bucket axes."""
    return _REVERSE[bucket]
