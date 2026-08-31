from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ImageQuality(BaseModel):
    width: int
    height: int
    score: int = Field(ge=0, le=100)
    hints: list[str] = Field(default_factory=list)


class AvatarOut(BaseModel):
    id: str
    name: str
    persona: str
    voice: str
    status: Literal["ready", "preparing", "failed"]
    source_url: str | None = None
    created_at: datetime
    engine: str
    quality: ImageQuality | None = None


RendererMethod = Literal["ditto", "ditto_realtime", "ditto_realtime_fast", "fast"]


class CreateSessionIn(BaseModel):
    avatar_id: str
    renderer_method: RendererMethod = "ditto"


class SessionOut(BaseModel):
    id: str
    avatar_id: str
    state: Literal["active", "ended"]
    created_at: datetime
    renderer_method: RendererMethod = "ditto"


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    client_turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    motion_plan: "MotionPlan | None" = None


class TurnTelemetryIn(BaseModel):
    """Timing-only browser telemetry. Conversation text and media stay out."""

    turn_id: str = Field(min_length=1, max_length=128)
    event: Literal[
        "turn_submitted", "turn_response", "socket_open", "first_packet",
        "first_video_decoded", "playback_started", "playback_ended",
        "jpeg_decode_failed", "video_pts_gap",
    ]
    elapsed_ms: int = Field(ge=0, le=300_000)
    details: dict[str, int | float | str | bool] = Field(default_factory=dict)


class HeadPose(BaseModel):
    """Avatar-relative pose offsets in degrees, not user-face measurements."""

    yaw_deg: float = Field(default=0, ge=-12, le=12)
    pitch_deg: float = Field(default=0, ge=-10, le=10)
    roll_deg: float = Field(default=0, ge=-6, le=6)


class GazeIntent(BaseModel):
    """Semantic gaze target for renderer adapters; Ditto v0 uses a small head cue."""

    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)


class NodIntent(BaseModel):
    start_ms: int = Field(default=300, ge=0, le=10_000)
    duration_ms: int = Field(default=460, ge=260, le=1_200)
    amplitude_deg: float = Field(default=5, ge=2, le=8)


class MotionPlan(BaseModel):
    """Safe, renderer-independent controls for one avatar turn.

    Expression is a coarse Ditto conditioning label in v0.1. It is deliberately
    not an arbitrary facial deformation vector.
    """

    expression: Literal["neutral", "warm", "concern"] = "neutral"
    head: HeadPose = Field(default_factory=HeadPose)
    gaze: GazeIntent = Field(default_factory=GazeIntent)
    nod: NodIntent | None = None


class Viseme(BaseModel):
    at_ms: int = Field(ge=0)
    value: float = Field(ge=0, le=1)


class RendererOut(BaseModel):
    mode: Literal["preview", "remote"]
    status: str
    stream_url: str | None = None
    audio_url: str | None = None
    applied_motion: MotionPlan | None = None


class TurnOut(BaseModel):
    turn_id: str
    assistant_text: str
    visemes: list[Viseme]
    renderer: RendererOut


class HealthOut(BaseModel):
    status: Literal["ok"]
    engine: Literal["preview", "remote"]
    llm: Literal["demo", "ollama"]
