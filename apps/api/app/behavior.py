"""Minimal affect-to-renderer adapter.

The dialogue model supplies one structured, turn-local affect through its
Realtime function call. This module intentionally does not inspect text, keep
an emotion history, or infer a user state. It only turns that validated
two-field contract into the renderer's bounded motion request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AffectIntent, GazeIntent, HeadPose, MotionPlan, NodIntent


@dataclass(frozen=True)
class BehaviorDecision:
    """Traceable result of the single affect tool output for a turn."""

    affect: AffectIntent
    motion_plan: MotionPlan
    source: str

    def as_log_dict(self) -> dict[str, object]:
        return {
            "affect": self.affect.model_dump(mode="json"),
            "motion_plan": self.motion_plan.model_dump(mode="json"),
            "source": self.source,
        }


class BehaviorPlanner:
    """Map a validated display affect to simple, bounded Ditto controls."""

    def from_affect(
        self,
        affect: AffectIntent,
        *,
        source: str = "realtime_tool",
        expression_test: bool = False,
    ) -> BehaviorDecision:
        """Build one renderer plan without text rules or stateful policy.

        The Ditto worker owns the calibrated ``delta_exp`` preset. These small
        posture cues are declarative and scale linearly with the
        model-selected intensity; they are not a second classifier.
        """

        intensity = affect.intensity
        head = HeadPose()
        gaze = GazeIntent()
        nod: NodIntent | None = None
        if expression_test:
            # A/B evaluation preset: intentionally more separated than auto,
            # but still within the public pose and gaze safety limits.
            presets = {
                "neutral": (0.0, 0.0, 0.0, 0.0),
                "angry": (0.0, 1.4, 0.0, 0.0),
                "disgust": (-2.0, 0.8, 0.0, 0.0),
                "fear": (0.0, -1.8, 0.0, 0.0),
                "contempt": (2.0, -0.6, 0.0, 0.0),
                "happy": (1.5, -2.9, 0.35, 0.45),
                "sad": (-1.2, 3.8, -0.25, -0.8),
                "surprise": (0.4, -4.5, 0.1, 0.75),
            }
            yaw, pitch, gaze_x, gaze_y = presets[affect.emotion]
            head = HeadPose(yaw_deg=yaw * intensity, pitch_deg=pitch * intensity)
            gaze = GazeIntent(x=gaze_x * intensity, y=gaze_y * intensity)
            if affect.emotion == "happy" and intensity >= 0.5:
                nod = NodIntent(start_ms=420, duration_ms=560, amplitude_deg=5.0 * intensity)
        elif affect.emotion == "sad":
            head = HeadPose(pitch_deg=2.2 * intensity)
            gaze = GazeIntent(y=-0.6 * intensity)
        elif affect.emotion == "happy":
            head = HeadPose(pitch_deg=-0.7 * intensity)
        elif affect.emotion == "surprise":
            head = HeadPose(pitch_deg=-0.55 * intensity)

        return BehaviorDecision(
            affect=affect,
            motion_plan=MotionPlan(
                expression=affect.emotion,
                intensity=intensity,
                expression_test=expression_test,
                head=head,
                gaze=gaze,
                nod=nod,
            ),
            source=source,
        )

    def fallback(self) -> BehaviorDecision:
        """Use only when a non-Realtime backend has no affect tool contract."""

        return self.from_affect(AffectIntent(emotion="neutral", intensity=0), source="backend_neutral_fallback")

    def resolve(self, *, affect: AffectIntent | None, requested: MotionPlan | None, motion_override: bool) -> BehaviorDecision:
        """Keep an explicit operator override without reviving text policy."""

        automatic = self.from_affect(affect) if affect is not None else self.fallback()
        if not motion_override:
            return automatic
        assert requested is not None  # validated by TurnIn
        return BehaviorDecision(
            affect=automatic.affect,
            motion_plan=requested,
            source="manual_override",
        )
