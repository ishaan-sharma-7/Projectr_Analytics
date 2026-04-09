"""CampusLens configuration — loads API keys from .env file."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


@dataclass
class Config:
    """Application configuration loaded from env vars."""

    # College Scorecard (free key from api.data.gov)
    scorecard_api_key: str = ""

    # Census API (free key from api.census.gov)
    census_api_key: str = ""

    # HUD API (free key from huduser.gov)
    hud_api_key: str = ""

    # Google Maps Platform
    google_maps_key: str = ""

    # Google AI / Gemini
    gemini_api_key: str = ""

    # Google Cloud (Firestore)
    gcp_project_id: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Cache directory for pre-scored data
    cache_dir: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            scorecard_api_key=os.getenv("SCORECARD_API_KEY", ""),
            census_api_key=os.getenv("CENSUS_API_KEY", ""),
            hud_api_key=os.getenv("HUD_API_KEY", ""),
            google_maps_key=os.getenv("GOOGLE_MAPS_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gcp_project_id=os.getenv("GCP_PROJECT_ID", ""),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            cache_dir=os.getenv(
                "CACHE_DIR",
                os.path.join(os.path.dirname(__file__), "cache"),
            ),
        )


config = Config.from_env()
