"""SOBIA-inspired deterministic face/head/gaze policy for rigged 3DGS.

This is an explicit, inspectable rule-based adapter, not the trained human-data
empathy model. A2F owns oral speech articulation. Policy owns eye direction,
blink, head movement, upper-face affect and bounded mouth-corner expression.
"""

from __future__ import annotations

import math
import json
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .gaussian_a2f import ARKIT_NAMES, canonical_weights

EMOTIONS = ("neutral", "happy", "sad", "angry", "fear", "surprise", "disgust", "contempt")
INTENTS = ("attentive", "supportive", "encouraging", "celebrating", "explaining")
MOUTH_CORNERS = frozenset(("mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight", "mouthDimpleLeft", "mouthDimpleRight"))
ARTICULATION_CHANNELS = frozenset(name for name in ARKIT_NAMES if (name.startswith(("mouth", "jaw")) or name == "tongueOut") and name not in MOUTH_CORNERS)

# Shared with browser preview: 100% reaches the emotion's full rig target.
# Opposing actions are not all maximized together. Speech articulation stays A2F-owned.
_PRESETS = json.loads(Path(__file__).with_name("emotion_profiles.json").read_text())


def _bounded(value: float, low: float, high: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Behavior values must be finite")
    return max(low, min(high, result))


@dataclass(frozen=True)
class BehaviorPlan:
    emotion: str = "neutral"
    intensity: float = 0.0
    intent: str = "attentive"
    nod: bool = False
    nod_start_seconds: float = .45
    nod_duration_seconds: float = .72
    nod_amplitude_degrees: float = 3.5
    gaze: dict[str, float] = field(default_factory=lambda: {"x": 0., "y": 0.})
    head: dict[str, float] = field(default_factory=lambda: {"pitch": 0., "yaw": 0., "roll": 0.})
    source: str = "rule_based_sobia_inspired"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["head_units"] = "degrees"
        result["provenance"] = "LLM tool selects intent in auto; manual selection overrides it. Deterministic ARKit composition; no trained empathy model loaded."
        return result


class BehaviorController:
    """One controller per turn/session; frame composition is deterministic."""

    def from_affect(self, emotion: str = "neutral", intensity: float = 0.0, *, intent: str = "explaining",
                    nod: bool = False, gaze: Mapping[str, float] | None = None,
                    head: Mapping[str, float] | None = None, nod_start_seconds: float = .45,
                    nod_duration_seconds: float = .72, nod_amplitude_degrees: float = 3.5,
                    source: str = "rule_based_sobia_inspired") -> BehaviorPlan:
        if emotion not in EMOTIONS:
            raise ValueError(f"Unsupported expression: {emotion}")
        if intent not in INTENTS:
            raise ValueError(f"Unsupported behavior intent: {intent}")
        strength = _bounded(intensity, 0., 1.)
        target_gaze = {"x": 0., "y": -.06 * strength if emotion == "sad" else 0.}
        target_head = {"pitch": 1.8 * strength if emotion == "sad" else -.9 * strength if emotion == "surprise" else 0.,
                       "yaw": 0., "roll": -.8 * strength if intent == "supportive" else 0.}
        if intent == "attentive":
            target_head["roll"] = -.7
        if gaze is not None:
            if set(gaze) - {"x", "y"}:
                raise ValueError("Gaze uses x and y")
            target_gaze.update({axis: _bounded(value, -1., 1.) for axis, value in gaze.items()})
        if head is not None:
            bounds = {"pitch": 10., "yaw": 12., "roll": 6.}
            if set(head) - bounds.keys():
                raise ValueError("Head uses pitch, yaw and roll in degrees")
            target_head.update({axis: _bounded(value, -bounds[axis], bounds[axis]) for axis, value in head.items()})
        return BehaviorPlan(emotion, strength, intent, bool(nod), _bounded(nod_start_seconds, 0., 10.),
                            _bounded(nod_duration_seconds, .3, 1.5), _bounded(nod_amplitude_degrees, 0., 6.),
                            target_gaze, target_head, source)

    def mix_frame(self, coefficients: Mapping[str, float] | None, time_seconds: float,
                  plan: BehaviorPlan | None = None, *, speaking: bool = True,
                  idle_motion: bool = True) -> dict[str, Any]:
        plan = plan or self.from_affect(intent="attentive")
        t = max(0., _bounded(time_seconds, 0., 1e9))
        raw = canonical_weights(coefficients or {})
        mixed = dict.fromkeys(ARKIT_NAMES, 0.)
        if speaking:
            for key in ARTICULATION_CHANNELS:
                mixed[key] = raw[key]
        # Smooth expression onset; callers interpolate successive outputs in
        # playback time. Never decay a sad/supportive expression into a smile.
        entry = min(1., t / .26)
        entry = entry * entry * (3. - 2. * entry)
        strength = plan.intensity * entry
        for key, value in _PRESETS[plan.emotion].items():
            if not (speaking and key in ARTICULATION_CHANNELS):
                mixed[key] = value * strength
        if plan.intent == "attentive" and plan.emotion == "neutral":
            mixed["browInnerUp"] = .055 * entry
        if plan.intent == "supportive" and plan.emotion == "neutral":
            mixed["browInnerUp"] = .15 * strength
        # Mouth corners may contribute to A2F's pronunciation. Retain a small
        # bounded share unless it would contradict negative/supportive affect.
        no_bright_smile = plan.emotion in ("sad", "angry", "fear", "disgust") or plan.intent == "supportive"
        for key in MOUTH_CORNERS:
            # Affect owns these channels. Attenuating them only during speech
            # made visible emotion disappear precisely while the avatar replied.
            if speaking:
                mixed[key] = max(mixed[key], raw[key] * .25)
        if no_bright_smile:
            for key in ("mouthSmileLeft", "mouthSmileRight", "mouthDimpleLeft", "mouthDimpleRight"):
                mixed[key] = min(mixed[key], .035)

        gaze = dict(plan.gaze)
        head = dict(plan.head)
        if idle_motion:
            # Procedural baseline is labelled; it is not a measured user cue.
            head["yaw"] += .28 * math.sin(t * .73)
            head["pitch"] += .18 * math.sin(t * .57)
        nod_phase = (t - plan.nod_start_seconds) / plan.nod_duration_seconds
        if plan.nod and 0. <= nod_phase <= 1.:
            head["pitch"] += plan.nod_amplitude_degrees * math.sin(math.pi * nod_phase) ** 2
        # Positive gaze x = avatar's right, positive y = up.
        x, y = gaze["x"] * .55, gaze["y"] * .55
        mixed["eyeLookInLeft"], mixed["eyeLookOutRight"] = max(0., x), max(0., x)
        mixed["eyeLookOutLeft"], mixed["eyeLookInRight"] = max(0., -x), max(0., -x)
        for side in ("Left", "Right"):
            mixed[f"eyeLookUp{side}"] = max(0., y)
            mixed[f"eyeLookDown{side}"] = max(0., -y)
        # Clock-driven blink also works when there is no speech/A2F stream.
        blink_phase = (t + 1.3) % 4.3
        blink = math.sin(math.pi * blink_phase / .36) ** 2 if blink_phase < .36 and idle_motion else 0.
        for side in ("Left", "Right"):
            mixed[f"eyeBlink{side}"] = blink
            mixed[f"eyeWide{side}"] *= 1. - blink
        head_limits = {"pitch": 10., "yaw": 12., "roll": 6.}
        head = {axis: _bounded(value, -head_limits[axis], head_limits[axis]) for axis, value in head.items()}
        return {
            "time_seconds": t,
            "weights": {key: round(_bounded(value, 0., 1.), 6) for key, value in mixed.items()},
            "raw_weights": raw,
            "head": {key: round(value, 5) for key, value in head.items()},
            "head_units": "degrees",
            "gaze": gaze,
            "behavior": plan.as_dict(),
            "composition": {"articulation_owner": "nvidia_a2f" if speaking else "neutral",
                            "expression_owner": plan.source, "eye_head_owner": plan.source,
                            "smile_guard": no_bright_smile, "speaking": speaking},
        }
