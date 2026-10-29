"""Application configuration, loaded from environment variables / .env.

Secrets (SECRET_KEY, EMBEDDING_ENCRYPTION_KEY) have NO defaults on purpose:
the application refuses to start without them rather than running with a
publicly known key. ``scripts/setup.ps1`` generates them for local use.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- general ---
    app_name: str = "Face Attendance"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # --- database ---
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'attendance.db').as_posix()}"

    # --- security (no defaults) ---
    secret_key: str = Field(min_length=32)
    embedding_encryption_key: str = Field(min_length=32)
    access_token_minutes: int = Field(default=480, ge=5, le=60 * 24 * 7)
    cookie_secure: bool = False  # set True when served over HTTPS
    cookie_samesite: Literal["lax", "strict"] = "lax"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    login_rate_limit: int = Field(default=8, ge=1)  # attempts per window per client+username
    login_rate_window_seconds: int = Field(default=60, ge=1)
    min_password_length: int = Field(default=10, ge=8)

    # --- face model ---
    model_name: str = "buffalo_l"
    model_root: str = str(BACKEND_DIR / "data" / "insightface")
    detection_size: int = Field(default=640, ge=160, le=1280)
    onnx_providers: str = "CPUExecutionProvider"
    inference_workers: int = Field(default=1, ge=1, le=4)
    load_model_on_startup: bool = True

    # --- recognition defaults (admin-editable at runtime; these seed the DB) ---
    default_recognition_threshold: float = Field(default=0.45, ge=0.1, le=0.95)
    default_recognition_margin: float = Field(default=0.04, ge=0.0, le=0.5)
    default_timezone: str = "Asia/Kolkata"
    max_frame_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 5 * 1024 * 1024
    max_frame_side: int = 960  # frames are downscaled to this before inference
    min_enroll_images: int = Field(default=3, ge=1)
    max_enroll_images: int = Field(default=12, ge=1)

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def providers(self) -> list[str]:
        return [p.strip() for p in self.onnx_providers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
