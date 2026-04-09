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
    ExistingHousingStock,
    HousingCapacity,
    HousingPressureScore,
    InstitutionalStrength,
    MarketDemographics,
    MasterPlanData,
    OccupancyOrdinance,
    PermitData,
    RentData,
    ScoreComponents,
    STRMarket,
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


def _endowment_score(per_student: int | None) -> float | None:
    """Convert endowment-per-student dollars to a 0–100 wealth-cushion score.

    Reference points (from public IPEDS Finance data):
      <$10k   → 20  (Cal State, regional comprehensives)
      $50k    → 50  (large flagships, e.g. UT Austin)
      $100k   → 70  (well-funded flagships, e.g. UMich)
      $500k+  → 95  (Ivy-tier endowments, e.g. Princeton, Yale)
      $1M+    → 100
    """
    if per_student is None:
        return None
    # Log-ish piecewise linear mapping
    if per_student <= 10_000:
        return 20.0
    if per_student <= 50_000:
        return 20 + (per_student - 10_000) / 40_000 * 30  # 20 → 50
    if per_student <= 100_000:
        return 50 + (per_student - 50_000) / 50_000 * 20  # 50 → 70
    if per_student <= 500_000:
        return 70 + (per_student - 100_000) / 400_000 * 25  # 70 → 95
    return min(100.0, 95 + (per_student - 500_000) / 500_000 * 5)  # 95 → 100


def _retention_score(rate: float | None) -> float | None:
    """Map first-year retention rate (0–1) to a 0–100 stability score.

    Retention is the leading indicator of enrollment durability — a flagship
    bleeding 25% of freshmen has fragile housing demand even at huge size.
    """
    if rate is None:
        return None
    pct = rate * 100
    # Floor at 30 so a school with 50% retention isn't pinned to 0.
    return max(30.0, min(100.0, round(pct, 1)))


def _selectivity_score(admission_rate: float | None) -> float | None:
    """Map admission rate (0–1) to a 0–100 brand-strength score.

    Lower admission rate → more selective → stronger brand → more durable
    applicant pipeline.  Open-enrollment schools land at the floor of 30.
    """
    if admission_rate is None:
        return None
    if admission_rate <= 0.10:
        return 100.0
    if admission_rate <= 0.30:
        return 80.0 + (0.30 - admission_rate) / 0.20 * 20  # 80 → 100
    if admission_rate <= 0.60:
        return 50.0 + (0.60 - admission_rate) / 0.30 * 30  # 50 → 80
    return max(30.0, 50.0 - (admission_rate - 0.60) * 50)  # 50 → 30


def _pell_penalty(pell_rate: float | None) -> float:
    """High Pell share signals an institutionally vulnerable student base.

    Pell-dependent students are most exposed to federal aid changes (the
    research doc explicitly flags this). We dock the strength score
    accordingly. Returns POSITIVE penalty points to subtract.
    """
    if pell_rate is None:
        return 0.0
    if pell_rate < 0.30:
        return 0.0
    if pell_rate < 0.50:
        return 5.0
    return 10.0


def compute_strength_score(strength: InstitutionalStrength) -> tuple[float, str]:
    """Combine the four sub-signals into a 0–100 strength score and label.

    Weighting:
      40% endowment cushion
      40% retention stability
      20% brand selectivity
      − Pell vulnerability penalty

    Sub-signals that are missing (a common situation for small or non-PhD
    institutions) are dropped from the average rather than imputed — we re-
    weight the remaining components so the score still reflects what we know.
    """
    endow = _endowment_score(strength.endowment_per_student)
    retain = _retention_score(strength.retention_rate)
    select = _selectivity_score(strength.admission_rate)

    parts: list[tuple[float, float]] = []  # (value, weight)
    if endow is not None:
        parts.append((endow, 0.40))
    if retain is not None:
        parts.append((retain, 0.40))
    if select is not None:
        parts.append((select, 0.20))

    if not parts:
        # Nothing to score on — call it stable and bail.
        return 50.0, "stable"

    total_weight = sum(w for _, w in parts)
    base = sum(v * w for v, w in parts) / total_weight
    score = max(0.0, min(100.0, base - _pell_penalty(strength.pell_grant_rate)))

    if score >= 75:
        label = "strong"
    elif score >= 50:
        label = "stable"
    else:
        label = "watch"

    return round(score, 1), label


def compute_pressure_score(
    university: UniversityMeta,
    enrollment_trend: list[EnrollmentTrend],
    permit_history: list[PermitData],
    housing_units: int,
    rent_history: list[RentData],
    demographics: MarketDemographics | None = None,
    housing_capacity: HousingCapacity | None = None,
    disaster_risk: DisasterRisk | None = None,
    institutional_strength: InstitutionalStrength | None = None,
    existing_housing: ExistingHousingStock | None = None,
    master_plan: MasterPlanData | None = None,
    occupancy_ordinance: OccupancyOrdinance | None = None,
    str_market: STRMarket | None = None,
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

    # 4. Institutional Strength Adjustment
    # Strong institutions = more durable enrollment = more confidence the
    # housing demand we're projecting will actually materialize. Watch
    # institutions get a haircut because the upstream signal (enrollment
    # trend) may not survive a budget shock.
    if institutional_strength is not None:
        s_score, s_label = compute_strength_score(institutional_strength)
        institutional_strength = institutional_strength.model_copy(
            update={"strength_score": s_score, "strength_label": s_label}
        )
        if s_label == "strong":
            multiplier *= 1.02
        elif s_label == "watch":
            multiplier *= 0.93

    # 5. Existing Stock Saturation Penalty
    # Markets that already have a wall of apartment buildings near campus
    # have less greenfield to build into. We dock the score for "high"
    # saturation. "low" saturation is genuine headroom and gets a small
    # bump because the demand model isn't picking up the available land.
    if existing_housing is not None:
        if existing_housing.saturation_label == "high":
            multiplier *= 0.92
        elif existing_housing.saturation_label == "low":
            multiplier *= 1.03

    # 8. STR shadow supply boost
    # High Airbnb/VRBO concentration removes units from the long-term rental
    # pool, reducing effective student housing supply and increasing PBSH demand
    # durability. We apply the pre-computed score_multiplier from the adapter.
    if str_market and str_market.pbsh_signal == "positive":
        multiplier *= str_market.score_multiplier

    # 7. Occupancy ordinance boost
    # Cities with enforced unrelated-person caps restrict cheap house-packing.
    # Students can't easily form large shared households → off-campus supply is
    # structurally tighter → PBSH demand is more durable and price-stable.
    # We only apply the boost when the ordinance is actually enforced.
    if occupancy_ordinance and occupancy_ordinance.pbsh_signal == "positive" and occupancy_ordinance.enforced:
        if occupancy_ordinance.max_unrelated_occupants is not None:
            if occupancy_ordinance.max_unrelated_occupants <= 3:
                multiplier *= 1.08  # tight cap (≤3) — meaningful demand lift
            else:
                multiplier *= 1.04  # moderate cap (4) — incremental benefit

    # 6. Planned on-campus bed pipeline
    # A large planned supply of on-campus beds will absorb students who would
    # otherwise need off-campus housing — direct negative for PBSH demand.
    # We use time-discounted beds relative to enrollment as the signal:
    #   ≥10% of enrollment in new on-campus beds → material supply relief (-12%)
    #   ≥5%                                      → moderate relief (-6%)
    #   ≥2%                                      → minor signal (-3%)
    if master_plan and master_plan.planned_beds_weighted and university.enrollment:
        planned_ratio = master_plan.planned_beds_weighted / university.enrollment
        if planned_ratio >= 0.10:
            multiplier *= 0.88
        elif planned_ratio >= 0.05:
            multiplier *= 0.94
        elif planned_ratio >= 0.02:
            multiplier *= 0.97

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
        institutional_strength=institutional_strength,
        existing_housing=existing_housing,
        master_plan=master_plan,
        occupancy_ordinance=occupancy_ordinance,
        str_market=str_market,
        gemini_summary=gemini_summary,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )
