from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import AvatarOut, ImageQuality, SessionOut
from .quality import inspect_image


DEFAULT_AVATARS = (
    (
        "demo-hana", "default-korean-avatar.png", "하나 · Ditto Live",
        "차분하고 신뢰감 있게 대화하는 AI 생성 한국어 데모 아바타",
    ),
    (
        "demo-minjun", "default-korean-man-avatar.png", "민준 · Ditto Live",
        "차분하고 명료하게 대화하는 AI 생성 한국어 데모 아바타",
    ),
    (
        "demo-seoyeon", "default-korean-idol-woman-avatar.png", "서연 · Idol Demo",
        "세련되고 밝은 톤으로 대화하는 AI 생성 아이돌 콘셉트 아바타",
    ),
    (
        "demo-doyun", "default-korean-idol-man-avatar.png", "도윤 · Idol Demo",
        "담백하고 자신감 있게 대화하는 AI 생성 아이돌 콘셉트 아바타",
    ),
)


class Store:
    """SQLite control-plane state; transcripts are intentionally never persisted."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS avatars (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    persona TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_path TEXT,
                    created_at TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    quality_json TEXT,
                    cache_ref TEXT
                );
                CREATE TABLE IF NOT EXISTS avatar_consents (
                    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
                    likeness INTEGER NOT NULL,
                    adult INTEGER NOT NULL,
                    ai_label INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active_turn_id TEXT
                );
                """
            )
        self._ensure_demo_avatar()

    def _ensure_demo_avatar(self) -> None:
        """Seed the one AI-generated, Ditto-ready avatar shown on the dashboard."""
        now = _now()
        upload_dir = self.database_path.parent / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            for avatar_id, asset_name, name, persona in DEFAULT_AVATARS:
                bundled_asset = Path(__file__).parent / "assets" / asset_name
                source_path = upload_dir / asset_name
                if not source_path.is_file():
                    shutil.copyfile(bundled_asset, source_path)
                quality = inspect_image(source_path.read_bytes(), "image/png")
                connection.execute(
                    """INSERT OR IGNORE INTO avatars
                       (id,name,persona,voice,status,source_path,created_at,engine,quality_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        avatar_id, name, persona, "Calm Korean", "ready", str(source_path), now,
                        "remote", quality.model_dump_json(),
                    ),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_avatar(
        self,
        *,
        avatar_id: str,
        name: str,
        persona: str,
        voice: str,
        source_path: str,
        status: str,
        engine: str,
        quality: ImageQuality,
        likeness: bool,
        adult: bool,
        ai_label: bool,
    ) -> AvatarOut:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO avatars(id,name,persona,voice,status,source_path,created_at,engine,quality_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (avatar_id, name, persona, voice, status, source_path, now, engine, quality.model_dump_json()),
            )
            connection.execute(
                """INSERT INTO avatar_consents(avatar_id,likeness,adult,ai_label,recorded_at)
                   VALUES(?,?,?,?,?)""",
                (avatar_id, int(likeness), int(adult), int(ai_label), now),
            )
        return self.get_avatar(avatar_id)

    def list_avatars(self) -> list[AvatarOut]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM avatars ORDER BY created_at DESC").fetchall()
        return [self._avatar(row) for row in rows]

    def get_avatar(self, avatar_id: str) -> AvatarOut:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM avatars WHERE id = ?", (avatar_id,)).fetchone()
        if row is None:
            raise KeyError("avatar not found")
        return self._avatar(row)

    def get_source_path(self, avatar_id: str) -> Path | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT source_path FROM avatars WHERE id = ?", (avatar_id,)).fetchone()
        if row is None:
            raise KeyError("avatar not found")
        return Path(row["source_path"]) if row["source_path"] else None

    def set_avatar_status(self, avatar_id: str, status: str, engine: str | None = None, cache_ref: str | None = None) -> None:
        values: list[Any] = [status]
        set_parts = ["status = ?"]
        if engine:
            set_parts.append("engine = ?")
            values.append(engine)
        if cache_ref is not None:
            set_parts.append("cache_ref = ?")
            values.append(cache_ref)
        values.append(avatar_id)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE avatars SET {', '.join(set_parts)} WHERE id = ?", values)

    def delete_avatar(self, avatar_id: str) -> Path | None:
        source_path = self.get_source_path(avatar_id)
        with self._lock, self._connect() as connection:
            # Explicitly clear sessions as well as relying on the new FK cascade;
            # this keeps deletion correct for databases created by earlier builds.
            connection.execute("DELETE FROM sessions WHERE avatar_id = ?", (avatar_id,))
            deleted = connection.execute("DELETE FROM avatars WHERE id = ?", (avatar_id,)).rowcount
        if not deleted:
            raise KeyError("avatar not found")
        return source_path

    def create_session(self, session_id: str, avatar_id: str) -> SessionOut:
        self.get_avatar(avatar_id)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO sessions(id,avatar_id,state,created_at) VALUES(?,?,?,?)", (session_id, avatar_id, "active", now))
        return SessionOut(id=session_id, avatar_id=avatar_id, state="active", created_at=now)

    def get_session(self, session_id: str) -> SessionOut:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT id, avatar_id, state, created_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError("session not found")
        return SessionOut(id=row["id"], avatar_id=row["avatar_id"], state=row["state"], created_at=row["created_at"])

    def set_active_turn(self, session_id: str, turn_id: str | None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE sessions SET active_turn_id = ? WHERE id = ?", (turn_id, session_id))

    def is_active_turn(self, session_id: str, turn_id: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT active_turn_id, state FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return bool(row and row["state"] == "active" and row["active_turn_id"] == turn_id)

    def end_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            changed = connection.execute("UPDATE sessions SET state = 'ended', active_turn_id = NULL WHERE id = ?", (session_id,)).rowcount
        if not changed:
            raise KeyError("session not found")

    def _avatar(self, row: sqlite3.Row) -> AvatarOut:
        quality = ImageQuality.model_validate(json.loads(row["quality_json"])) if row["quality_json"] else None
        return AvatarOut(
            id=row["id"],
            name=row["name"],
            persona=row["persona"],
            voice=row["voice"],
            status=row["status"],
            source_url=f"/api/assets/{row['id']}" if row["source_path"] else None,
            created_at=row["created_at"],
            engine=row["engine"],
            quality=quality,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
