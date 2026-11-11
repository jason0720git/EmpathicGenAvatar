"""Per-turn targets, consumed at stitch time rather than ahead-of-time queues."""
from __future__ import annotations

import threading
import time
from typing import Callable, Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ControlHead(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    yaw_deg: float = Field(default=0, ge=-12, le=12)
    pitch_deg: float = Field(default=0, ge=-10, le=10)
    roll_deg: float = Field(default=0, ge=-6, le=6)


class ControlGaze(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)


class ControlMessage(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    type: Literal['control', 'control.reset']
    seq: int = Field(gt=0, strict=True)
    expression: Literal['angry','disgust','fear','happy','neutral','sad','surprise','contempt'] | None = None
    intensity: float | None = Field(default=None, ge=0, le=1)
    head: ControlHead | None = None
    gaze: ControlGaze | None = None

    @model_validator(mode='after')
    def channels(self):
        count = sum(getattr(self,k) is not None for k in ('expression','intensity','head','gaze'))
        if self.type == 'control' and not count:
            raise ValueError('control needs at least one channel')
        if self.type == 'control.reset' and count:
            raise ValueError('control.reset cannot carry channel targets')
        return self


class LiveControlState:
    """Latest-target mailbox. Values change only on the rendering thread.

    This controls calibrated residuals, not the native Audio2Motion condition.
    The acknowledgement PTS is the first generated frame, not display time.
    """
    def __init__(self, resolve: Callable, on_applied: Callable):
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._resolve = resolve
        self._on_applied = on_applied
        self._patch = {}
        self._target = {}
        self._seq = 0
        self._applied = 0
        self._closed = False
        self._current = None
        self._active = False
        self._expression = 'neutral'
        self._owned = set()
        self._owned_frames = {"face": 0, "gaze": 0, "head": 0}
        self._pacing = False
        self._playback_started = False
        self._playback_pts = -1
        self._last_feedback = 0.
        self._first_paced_frame = False
        self._last_stitch_pts = -1
        self._control_disabled = False

    def playback(self, payload: dict):
        if set(payload) != {'type','pts_ms'} or payload.get('type') != 'playback':
            raise ValueError('expected playback type and pts_ms only')
        pts = payload['pts_ms']
        if type(pts) is not int or pts < -1 or pts > 3_600_000:
            raise ValueError('invalid playback PTS')
        with self._condition:
            if self._closed or self._control_disabled:
                raise ValueError('playback control is closed')
            if pts == -1:
                if self._pacing:
                    raise ValueError('playback initialization already received')
                self._pacing = True
            else:
                if not self._pacing or pts < self._playback_pts:
                    raise ValueError('playback PTS must be monotonic after initialization')
                if pts > self._last_stitch_pts + 400:
                    raise ValueError('playback PTS exceeds generated video')
                self._playback_started = True
                self._playback_pts = pts
            self._last_feedback = time.monotonic()
            self._condition.notify_all()

    def wait_for_frame(self, pts_ms: int):
        """Bound future stitching, not audio/network delivery. Native thread only.

        Explicit feedback opts in. Offline/benchmark consumers retain their
        previous throughput. Closed or stale feedback can never strand SDK join.
        """
        timed_out = False
        with self._condition:
            if self._pacing and not self._first_paced_frame and pts_ms >= 0:
                self._first_paced_frame = True
                self._last_feedback = time.monotonic()
            while self._pacing and not self._closed:
                horizon = self._playback_pts + 800 if self._playback_started else 1200
                if pts_ms <= horizon:
                    break
                remaining = 5-(time.monotonic()-self._last_feedback)
                if remaining <= 0:
                    self._pacing = False
                    self._control_disabled = True
                    timed_out = True
                    break
                self._condition.wait(timeout=min(.1,remaining))
            self._last_stitch_pts = max(self._last_stitch_pts,pts_ms)
        if timed_out:
            self._on_applied({'type':'control.error','detail':'playback feedback timed out; live control disabled for this turn'})

    def receive(self, payload: dict) -> dict:
        command = ControlMessage.model_validate(payload)
        with self._lock:
            if self._closed:
                raise ValueError('turn is closed')
            if self._control_disabled:
                raise ValueError('live control disabled after playback feedback timeout')
            if command.seq <= self._seq:
                raise ValueError('seq must increase within this turn')
            patch = {} if command.type == 'control.reset' else {**self._patch, **command.model_dump(exclude_none=True, exclude={'type','seq'})}
            target = self._resolve(patch)
            self._patch, self._target = patch, target
            self._seq = command.seq
        return {'type':'control.received','seq':command.seq,'mode':'residual_only'}

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def diagnostics(self) -> dict:
        """Snapshot after the render thread joins. Includes the reset release."""
        with self._lock:
            return {"enabled": True, "last_received_seq": self._seq, "last_applied_seq": self._applied,
                    "channel_owned_frames": dict(self._owned_frames)}

    def apply(self, controls: dict, pts_ms: int, boundary_weight: float = 1) -> dict:
        with self._lock:
            if self._closed or not self._seq:
                return controls
            target, seq = self._target, self._seq
        baseline = np.asarray(controls.get('delta_exp',np.zeros((1,63))),dtype=np.float32).reshape(21,3)
        head_keys = ('delta_yaw','delta_pitch','delta_roll')
        baseline_head = np.array([controls.get(k,0.) for k in head_keys],dtype=np.float32)
        if self._current is None:
            self._current = (baseline.copy(),baseline_head.copy())
        current, current_head = self._current
        desired = baseline.copy()
        self._owned.update(k for k in ('face','gaze','head') if k in target)
        if 'face' in target:
            face_points = [i for i in range(21) if i not in (11,15)]
            desired[face_points] = target['face'][face_points]
        if 'gaze' in target:
            desired[[11,15]] = target['gaze'][[11,15]]
        desired_head = target.get('head',baseline_head)
        # Ditto adaptation of SOBIA's trajectory time-scale range. Mapping
        # slower attack to sad/fear is our engineering choice; SOBIA itself
        # varies trajectory styles. No anatomical regions are guessed from
        # Ditto's implicit keypoints. Each channel owns its clock.
        expression = target.get('expression',self._expression)
        face_tau = .28 if expression == 'happy' else .55 if expression in ('sad','fear') else .42
        if not target or np.linalg.norm(desired) < np.linalg.norm(current):
            face_tau = .60
        alpha = np.full((21,3),1-np.exp(-.04/face_tau))
        alpha[[11,15]] = 1-np.exp(-.04/.22)
        current += (desired-current)*alpha
        current_head += np.clip((desired_head-current_head)*(1-np.exp(-.04/.4)),-.24,.24)
        if 'face' not in self._owned:
            current[[i for i in range(21) if i not in (11,15)]] = baseline[[i for i in range(21) if i not in (11,15)]]
        if 'gaze' not in self._owned:
            current[[11,15]] = baseline[[11,15]]
        if 'head' not in self._owned:
            current_head[:] = baseline_head
        result = dict(controls)
        weight = float(np.clip(boundary_weight,0,1))
        output = baseline+(current-baseline)*weight
        output_head = baseline_head+(current_head-baseline_head)*weight
        result['delta_exp'] = output.reshape(1,63).copy()
        result.update(dict(zip(head_keys,output_head.tolist())))
        # Always retain final speech articulation while a live face override or
        # its reset tail is present. No deliberate lid closing is introduced.
        if 'face' in self._owned:
            result['preserve_speech_lips'] = True
            result['allow_smile_corners'] = expression == 'happy'
        self._active = bool(target) or not(np.allclose(current,baseline,atol=1e-6) and np.allclose(current_head,baseline_head,atol=1e-4))
        self._expression = expression
        if seq != self._applied:
            self._applied = seq
            self._on_applied({'type':'control.applied','seq':seq,'pts_ms':max(0,pts_ms),'mode':'residual_only',
                'head_deg':dict(zip(('yaw_deg','pitch_deg','roll_deg'),output_head.tolist())),
                'pupil_delta':output[[11,15]].tolist(),'affect_norm':float(np.linalg.norm(output))})
        if not self._active:
            self._owned.clear()
            self._current = None
            return controls
        if weight > 0:
            for channel in self._owned:
                self._owned_frames[channel] += 1
        return result
