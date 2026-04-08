"""Pydantic models for CampusLens API requests and responses."""

from pydantic import BaseModel, Field


class UniversityMeta(BaseModel):
    """Core university metadata from College Scorecard."""

    unitid: int
    name: str
    city: str
    state: str
    lat: float
    lon: float
    enrollment: int | None = None
    url: str | None = None


class EnrollmentTrend(BaseModel):
    """Year-over-year enrollment data from IPEDS."""

    year: int
    total_enrollment: int


class PermitData(BaseModel):
    """Building permits from Census BPS."""

    year: int
    permits: int
    fips_place: str = ""


class HousingUnits(BaseModel):
    """Housing unit count from Census ACS."""

    fips_tract: str
    total_units: int
    year: int = 2023


class RentData(BaseModel):
    """Rent data from ApartmentList or HUD FMR."""

    city: str
    state: str
    year: int
    month: int | None = None
    median_rent: float
    source: str = "apartmentlist"  # or "hud_fmr"


class ScoreComponents(BaseModel):
    """Individual components of the Housing Pressure Score."""

    enrollment_pressure: float = Field(ge=0, le=100, description="Enrollment growth component (0-100)")
    permit_gap: float = Field(ge=0, le=100, description="Permit shortfall component (0-100)")
    rent_pressure: float = Field(ge=0, le=100, description="Rent growth component (0-100)")


class MarketDemographics(BaseModel):
    """Demographic + housing context from Census ACS 5-year (county-level)."""

    median_household_income: int | None = None
    median_home_value: int | None = None
    median_gross_rent: int | None = None
    median_year_built: int | None = None
    vacancy_rate_pct: float | None = None
    pct_bachelors_or_higher: float | None = None
    pct_renter_occupied: float | None = None
    total_housing_units: int | None = None


class HousingCapacity(BaseModel):
    """On-campus residence-hall capacity from IPEDS Institutional Characteristics."""

    year: int
    dormitory_capacity: int
    typical_room_charge: int | None = None
    typical_board_charge: int | None = None
    beds_per_student: float | None = None


class DisasterRisk(BaseModel):
    """Federally declared disaster history from OpenFEMA (county-level)."""

    window_years: int
    total_disasters: int
    weather_disasters: int
    by_type: dict[str, int] = {}
    most_recent_year: int | None = None


class HousingPressureScore(BaseModel):
    """Complete Housing Pressure Score for a university market."""

    university: UniversityMeta
    score: float = Field(ge=0, le=100, description="Overall pressure score (0-100)")
    components: ScoreComponents
    enrollment_trend: list[EnrollmentTrend] = []
    permit_history: list[PermitData] = []
    rent_history: list[RentData] = []
    nearby_housing_units: int | None = None
    demographics: MarketDemographics | None = None
    housing_capacity: HousingCapacity | None = None
    disaster_risk: DisasterRisk | None = None
    gemini_summary: str | None = None
    scored_at: str = ""


class ScoreRequest(BaseModel):
    """Request to compute a score for a university."""

    university_name: str
    unitid: int | None = None


class UniversityListItem(BaseModel):
    """Abbreviated university for the national map."""

    unitid: int
    name: str
    city: str
    state: str
    lat: float
    lon: float
    score: float
    score_label: str = ""  # "high", "medium", "low"
