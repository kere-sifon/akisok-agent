from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

PILLARS = (
    "history",
    "people",
    "culture",
    "places",
    "news",
    "opinion",
    "technology",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_QUERIES_PATH = REPO_ROOT / "config" / "seed_queries.yaml"


class Settings(BaseModel):
    aws_region: str
    bedrock_model_id: str
    mongodb_uri: str
    mongodb_db_name: str
    search_api_key: str
    embedding_model_id: str
    max_search_calls_per_run: int = Field(default=10, ge=1)
    relevance_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    reproduction_overlap_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    dedup_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    dedup_lookback_days: int = Field(default=14, ge=1)
    admin_ui_port: int = Field(default=8001, ge=1)
    content_repo_path: str | None = None
    seed_lga_rotation_size: int = Field(default=3, ge=1)
    evergreen_queries: list[str] = Field(default_factory=list)
    lga_names: list[str] = Field(default_factory=list)
    seed_queries: list[str] = Field(default_factory=list)

    @field_validator(
        "bedrock_model_id",
        "mongodb_uri",
        "mongodb_db_name",
        "aws_region",
        "search_api_key",
        "embedding_model_id",
    )
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


LGA_QUERY_TEMPLATE = "{lga} Akwa Ibom"


def _require(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def load_seed_catalog(path: Path | None = None) -> tuple[list[str], list[str]]:
    seed_path = path or SEED_QUERIES_PATH
    with seed_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Seed query file must be a mapping: {seed_path}")
    evergreen = _string_list(raw.get("evergreen") or raw.get("queries"))
    lga_names = _string_list(raw.get("lga_names") or raw.get("lgas"))
    if not evergreen:
        raise ValueError(f"No evergreen discovery queries found in {seed_path}")
    return evergreen, lga_names


def _string_list(values: object) -> list[str]:
    if not values:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def next_run_seed_queries(
    mongo,
    *,
    evergreen: list[str],
    lga_names: list[str],
    rotation_size: int,
    template: str = LGA_QUERY_TEMPLATE,
) -> list[str]:
    """Evergreen queries plus the next LGA rotation slice. Advances last_index."""
    start = mongo.get_lga_rotation_index()
    count = len(lga_names)
    if count == 0:
        slice_names: list[str] = []
        next_index = 0
    else:
        take = min(max(rotation_size, 0), count)
        slice_names = [lga_names[(start + offset) % count] for offset in range(take)]
        next_index = (start + take) % count
    mongo.set_lga_rotation_index(next_index)
    lga_queries = [template.replace("{lga}", name) for name in slice_names]
    return [*evergreen, *lga_queries]


def load_settings(*, dotenv: bool = True, seed_path: Path | None = None) -> Settings:
    if dotenv:
        load_dotenv()

    raw_threshold = os.getenv("RELEVANCE_THRESHOLD", "0.6")
    raw_max_calls = os.getenv("MAX_SEARCH_CALLS_PER_RUN", "10")
    evergreen, lga_names = load_seed_catalog(seed_path)
    try:
        return Settings(
            aws_region=_require("AWS_REGION"),
            bedrock_model_id=_require("BEDROCK_MODEL_ID"),
            mongodb_uri=_require("MONGODB_URI"),
            mongodb_db_name=_require("MONGODB_DB_NAME"),
            search_api_key=_require("SEARCH_API_KEY"),
            embedding_model_id=_require("EMBEDDING_MODEL_ID"),
            max_search_calls_per_run=int(raw_max_calls),
            relevance_threshold=float(raw_threshold),
            reproduction_overlap_threshold=float(
                os.getenv("REPRODUCTION_OVERLAP_THRESHOLD", "0.15")
            ),
            dedup_similarity_threshold=float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.92")),
            dedup_lookback_days=int(os.getenv("DEDUP_LOOKBACK_DAYS", "14")),
            admin_ui_port=int(os.getenv("ADMIN_UI_PORT", "8001")),
            content_repo_path=(os.getenv("CONTENT_REPO_PATH") or "").strip() or None,
            seed_lga_rotation_size=int(os.getenv("SEED_LGA_ROTATION_SIZE", "3")),
            evergreen_queries=evergreen,
            lga_names=lga_names,
            seed_queries=list(evergreen),
        )
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Invalid pipeline configuration: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
