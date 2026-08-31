from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .models import AvatarOut, MotionPlan, RendererOut, Viseme


@dataclass
class Preparation:
    cache_ref: str | None


class AvatarRenderer:
    mode: str = "preview"

    async def prepare(self, avatar: AvatarOut, source_path: Path) -> Preparation:
        raise NotImplementedError

    async def render(self, avatar: AvatarOut, *, session_id: str, turn_id: str, text: str, motion_plan: MotionPlan | None = None) -> tuple[list[Viseme], RendererOut]:
        raise NotImplementedError

    async def cancel(self, session_id: str) -> None:
        return None

    async def delete(self, avatar_id: str) -> None:
        return None


class PreviewRenderer(AvatarRenderer):
    """Protocol-compatible local renderer; visual/audio are synthesized by the browser."""

    mode = "preview"

    async def prepare(self, avatar: AvatarOut, source_path: Path) -> Preparation:
        await asyncio.sleep(0.04)
        return Preparation(cache_ref=f"preview:{avatar.id}")

    async def render(self, avatar: AvatarOut, *, session_id: str, turn_id: str, text: str, motion_plan: MotionPlan | None = None) -> tuple[list[Viseme], RendererOut]:
        visemes = [Viseme(at_ms=index * 105, value=round(0.28 + ((ord(char) * 17) % 63) / 100, 2)) for index, char in enumerate(text[:80]) if not char.isspace()]
        return visemes, RendererOut(mode="preview", status="browser-audio-reactive-preview", applied_motion=motion_plan)


class RemoteRenderer(AvatarRenderer):
    """Adapter for a GPU worker implementing workers/avatar/CONTRACT.md."""

    mode = "remote"

    def __init__(self, base_url: str, shared_token: str | None = None, stream_prefix: str = "/avatar-stream/", render_profile: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.shared_token = shared_token
        self.headers = {"X-Worker-Token": shared_token} if shared_token else {}
        self.stream_prefix = stream_prefix.rstrip("/") + "/"
        self.render_profile = render_profile

    async def prepare(self, avatar: AvatarOut, source_path: Path) -> Preparation:
        payload: dict[str, Any] = {
            "avatar_id": avatar.id,
            "source_path": str(source_path),
            "avatar_version": 1,
            "quality": avatar.quality.model_dump() if avatar.quality else None,
        }
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{self.base_url}/v1/avatars/prepare", json=payload, headers=self.headers)
            response.raise_for_status()
        body = response.json()
        return Preparation(cache_ref=body["cache_ref"])

    async def render(self, avatar: AvatarOut, *, session_id: str, turn_id: str, text: str, motion_plan: MotionPlan | None = None) -> tuple[list[Viseme], RendererOut]:
        payload: dict[str, Any] = {"avatar_id": avatar.id, "session_id": session_id, "turn_id": turn_id, "text": text}
        if self.render_profile is not None:
            payload["render_profile"] = self.render_profile
        if motion_plan is not None:
            payload["motion_plan"] = motion_plan.model_dump(mode="json")
        # First Ditto invocation initializes several TensorRT engines and can
        # take longer than an interactive turn. Subsequent warm renders are
        # expected to complete well below this ceiling.
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{self.base_url}/v1/turns/render", json=payload, headers=self.headers)
            response.raise_for_status()
        body = response.json()
        visemes = [Viseme.model_validate(item) for item in body.get("visemes", [])]
        stream_url = body.get("stream_url")
        if isinstance(stream_url, str) and stream_url.startswith("/avatar-stream/"):
            stream_url = self.stream_prefix + stream_url.removeprefix("/avatar-stream/")
        # The GPU worker is private to Docker. Serve completed video through
        # the control API instead of exposing its network address to browsers.
        if isinstance(stream_url, str) and stream_url.startswith("/v1/assets/renders/"):
            stream_url = "/api/rendered/" + stream_url.rsplit("/", 1)[-1]
        elif isinstance(stream_url, str) and stream_url.startswith("/v1/assets/live/"):
            stream_url = "/api/live-media/" + stream_url.rsplit("/", 1)[-1]
        audio_url = body.get("audio_url")
        if isinstance(audio_url, str) and audio_url.startswith("/v1/assets/audio/"):
            audio_url = "/api/live-audio/" + audio_url.rsplit("/", 1)[-1]
        # An explicit null means the sync-reference MP4 path intentionally did
        # not apply live controls; only absent legacy fields inherit the local
        # request for preview compatibility.
        applied_motion = MotionPlan.model_validate(body["applied_motion"]) if body.get("applied_motion") else (motion_plan if "applied_motion" not in body else None)
        return visemes, RendererOut(mode="remote", status=body.get("status", "queued"), stream_url=stream_url, audio_url=audio_url, applied_motion=applied_motion)

    async def read_live_asset(self, filename: str, asset_type: str) -> tuple[bytes, str]:
        if Path(filename).name != filename or asset_type not in {"live", "audio"}:
            raise FileNotFoundError(filename)
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.get(f"{self.base_url}/v1/assets/{asset_type}/{filename}", headers=self.headers)
            if response.status_code == 404:
                raise FileNotFoundError(filename)
            response.raise_for_status()
        default = "multipart/x-mixed-replace; boundary=frame" if asset_type == "live" else "audio/wav"
        return response.content, response.headers.get("content-type", default)

    async def read_render(self, filename: str) -> tuple[bytes, str]:
        if Path(filename).name != filename or not filename.endswith(".mp4"):
            raise FileNotFoundError(filename)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/v1/assets/renders/{filename}", headers=self.headers)
            if response.status_code == 404:
                raise FileNotFoundError(filename)
            response.raise_for_status()
        return response.content, response.headers.get("content-type", "video/mp4")

    async def cancel(self, session_id: str) -> None:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.post(f"{self.base_url}/v1/turns/cancel", json={"session_id": session_id}, headers=self.headers)
            response.raise_for_status()

    async def delete(self, avatar_id: str) -> None:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.delete(f"{self.base_url}/v1/avatars/{avatar_id}", headers=self.headers)
            response.raise_for_status()
