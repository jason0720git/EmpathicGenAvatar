"""Local, file-backed Gaussian assets and complete per-session diagnostics."""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checked_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{24}", value):
        raise ValueError("Invalid identifier")
    return value


def safe_payload(value):
    """Redact credentials and inline media while preserving diagnostic metadata."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(token in key.lower() for token in ("api_key", "authorization", "secret", "access_token")):
                result[key] = "[redacted]"
            elif key in {"pcm_base64", "audio", "delta_audio"} and isinstance(item, str):
                result[key + "_base64_chars"] = len(item)
            else:
                result[key] = safe_payload(item)
        return result
    if isinstance(value, list):
        return [safe_payload(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[redacted]", value)
    return value


class SessionLog:
    def __init__(self, directory: Path, session_id: str, config: dict):
        self.path = directory / checked_id(session_id)
        self.path.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.start = time.monotonic()
        self.lock = threading.Lock()
        self.sequence = 0
        (self.path / "session.json").write_text(json.dumps(safe_payload(config), ensure_ascii=False, indent=2), encoding="utf-8")
        self.record("session.created", config)

    def record(self, event: str, payload: dict | None = None):
        with self.lock:
            self.sequence += 1
            record = {"at": utc_now(), "elapsed_ms": round((time.monotonic()-self.start)*1000, 2),
                      "sequence": self.sequence, "event": event, "session_id": self.session_id,
                      **safe_payload(payload or {})}
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        return record

    def audio(self, turn_id: str, role: str, data: bytes):
        checked_id(turn_id)
        if role not in {"input", "output"}:
            raise ValueError("Invalid audio role")
        with self.lock, (self.path / f"{turn_id}-{role}-24000.pcm").open("ab") as out:
            out.write(data)

    def archive(self) -> bytes:
        buffer = io.BytesIO()
        with self.lock, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.path.iterdir()):
                if path.is_file():
                    archive.write(path, path.name)
            archive.writestr("audio-format.txt", "All .pcm files are raw mono signed 16-bit little-endian PCM at 24000 Hz.\nExample: ffmpeg -f s16le -ar 24000 -ac 1 -i TURN-output-24000.pcm output.wav\n")
        return buffer.getvalue()


def validate_asset_zip(data: bytes):
    if len(data) > 150 * 1024 * 1024:
        raise ValueError("Avatar ZIP exceeds 150 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = 0
            names = set()
            parents = set()
            members = archive.infolist()
            if len(members) > 64:
                raise ValueError("Too many avatar files")
            for member in members:
                name = member.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or ":" in name or member.flag_bits & 1:
                    raise ValueError("Unsafe avatar ZIP path or encrypted entry")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Avatar ZIP cannot contain symlinks")
                total += member.file_size
                if total > 400 * 1024 * 1024:
                    raise ValueError("Expanded avatar exceeds 400 MB")
                if not member.is_dir():
                    if path.name in names:
                        raise ValueError("Duplicate avatar asset name")
                    names.add(path.name)
                    parents.add(str(path.parent))
            if not {"offset.ply", "skin.glb", "animation.glb"} <= names:
                raise ValueError("LAM export requires offset.ply, skin.glb and animation.glb")
            if len(parents) != 1:
                raise ValueError("LAM files must share one folder in the ZIP")
            for member in members:
                if member.is_dir():
                    continue
                with archive.open(member) as asset:
                    header = asset.read(12)
                if member.filename.endswith(".glb"):
                    import struct
                    if len(header) != 12 or header[:4] != b"glTF" or struct.unpack("<II", header[4:]) != (2, member.file_size):
                        raise ValueError("Invalid GLB header or size")
                if member.filename.endswith(".ply") and not header.startswith(b"ply\n") and not header.startswith(b"ply\r\n"):
                    raise ValueError("Invalid Gaussian PLY header")
            if archive.testzip():
                raise ValueError("Damaged avatar ZIP")
    except zipfile.BadZipFile as error:
        raise ValueError("Not a valid avatar ZIP") from error


class AvatarFiles:
    def __init__(self, root: Path):
        self.root = root / "avatars"
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, avatar_id: str) -> Path:
        return self.root / checked_id(avatar_id)

    def save(self, record: dict):
        target = self.directory(record["id"])
        target.mkdir(parents=True, exist_ok=True)
        temporary = target / "record.tmp"
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target / "record.json")

    def get(self, avatar_id: str) -> dict:
        path = self.directory(avatar_id) / "record.json"
        if not path.is_file():
            raise FileNotFoundError(avatar_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        result = []
        for path in self.root.glob("*/record.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda r: (bool(r.get("pinned")), r["created_at"]), reverse=True)

    def create(self, name: str, source: str, *, photo: bytes | None = None, asset: bytes | None = None) -> dict:
        if asset is not None:
            validate_asset_zip(asset)
        image = None
        if photo is not None:
            if len(photo) > 15 * 1024 * 1024:
                raise ValueError("Portrait exceeds 15 MB")
            try:
                image = Image.open(io.BytesIO(photo))
                if image.width * image.height > 25_000_000 or min(image.size) < 128:
                    raise ValueError("Portrait dimensions must be at least 128px and at most 25 megapixels")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1536, 1536))
            except (OSError, Image.DecompressionBombError) as error:
                raise ValueError("Invalid portrait image") from error
        avatar_id = uuid.uuid4().hex[:24]
        record = {"id": avatar_id, "name": name.strip()[:80] or "새 3DGS 아바타", "source": source,
                  "status": "ready" if asset else "preparing", "created_at": utc_now(),
                  "asset_url": f"/gaussian-api/avatars/{avatar_id}/asset.zip",
                  "image_url": f"/gaussian-api/avatars/{avatar_id}/source" if image else None,
                  "source_sha256": hashlib.sha256(photo).hexdigest() if photo else None,
                  "asset_sha256": hashlib.sha256(asset).hexdigest() if asset else None,
                  "engine": "LAM", "error": None}
        target = self.directory(avatar_id)
        target.mkdir(parents=True, exist_ok=True)
        if image:
            image.save(target / "source.png")
        if asset:
            (target / "asset.zip").write_bytes(asset)
        self.save(record)
        return record
