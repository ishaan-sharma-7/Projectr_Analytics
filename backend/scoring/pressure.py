"""Housing Pressure Score — the core metric of CampusLens.

Three components combined into a 0–100 score:

  Score = 0.40 × Enrollment Pressure
        + 0.35 × Permit Gap
        + 0.25 × Rent Pressure

Higher score = more housing pressure = undersupplied market.

Component calculations:
  - Enrollment Pressure: 5yr enrollment CAGR, normalized to [0,100].
    A CAGR of 0% → 30, 2% → 60, 5%+ → 100. Negative growth → 0–20.

  - Permit Gap: 1 - (5yr_permits / county_housing_units), normalized.
    If permits are <1% of housing stock → high gap (90+).
    If permits are >10% of housing stock → low gap (10–20).

  - Rent Pressure: 3yr rent growth rate, normalized to [0,100].
    0% growth → 20, 5% → 60, 10%+ → 100.
"""

from datetime import datetime, timezone

from backend.models.schemas import (
    DisasterRisk,
    EnrollmentTrend,
    HousingCapacity,
    HousingPressureScore,
    MarketDemographics,
    PermitData,
    RentData,
    ScoreComponents,
    UniversityMeta,
)
from backend.adapters.ipeds import compute_enrollment_cagr
from backend.adapters.rent import compute_rent_growth

# ── Component weights ──
W_ENROLLMENT = 0.40
W_PERMIT = 0.35
W_RENT = 0.25


def _normalize(value: float, low: float, high: float) -> float:
    """Clamp and normalize a value to [0, 100]."""
    if high <= low:
        return 50.0
    normalized = (value - low) / (high - low) * 100
    return max(0.0, min(100.0, round(normalized, 1)))


def _enrollment_score(cagr: float | None) -> float:
    """Convert enrollment CAGR (%) to a 0–100 score."""
    if cagr is None:
        return 50.0  # Neutral when no data
    # Map: -5% → 0, 0% → 30, 2% → 60, 5% → 100
    return _normalize(cagr, -5.0, 5.0)


def _permit_gap_score(
    permits_5yr: int,
    housing_units: int,
) -> float:
    """Convert permit-to-housing ratio into a gap score.

    Low ratio = high gap = high score (undersupplied).
    """
    if housing_units <= 0:
        return 50.0  # Neutral when no data

    ratio = permits_5yr / housing_units
    # Map: 0% ratio → 100 (no permits = maximum gap)
    #       5% ratio → 50
    #       10%+ ratio → 0 (lots of building)
    gap = 1.0 - ratio
    return _normalize(gap, 0.0, 1.0)


def _rent_score(growth: float | None) -> float:
    """Convert annual rent growth (%) to a 0–100 score."""
    if growth is None:
        return 50.0  # Neutral when no data
    # Map: -2% → 0, 0% → 20, 5% → 60, 12% → 100
    return _normalize(growth, -2.0, 12.0)


def compute_pressure_score(
    university: UniversityMeta,
    enrollment_trend: list[EnrollmentTrend],
    permit_history: list[PermitData],
    housing_units: int,
    rent_history: list[RentData],
    demographics: MarketDemographics | None = None,
    housing_capacity: HousingCapacity | None = None,
    disaster_risk: DisasterRisk | None = None,
    gemini_summary: str | None = None,
) -> HousingPressureScore:
    """Compute the full Housing Pressure Score for a university market."""

    # ── Component 1: Enrollment Pressure ──
    cagr = compute_enrollment_cagr(enrollment_trend, years=5)
    enrollment_pressure = _enrollment_score(cagr)

    # ── Component 2: Permit Gap ──
    total_permits_5yr = sum(p.permits for p in permit_history[-5:])
    permit_gap = _permit_gap_score(total_permits_5yr, housing_units)

    # ── Component 3: Rent Pressure ──
    rent_growth = compute_rent_growth(rent_history, years=3)
    rent_pressure = _rent_score(rent_growth)

    # ── Weighted composite ──
    raw_score = (
        W_ENROLLMENT * enrollment_pressure
        + W_PERMIT * permit_gap
        + W_RENT * rent_pressure
    )
    # ── Compute beds-per-student if both signals are available ──
    if housing_capacity and university.enrollment and university.enrollment > 0:
        housing_capacity = housing_capacity.model_copy(
            update={
                "beds_per_student": round(
                    housing_capacity.dormitory_capacity / university.enrollment, 3
                )
            }
        )

    # ── V2 Multiplier System ──
    multiplier = 1.0

    # 1. Capacity Penalty/Boost
    if housing_capacity and housing_capacity.beds_per_student is not None:
        if housing_capacity.beds_per_student < 0.25:
            multiplier *= 1.15
        elif housing_capacity.beds_per_student > 0.75:
            multiplier *= 0.80

    # 2. Demographics (Vacancy) Penalty/Boost
    if demographics and demographics.vacancy_rate_pct is not None:
        if demographics.vacancy_rate_pct < 3.0:
            multiplier *= 1.05
        elif demographics.vacancy_rate_pct > 10.0:
            multiplier *= 0.85

    # 3. Disaster Risk Penalty
    if disaster_risk:
        if disaster_risk.weather_disasters >= 10:
            multiplier *= 0.90
        elif disaster_risk.weather_disasters >= 5:
            multiplier *= 0.95

    final_score = max(0.0, min(100.0, round(raw_score * multiplier, 1)))

    components = ScoreComponents(
        enrollment_pressure=enrollment_pressure,
        permit_gap=permit_gap,
        rent_pressure=rent_pressure,
    )

    return HousingPressureScore(
        university=university,
        score=final_score,
        components=components,
        enrollment_trend=enrollment_trend,
        permit_history=permit_history,
        rent_history=rent_history,
        nearby_housing_units=housing_units,
        demographics=demographics,
        housing_capacity=housing_capacity,
        disaster_risk=disaster_risk,
        gemini_summary=gemini_summary,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )
