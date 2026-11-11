"""Turn-local timing for the calibrated Ditto expression residual at 25 fps."""
from math import exp, log10
from random import Random

import numpy as np


COMPANION_EXPRESSION_POLICY = "sobia-companion-regional-v1"
SOBIA_REFERENCE_COMMIT = "b4ee194b"
FRAME_SECONDS = .04


def _smoothstep(value: float) -> float:
    t = max(0., min(1., value))
    return t * t * (3. - 2. * t)


def _follow(previous: float, target: float, tau: float) -> float:
    return previous + (target - previous) * (1. - exp(-FRAME_SECONDS / tau))


class CompanionExpression:
    """Scale existing brow/lid/cheek actions without introducing new keypoints.

    Adapted from SOBIA CompanionMotion's reaction envelope. A turn's style is
    reproducible. Articulation, native blinks, pupils and pose keep their owners.
    """

    def __init__(self, expression: str, intensity: float, turn_key: str):
        rng = Random(turn_key)
        tempo = rng.uniform(.84, 1.18) * (1.12 - .26 * intensity)
        soft = rng.random()
        self.brow_balance = rng.uniform(-.10, .10)
        caring = expression in ("sad", "fear")
        onset = .19 if expression == "surprise" else .48 if caring else .32
        self.rise = onset * tempo
        self.hold = (.18 + .32 * soft) * tempo
        self.fall = (.48 if expression == "surprise" else .74 + .34 * soft) * tempo
        self.brow_lag = .035 * tempo if caring else 0.
        self.lid_lag = .035 * tempo
        self.cheek_lag = .09 * tempo
        self.brow_rest = .37 if caring else .18
        self.age = 0.
        self.fast_energy = 0.
        self.slow_energy = 0.
        self.accent = 0.
        self.quiet_seconds = 0.
        self.gains = np.zeros(3, dtype=np.float32)
        self.frames = self.voiced_frames = self.accent_frames = self.boundary_frames = 0
        self.peak_targets = np.zeros(3)
        self.peak_gains = np.zeros(3)
        self.peak_components = np.zeros(3)

    def _envelope(self, lag: float, rise_scale: float, rest: float,
                  accent_share: float, boundary: float) -> float:
        age = max(0., self.age - lag)
        rise = self.rise * rise_scale
        attack = _smoothstep(age / rise)
        decay = _smoothstep((age - rise - self.hold) / self.fall)
        sustain = rest + (1. - rest) * .75 * self.accent * accent_share
        return attack * (1. - (1. - sustain) * decay) * (1. - .39 * boundary)

    def _advance(self, rms: float | None) -> None:
        # The PCM lead/tail is distinct from a quiet frame *within* a phrase.
        if rms is None:
            self.gains *= exp(-FRAME_SECONDS / .28)
            return
        voiced = rms >= .006
        self.voiced_frames += int(voiced)
        if not self.age and not voiced:
            return
        self.age += FRAME_SECONDS
        energy = max(0., min(1., (20. * log10(max(rms, 1e-7)) + 54.) / 35.))
        self.fast_energy = _follow(self.fast_energy, energy, .12)
        self.slow_energy = _follow(self.slow_energy, energy, .65)
        onset = max(0., min(1., 3. * (self.fast_energy - self.slow_energy)))
        self.accent = _follow(self.accent, onset, .15 if onset > self.accent else .28)
        self.quiet_seconds = 0. if voiced else self.quiet_seconds + FRAME_SECONDS
        # Release on a pause. A smooth return prevents a step at the next word.
        boundary = _smoothstep((self.quiet_seconds - .08) / .20)
        self.accent_frames += int(self.accent >= .20)
        self.boundary_frames += int(boundary > 0.)
        targets = (
            self._envelope(self.brow_lag, 1., self.brow_rest, 1., boundary),
            self._envelope(self.lid_lag, 1.12, .37, .65, boundary),
            self._envelope(self.cheek_lag, 1.26, .52, .44, boundary),
        )
        for index, target in enumerate(targets):
            self.gains[index] = _follow(self.gains[index], target, .07)
            self.peak_targets[index] = max(self.peak_targets[index], target)

    def apply(self, residual: np.ndarray, rms: float | None) -> np.ndarray:
        self._advance(rms)
        self.frames += 1
        np.maximum(self.peak_gains, self.gains, out=self.peak_gains)
        points = residual.copy().reshape(21, 3)
        brow, lids, cheek = self.gains
        # An asymmetric accent only attenuates the weaker side. Every output
        # remains within the signed displacement of its calibrated preset.
        points[1] *= brow * (1. - max(0., self.brow_balance))
        points[2] *= brow * (1. + min(0., self.brow_balance))
        points[[13, 16]] *= lids
        points[[3, 7, 14, 20]] *= cheek
        for index, region in enumerate(([1, 2], [13, 16], [3, 7, 14, 20])):
            peak = float(np.max(np.abs(points[region])))
            self.peak_components[index] = max(self.peak_components[index], peak)
        return points

    def diagnostics(self) -> dict:
        def regions(values):
            return dict(zip(("brow", "lid", "cheek_corner"), (round(float(v), 7) for v in values)))
        return {
            "stage": "automatic_residual_before_live_override_blink_and_stitch",
            "frame_seconds": FRAME_SECONDS, "rise_s": round(self.rise, 4),
            "hold_s": round(self.hold, 4), "fall_s": round(self.fall, 4),
            "region_lag_s": regions((self.brow_lag, self.lid_lag, self.cheek_lag)),
            "brow_balance": round(self.brow_balance, 4),
            "evaluated_frames": self.frames, "voiced_frames": self.voiced_frames,
            "accent_at_least_0_2_frames": self.accent_frames, "pause_boundary_frames": self.boundary_frames,
            "peak_target_gain": regions(self.peak_targets), "peak_smoothed_gain": regions(self.peak_gains),
            "peak_abs_residual_component": regions(self.peak_components),
        }
