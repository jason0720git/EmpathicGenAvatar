from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Small, explicit configuration surface for the prototype control API."""

    data_dir: Path
    database_path: Path
    allowed_origins: tuple[str, ...]
    avatar_engine: str = "preview"
    avatar_renderer_url: str | None = None
    ollama_url: str | None = None
    ollama_model: str = "llama3.2:3b"
    app_env: str = "development"
    api_access_token: str | None = None
    worker_shared_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("APP_DATA_DIR", "./data")).resolve()
        database_path = Path(os.getenv("DATABASE_PATH", str(data_dir / "empathic.db"))).resolve()
        origins = tuple(origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if origin.strip())
        engine = os.getenv("AVATAR_ENGINE", "preview").strip().lower()
        if engine not in {"preview", "remote"}:
            raise ValueError("AVATAR_ENGINE must be 'preview' or 'remote'")
        renderer_url = os.getenv("AVATAR_RENDERER_URL") or None
        if engine == "remote" and not renderer_url:
            raise ValueError("AVATAR_RENDERER_URL is required when AVATAR_ENGINE=remote")
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        api_access_token = os.getenv("API_ACCESS_TOKEN") or None
        if app_env == "production" and not api_access_token:
            raise ValueError("API_ACCESS_TOKEN is required when APP_ENV=production")
        return cls(
            data_dir=data_dir,
            database_path=database_path,
            allowed_origins=origins,
            avatar_engine=engine,
            avatar_renderer_url=renderer_url.rstrip("/") if renderer_url else None,
            ollama_url=(os.getenv("OLLAMA_URL") or None),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            app_env=app_env,
            api_access_token=api_access_token,
            worker_shared_token=os.getenv("WORKER_SHARED_TOKEN") or None,
        )
