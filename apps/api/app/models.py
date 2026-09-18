from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


RendererMethod = Literal["ditto", "ditto_realtime", "ditto_realtime_fast", "ditto_realtime_trt10", "fast"]
AvatarAffect = Literal["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise", "contempt"]
ExpressionRenderMode = Literal["off", "native", "legacy", "speech_safe"]


class CreateSessionIn(BaseModel):
    mode: Literal["realtime", "wav_test"] = "realtime"
    avatar_id: str
    renderer_method: RendererMethod = "ditto"
    session_instruction: str | None = Field(default=None, max_length=6_000)


class SessionOut(BaseModel):
    mode: Literal["realtime", "wav_test"] = "realtime"
    id: str
    avatar_id: str
    state: Literal["active", "ended"]
    created_at: datetime
    renderer_method: RendererMethod = "ditto"
    session_instruction: str | None = None


class TurnIn(BaseModel):
    expression_render_mode: ExpressionRenderMode = "speech_safe"
    text: str = Field(min_length=1, max_length=4_000)
    client_turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    motion_plan: "MotionPlan | None" = None
    # A manual display-affect selection for visual evaluation. When present,
    # the conversation provider must not spend a Realtime tool call.
    affect_override: "AffectIntent | None" = None
    # A missing plan delegates to the server-side behavior policy.  This flag
    # lets trusted operator tools intentionally hold a neutral pose as well.
    motion_override: bool = False

    @model_validator(mode="after")
    def override_requires_plan(self):
        if self.motion_override and self.motion_plan is None:
            raise ValueError("motion_override requires motion_plan")
        if self.motion_override and self.affect_override is not None:
            raise ValueError("motion_override cannot be combined with affect_override")
        return self


class TurnTelemetryIn(BaseModel):
    """Timing-only browser telemetry. Conversation text and media stay out."""

    turn_id: str = Field(min_length=1, max_length=128)
    event: Literal[
        "turn_submitted", "turn_response", "socket_open", "first_packet",
        "first_video_decoded", "playback_started", "playback_ended",
        "jpeg_decode_failed", "video_pts_gap",
        "socket_error", "socket_closed", "playout_drift", "render_requested", "first_frame_presented", "visual_transition",
    ]
    elapsed_ms: int = Field(ge=0, le=300_000)
    details: dict[str, int | float | str | bool] = Field(default_factory=dict)


class HeadPose(BaseModel):
    """Avatar-relative pose offsets in degrees, not user-face measurements."""

    yaw_deg: float = Field(default=0, ge=-12, le=12)
    pitch_deg: float = Field(default=0, ge=-10, le=10)
    roll_deg: float = Field(default=0, ge=-6, le=6)


class GazeIntent(BaseModel):
    """Semantic gaze target for renderer adapters; Ditto v0 uses a small head cue.

    ``y=-1`` is a downward cue and ``y=1`` an upward cue.  These values are
    avatar-relative intent, never camera-derived user measurements.
    """

    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)


class NodIntent(BaseModel):
    start_ms: int = Field(default=300, ge=0, le=10_000)
    duration_ms: int = Field(default=460, ge=260, le=1_200)
    amplitude_deg: float = Field(default=5, ge=2, le=8)


class AffectIntent(BaseModel):
    """One compact, turn-local display affect proposed by the dialogue model.

    This is the expression the avatar should show in its reply, not a claim
    about a user's emotion or a persistent user profile.
    """

    emotion: AvatarAffect
    intensity: float = Field(ge=0, le=1)


class MotionPlan(BaseModel):
    """Safe, renderer-independent controls for one avatar turn.

    ``expression`` and ``intensity`` are the only semantic controls accepted
    from the affect layer. Renderer adapters turn them into their own bounded
    emotion conditions, pose cues, and calibrated facial presets.
    """

    expression: AvatarAffect = "neutral"
    intensity: float = Field(default=0.35, ge=0, le=1)
    # Manual button turns use this bounded high-contrast preset so evaluators
    # can verify each affect without changing automatic conversation behavior.
    expression_test: bool = False
    expression_render_mode: ExpressionRenderMode = "speech_safe"
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
    llm: Literal["demo", "ollama", "openai-realtime"]
    empathic_debug_log: bool = False


class ExpressionFeedbackIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    issue: Literal["good", "mouth_blur", "lip_shape", "audio_ahead", "video_ahead", "weak_expression", "no_media"]
    severity: int = Field(default=2, ge=0, le=3)
    at_ms: int | None = Field(default=None, ge=0, le=300_000)
    note: str = Field(default="", max_length=1000)
