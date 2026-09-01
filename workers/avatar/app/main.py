from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import queue
import re
import secrets
import subprocess
import struct
import sys
import threading
import time
import traceback
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field


class PrepareIn(BaseModel):
    avatar_id: str = Field(min_length=1, max_length=128)
    avatar_version: int = Field(ge=1)
    source_path: str
    quality: dict | None = None


class IdleIn(PrepareIn):
    """One-shot full-frame idle-loop preparation for an approved avatar."""

    variants: int = Field(default=3, ge=1, le=3)


class RenderIn(BaseModel):
    avatar_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    audio_path: str | None = None
    audio_streaming: bool = False
    text: str = Field(default="", max_length=4_000)
    # Deliberately a named product preset, never an arbitrary client-supplied
    # diffusion-step count. This keeps the quality baseline reproducible.
    render_profile: Literal["quality", "fast", "fast_preroll9", "fast_preroll5"] = "quality"
    motion_plan: "MotionPlan | None" = None


class HeadPose(BaseModel):
    yaw_deg: float = Field(default=0, ge=-12, le=12)
    pitch_deg: float = Field(default=0, ge=-10, le=10)
    roll_deg: float = Field(default=0, ge=-6, le=6)


class GazeIntent(BaseModel):
    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)


class NodIntent(BaseModel):
    start_ms: int = Field(default=300, ge=0, le=10_000)
    duration_ms: int = Field(default=460, ge=260, le=1_200)
    amplitude_deg: float = Field(default=5, ge=2, le=8)


class MotionPlan(BaseModel):
    """The worker-side subset of behavior.v0.1 used by the Ditto adapter."""

    expression: Literal["neutral", "warm", "concern"] = "neutral"
    head: HeadPose = Field(default_factory=HeadPose)
    gaze: GazeIntent = Field(default_factory=GazeIntent)
    nod: NodIntent | None = None


# Ditto's upstream ConditionHandler labels: Angry, Disgust, Fear, Happy,
# Neutral, Sad, Surprise, Contempt. These are deliberately coarse v0.1
# choices; arbitrary delta_exp vectors stay internal until calibrated.
DITTO_EMOTION_INDEX = {"warm": 3, "neutral": 4, "concern": 5}
# StreamSDK prepends three 40 ms chunks for its causal frontend and its
# Audio2Motion overlap adds another ten frames.  Those 13 frames are context,
# not part of the caller's WAV timeline, and must never be presented at PTS 0.
DITTO_CHUNKSIZE = (3, 5, 2)
DITTO_PREROLL_FRAMES = 13


def build_ditto_ctrl_info(plan: MotionPlan, frame_count: int, fps: int = 25, frame_offset: int = 0) -> dict[int, dict[str, float]]:
    """Convert safe turn-level controls into Ditto's documented frame controls.

    Ditto accepts pose offsets in degrees. Its public online API does not expose
    an independent numeric eye-gaze vector, so v0.1 turns gaze intent into a
    deliberately small head cue rather than pretending it controls pupils.
    """
    gaze_yaw = plan.gaze.x * 3.0
    gaze_pitch = -plan.gaze.y * 2.0
    base = {
        "delta_yaw": plan.head.yaw_deg + gaze_yaw,
        "delta_pitch": plan.head.pitch_deg + gaze_pitch,
        "delta_roll": plan.head.roll_deg,
    }
    total_frames = frame_count + frame_offset
    controls: dict[int, dict[str, float]] = {frame: dict(base) for frame in range(total_frames)}
    if plan.nod is None:
        return controls

    start_frame = min(total_frames - 1, frame_offset + round(plan.nod.start_ms / 1_000 * fps))
    duration_frames = max(2, round(plan.nod.duration_ms / 1_000 * fps))
    end_frame = min(total_frames, start_frame + duration_frames)
    for frame in range(start_frame, end_frame):
        phase = (frame - start_frame) / max(1, end_frame - start_frame - 1)
        # Smooth 0 → peak → 0 pitch envelope. The amplitude is bounded by
        # NodIntent, so camera-derived noise cannot create a violent motion.
        envelope = float(np.sin(np.pi * phase))
        controls[frame]["delta_pitch"] = base["delta_pitch"] + plan.nod.amplitude_deg * envelope
    return controls


def build_idle_ctrl_info(variant: int, frame_count: int) -> dict[int, dict[str, float]]:
    """A conservative, seamless idle trajectory in Ditto's pose space.

    The paths return to their start position so browser-side looping does not
    create a pose jump. Mouth movement remains audio-driven and therefore
    stays closed for the silent idle signal.
    """
    controls: dict[int, dict[str, float]] = {}
    cycles = (1.0, 1.25, 0.75)[variant % 3]
    phase_offset = (0.0, 0.7, 1.4)[variant % 3]
    for frame in range(frame_count):
        phase = 2 * np.pi * cycles * frame / max(1, frame_count - 1)
        yaw = 0.8 * np.sin(phase + phase_offset)
        pitch = 0.38 * np.sin(phase * 0.5 + phase_offset) + 0.16 * np.sin(phase * 2)
        roll = 0.22 * np.sin(phase * 0.7 + phase_offset)
        # Variant two includes one deliberately tiny acknowledgement nod.
        if variant % 3 == 2:
            nod_phase = frame / max(1, frame_count - 1)
            pitch += 1.15 * np.sin(np.pi * nod_phase) ** 2
        controls[frame] = {
            "delta_yaw": float(yaw),
            "delta_pitch": float(pitch),
            "delta_roll": float(roll),
        }
    return controls


class CancelIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class WorkerConfig:
    data_root: Path
    mode: Literal["stub", "ditto_batch", "ditto_live", "ditto_realtime", "musetalk_live"]
    ditto_root: Path
    model_root: Path
    config_path: Path
    sampling_timesteps: int
    fast_sampling_timesteps: int
    warm_media_path: bool
    profile_first_turn: bool
    musetalk_root: Path
    musetalk_model_root: Path
    musetalk_batch_size: int
    liveportrait_root: Path
    liveportrait_model_root: Path
    liveportrait_motion_frames: int
    shared_token: str | None = None

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        mode = os.getenv("AVATAR_RENDER_MODE", "stub").lower()
        if mode not in {"stub", "ditto_batch", "ditto_live", "ditto_realtime", "musetalk_live"}:
            raise ValueError("AVATAR_RENDER_MODE must be stub, ditto_batch, ditto_live, ditto_realtime, or musetalk_live")
        # Ditto's public default is aimed at offline quality.  Four steps is
        # our explicit conversational preset: it materially reduces the
        # first-audio-frame wait while retaining enough denoising for the
        # small, front-facing live-avatar plane.  Deployments can raise this
        # independently for a quality tier.
        sampling_timesteps = int(os.getenv("DITTO_SAMPLING_TIMESTEPS", "4"))
        if not 1 <= sampling_timesteps <= 50:
            raise ValueError("DITTO_SAMPLING_TIMESTEPS must be between 1 and 50")
        fast_sampling_timesteps = int(os.getenv("DITTO_FAST_SAMPLING_TIMESTEPS", "2"))
        if not 1 <= fast_sampling_timesteps < sampling_timesteps:
            raise ValueError("DITTO_FAST_SAMPLING_TIMESTEPS must be at least 1 and lower than DITTO_SAMPLING_TIMESTEPS")
        return cls(
            data_root=Path(os.getenv("AVATAR_DATA_ROOT", "/data")).resolve(),
            mode=mode,
            ditto_root=Path(os.getenv("DITTO_ROOT", "/opt/ditto")).resolve(),
            model_root=Path(os.getenv("DITTO_MODEL_ROOT", "/models/ditto/ditto_pytorch")).resolve(),
            config_path=Path(os.getenv("DITTO_CONFIG", "/models/ditto/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl")).resolve(),
            sampling_timesteps=sampling_timesteps,
            fast_sampling_timesteps=fast_sampling_timesteps,
            warm_media_path=os.getenv("DITTO_WARM_MEDIA_PATH", "false").strip().lower() in {"1", "true", "yes"},
            profile_first_turn=os.getenv("DITTO_PROFILE_FIRST_TURN", "false").strip().lower() in {"1", "true", "yes"},
            musetalk_root=Path(os.getenv("MUSETALK_ROOT", "/opt/musetalk")).resolve(),
            musetalk_model_root=Path(os.getenv("MUSETALK_MODEL_ROOT", "/models/musetalk")).resolve(),
            musetalk_batch_size=max(1, int(os.getenv("MUSETALK_BATCH_SIZE", "8"))),
            liveportrait_root=Path(os.getenv("LIVEPORTRAIT_ROOT", "/opt/liveportrait")).resolve(),
            liveportrait_model_root=Path(os.getenv("LIVEPORTRAIT_MODEL_ROOT", "/models/liveportrait")).resolve(),
            liveportrait_motion_frames=max(12, min(150, int(os.getenv("LIVEPORTRAIT_MOTION_FRAMES", "50")))),
            shared_token=os.getenv("WORKER_SHARED_TOKEN") or None,
        )


class CacheStore:
    def __init__(self, root: Path):
        self.root = root

    def setup(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, avatar_id: str, body: dict) -> None:
        self._path(avatar_id).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    def get(self, avatar_id: str) -> dict:
        path = self._path(avatar_id)
        if not path.is_file():
            raise KeyError(avatar_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, avatar_id: str) -> None:
        self._path(avatar_id).unlink(missing_ok=True)

    def _path(self, avatar_id: str) -> Path:
        safe = hashlib.sha256(avatar_id.encode()).hexdigest()
        return self.root / f"{safe}.json"


class DittoBatchRuntime:
    """Safe subprocess adapter for upstream Ditto batch inference.

    `stream_pipeline_online.StreamSDK` is the correct primitive for the
    production media path. This validation renderer uses the official CLI so
    it stays reliable while the LiveKit frame publisher is integrated.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    async def synthesize(self, text: str, output: Path) -> Path:
        """Create a local WAV without an account or a cloud TTS dependency.

        eSpeak NG is the functional Korean default for this GPU POC. Replace
        it with the CosyVoice service before public product deployment.
        """
        process = await asyncio.create_subprocess_exec(
            "espeak-ng", "-v", "ko", "-s", "165", "-w", str(output), text,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output.is_file() or output.stat().st_size < 128:
            detail = stderr.decode("utf-8", errors="replace")[-500:]
            raise HTTPException(status_code=502, detail=f"Local TTS failed: {detail or 'no audio output'}")
        return output

    async def render(self, body: RenderIn, source: Path, output: Path) -> None:
        audio = safe_data_path(self.config.data_root, body.audio_path) if body.audio_path else output.with_suffix(".wav")
        if not body.audio_path:
            await self.synthesize(body.text, audio)
        if not audio.is_file() or audio.suffix.lower() not in {".wav", ".flac", ".mp3"}:
            raise HTTPException(status_code=422, detail="audio_path must be a readable WAV/FLAC/MP3 inside AVATAR_DATA_ROOT")
        inference = self.config.ditto_root / "inference.py"
        if not inference.is_file() or not self.config.model_root.is_dir() or not self.config.config_path.is_file():
            raise HTTPException(status_code=503, detail="Ditto source or checkpoint mount is incomplete; see workers/avatar/README.md")
        command = [
            sys.executable,
            str(inference),
            "--data_root", str(self.config.model_root),
            "--cfg_pkl", str(self.config.config_path),
            "--audio_path", str(audio),
            "--source_path", str(source),
            "--output_path", str(output),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(self.config.ditto_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        key = body.session_id or body.turn_id
        self.processes[key] = process
        _, stderr = await process.communicate()
        self.processes.pop(key, None)
        if process.returncode != 0 or not output.is_file():
            detail = stderr.decode("utf-8", errors="replace")[-1_000:]
            raise HTTPException(status_code=502, detail=f"Ditto inference failed: {detail or 'no output'}")

    async def cancel(self, session_id: str) -> None:
        process = self.processes.get(session_id)
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.5)
            except TimeoutError:
                process.kill()


class MjpegFrameSink:
    """Thread-safe bridge from Ditto's online writer to an HTTP MJPEG stream."""

    def __init__(self, loop: asyncio.AbstractEventLoop, frames: asyncio.Queue[bytes], expected_frames: int | None = None, packet_sink=None, playback_started: asyncio.Event | None = None, skip_initial_frames: int = 0, pace_output: bool = True):
        self.loop = loop
        self.frames = frames
        # Ditto's online pipeline needs causal context and may flush additional
        # motion after the supplied waveform.  Media playback, however, must
        # have exactly the same duration as the WAV served to the browser.
        self.expected_frames = expected_frames
        self.skip_initial_frames = skip_initial_frames
        self.pace_output = pace_output
        self.packet_sink = packet_sink
        self.playback_started = playback_started
        self.started_at = time.monotonic()
        self.first_frame_at: float | None = None
        self.frame_count = 0
        self.source_frame_count = 0
        self.dropped_preroll_frames = 0
        self.dropped_tail_frames = 0
        self.next_emit_at = self.started_at

    def __call__(self, frame_rgb: np.ndarray, fmt: str = "rgb") -> None:
        self.source_frame_count += 1
        if self.source_frame_count <= self.skip_initial_frames:
            self.dropped_preroll_frames += 1
            return
        if self.expected_frames is not None and self.frame_count >= self.expected_frames:
            self.dropped_tail_frames += 1
            return
        # Live Ditto emits any generated burst immediately; the browser owns
        # the 25-fps playout clock and absorbs GPU jitter in its buffer.
        if self.pace_output:
            now = time.monotonic()
            if self.next_emit_at > now:
                time.sleep(self.next_emit_at - now)
            self.next_emit_at = max(self.next_emit_at, time.monotonic()) + 1 / 25
        if self.first_frame_at is None:
            self.first_frame_at = time.monotonic()
            if self.playback_started is not None:
                self.loop.call_soon_threadsafe(self.playback_started.set)
        self.frame_count += 1
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR) if fmt == "rgb" else frame_rgb
        ok, encoded = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 86])
        if ok:
            frame = encoded.tobytes()
            pts_ms = (self.frame_count - 1) * 40
            self.loop.call_soon_threadsafe(self._replace_latest, frame)
            if self.packet_sink is not None:
                self.loop.call_soon_threadsafe(self.packet_sink, "video", pts_ms, frame)

    def _replace_latest(self, frame: bytes) -> None:
        # Live media must prefer the newest frame rather than accumulating lag.
        with contextlib.suppress(asyncio.QueueEmpty):
            self.frames.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self.frames.put_nowait(frame)

    def close(self) -> None:
        # Completion is observed from the render task. Do not put an end
        # sentinel into the latest-frame queue: a late browser subscriber
        # would otherwise receive only that sentinel and render a blank stage.
        return None


class DiscardFrameSink:
    """Warm Ditto's GPU path without retaining or encoding synthetic frames."""

    def __call__(self, frame_rgb: np.ndarray, fmt: str = "rgb") -> None:
        return None

    def close(self) -> None:
        return None


class Mp4FrameSink:
    """Write complete Ditto frames to a short, browser-playable idle video."""

    def __init__(self, output: Path, expected_frames: int, skip_initial_frames: int = 0) -> None:
        self.output = output
        self.expected_frames = expected_frames
        self.skip_initial_frames = skip_initial_frames
        self.source_frame_count = 0
        self.frame_count = 0
        self.encoder: subprocess.Popen[bytes] | None = None

    def __call__(self, frame_rgb: np.ndarray, fmt: str = "rgb") -> None:
        self.source_frame_count += 1
        if self.source_frame_count <= self.skip_initial_frames or self.frame_count >= self.expected_frames:
            return
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR) if fmt == "rgb" else frame_rgb
        if self.encoder is None:
            height, width = frame_bgr.shape[:2]
            self.encoder = subprocess.Popen(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "rawvideo", "-pixel_format", "bgr24",
                    "-video_size", f"{width}x{height}", "-framerate", "25",
                    "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(self.output),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        assert self.encoder.stdin is not None
        self.encoder.stdin.write(frame_bgr.tobytes())
        self.frame_count += 1

    def close(self) -> None:
        if self.encoder is None:
            return
        assert self.encoder.stdin is not None
        self.encoder.stdin.close()
        detail = b""
        if self.encoder.stderr is not None:
            detail = self.encoder.stderr.read()
        returncode = self.encoder.wait()
        if returncode != 0 or not self.output.is_file() or self.output.stat().st_size < 1024:
            message = detail.decode("utf-8", errors="replace")[-400:]
            raise RuntimeError(
                "Could not encode idle-video MP4 "
                f"(source_frames={self.source_frame_count}, written_frames={self.frame_count}, "
                f"ffmpeg={message or 'no output'})"
            )


@dataclass
class LiveTurn:
    frames: asyncio.Queue[bytes]
    audio: Path
    task: asyncio.Task[None]
    packets: asyncio.Queue[tuple[str, int, bytes]] | None = None
    websocket_connected: asyncio.Event | None = None
    playback_started: asyncio.Event | None = None
    video_pts: asyncio.Queue[int] | None = None


class DittoLiveRuntime:
    """Persistent online Ditto runtime.

    Models are loaded once per worker and each approved avatar is registered
    once at preparation time. A turn produces JPEG frames directly; it never
    waits for FFmpeg to encode a complete MP4.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.sdk = None
        self.avatar_sources: dict[str, object] = {}
        self.warmed_avatars: set[str] = set()
        self.turns: dict[str, LiveTurn] = {}
        self.lock = asyncio.Lock()

    def _load_sdk(self):
        if self.sdk is None:
            sys.path.insert(0, str(self.config.ditto_root))
            from stream_pipeline_online import StreamSDK
            self.sdk = StreamSDK(str(self.config.config_path), str(self.config.model_root))
        return self.sdk

    def _register_avatar(self, avatar_id: str, source: Path) -> None:
        if avatar_id in self.avatar_sources:
            return
        sdk = self._load_sdk()
        # This is exactly the source-registration portion of StreamSDK.setup.
        source_info = sdk.avatar_registrar(
            str(source), max_dim=1920, n_frames=-1,
            crop_scale=2.3, crop_vx_ratio=0, crop_vy_ratio=-0.125,
            crop_flag_do_rot=True,
        )
        if len(source_info["x_s_info_lst"]) > 1:
            from core.atomic_components.avatar_registrar import smooth_x_s_info_lst
            source_info["x_s_info_lst"] = smooth_x_s_info_lst(source_info["x_s_info_lst"], smo_k=13)
        self.avatar_sources[avatar_id] = source_info

    def _warm_avatar(self, avatar_id: str, loop: asyncio.AbstractEventLoop) -> None:
        """Move lazy CUDA/ONNX/PyTorch work out of the first spoken turn.

        Ditto creates its per-turn workers lazily.  Without this small silent
        pass, the first conversational turn pays for allocator setup, kernel
        selection and the first Audio2Motion execution before it can emit a
        frame. Avatar preparation already runs before the avatar is marked
        ready, so this is the right place to pay that one-time cost.

        ``DITTO_WARM_MEDIA_PATH=true`` enables an extended experiment that
        also primes color conversion, JPEG encoding, and the event-loop packet
        callback. It remains opt-in because the first experiment did not lower
        Ditto's intrinsic first-frame inference time enough to justify adding
        this work to every session preparation by default.
        """
        if avatar_id in self.warmed_avatars:
            return
        sdk = self._load_sdk()
        chunksize = DITTO_CHUNKSIZE
        window_samples = int(sum(chunksize) * 0.04 * 16000) + 80
        started = time.monotonic()
        warm_plan = MotionPlan()
        if self.config.warm_media_path:
            frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
            # One emitted frame is enough to warm the visible delivery path.
            # The bounded queue and no-op packet consumer retain no media and
            # never expose this silent dry-run to a browser.
            sink: MjpegFrameSink | DiscardFrameSink = MjpegFrameSink(
                loop,
                frames,
                expected_frames=1,
                packet_sink=lambda _kind, _pts, _payload: None,
                skip_initial_frames=DITTO_PREROLL_FRAMES,
                pace_output=False,
            )
            warm_frames = DITTO_PREROLL_FRAMES + 12
            ctrl_info = build_ditto_ctrl_info(warm_plan, warm_frames, frame_offset=DITTO_PREROLL_FRAMES)
            warm_windows = 6
        else:
            sink = DiscardFrameSink()
            warm_frames = 10
            ctrl_info = {}
            warm_windows = 2
        sdk.setup(
            "", "", frame_sink=sink, source_info=self.avatar_sources[avatar_id], online_mode=True,
            sampling_timesteps=self.config.sampling_timesteps,
            emo=DITTO_EMOTION_INDEX[warm_plan.expression], ctrl_info=ctrl_info,
        )
        try:
            sdk.setup_Nd(warm_frames, ctrl_info=ctrl_info)
            silence = np.zeros((window_samples,), dtype=np.float32)
            for _ in range(warm_windows):
                sdk.run_chunk(silence, chunksize)
                if self.config.warm_media_path and isinstance(sink, MjpegFrameSink) and sink.frame_count:
                    break
        finally:
            sdk.close()
            sink.close()
        self.warmed_avatars.add(avatar_id)
        print(
            "Ditto avatar warm-up: " + json.dumps({
                "avatar_id": avatar_id,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                "media_path_enabled": self.config.warm_media_path,
                "source_frames": sink.source_frame_count if isinstance(sink, MjpegFrameSink) else 0,
                "jpeg_frames": sink.frame_count if isinstance(sink, MjpegFrameSink) else 0,
                "packet_callback_warmed": isinstance(sink, MjpegFrameSink) and sink.frame_count > 0,
            }, ensure_ascii=False, sort_keys=True),
            flush=True,
        )

    async def prepare(self, avatar_id: str, source: Path) -> None:
        async with self.lock:
            await asyncio.to_thread(self._register_avatar, avatar_id, source)
            await asyncio.to_thread(self._warm_avatar, avatar_id, asyncio.get_running_loop())
            if self.config.warm_media_path:
                # Deliver the callback scheduled by MjpegFrameSink before a
                # turn may reuse this prepared avatar.
                await asyncio.sleep(0)

    def idle_path(self, avatar_id: str, variant: int) -> Path:
        safe_avatar = hashlib.sha256(avatar_id.encode("utf-8")).hexdigest()[:24]
        return self.config.data_root / "idle" / f"{safe_avatar}-v{variant}.mp4"

    async def prepare_idle(self, avatar_id: str, source: Path, variants: int = 3) -> list[Path]:
        """Generate immutable, full-frame idle variants once per avatar."""
        await self.prepare(avatar_id, source)
        async with self.lock:
            outputs: list[Path] = []
            for variant in range(variants):
                output = self.idle_path(avatar_id, variant)
                if output.is_file() and output.stat().st_size > 1_024:
                    outputs.append(output)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(self._generate_idle_blocking, avatar_id, variant, output)
                outputs.append(output)
            return outputs

    def _generate_idle_blocking(self, avatar_id: str, variant: int, output: Path) -> None:
        started = time.monotonic()
        sdk = self._load_sdk()
        frame_count = 200  # eight seconds at the shared 25-fps media clock
        sink = Mp4FrameSink(output, expected_frames=frame_count, skip_initial_frames=DITTO_PREROLL_FRAMES)
        ctrl_info = build_idle_ctrl_info(variant, frame_count + DITTO_PREROLL_FRAMES)
        # An exact all-zero waveform is discarded by Ditto's streaming HuBERT
        # frontend and never reaches the motion pipeline. A very-low-energy,
        # deterministic breath signal keeps the model clock running without
        # producing visible speech articulation.
        sample_count = frame_count * 640
        sample_clock = np.arange(sample_count, dtype=np.float32) / 16_000.0
        rng = np.random.default_rng(10_000 + variant)
        breath = (
            0.0009 * np.sin(2 * np.pi * (0.14 + variant * 0.015) * sample_clock)
            + 0.00025 * rng.standard_normal(sample_count, dtype=np.float32)
        )
        silence = breath.astype(np.float32, copy=False)
        try:
            sdk.setup(
                "", "", frame_sink=sink, source_info=self.avatar_sources[avatar_id], online_mode=True,
                sampling_timesteps=self.config.sampling_timesteps,
                emo=DITTO_EMOTION_INDEX["neutral"], ctrl_info=ctrl_info,
            )
            sdk.setup_Nd(frame_count, ctrl_info=ctrl_info)
            chunksize = DITTO_CHUNKSIZE
            window_samples = int(sum(chunksize) * 0.04 * 16000) + 80
            stride_samples = chunksize[1] * 640
            padded = np.concatenate([np.zeros((chunksize[0] * 640,), dtype=np.float32), silence])
            for start in range(0, len(padded), stride_samples):
                chunk = padded[start:start + window_samples]
                if len(chunk) < window_samples:
                    chunk = np.pad(chunk, (0, window_samples - len(chunk)))
                sdk.run_chunk(chunk, chunksize)
        finally:
            sdk.close()
            sink.close()
        if sink.frame_count < frame_count:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"Idle Ditto render was incomplete ({sink.frame_count}/{frame_count} frames)")
        print(
            "Ditto idle loop generated: "
            + json.dumps(
                {
                    "avatar_id": avatar_id,
                    "variant": variant,
                    "frames": sink.frame_count,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    async def synthesize(self, text: str, output: Path) -> Path:
        process = await asyncio.create_subprocess_exec(
            "espeak-ng", "-v", "ko", "-s", "165", "-w", str(output), text,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output.is_file():
            raise HTTPException(status_code=502, detail=f"Local TTS failed: {stderr.decode(errors='replace')[-300:]}")
        return output

    async def start(self, body: RenderIn, source: Path, audio_dir: Path) -> tuple[str, str]:
        await self.prepare(body.avatar_id, source)
        audio = audio_dir / f"{body.turn_id}-{uuid.uuid4().hex[:8]}.wav"
        await self.synthesize(body.text, audio)
        frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        packets: asyncio.Queue[tuple[str, int, bytes]] = asyncio.Queue(maxsize=1024)
        video_pts: asyncio.Queue[int] = asyncio.Queue(maxsize=1024)
        websocket_connected = asyncio.Event()
        playback_started = asyncio.Event()
        # Construct the turn before its task runs so the WebSocket route can
        # attach immediately after the render REST response.
        placeholder = asyncio.create_task(asyncio.sleep(0), name=f"ditto-live-placeholder-{body.turn_id}")
        turn = LiveTurn(
            frames=frames, audio=audio, task=placeholder, packets=packets,
            websocket_connected=websocket_connected, playback_started=playback_started, video_pts=video_pts,
        )
        task = asyncio.create_task(self._run(body, audio, turn), name=f"ditto-live-{body.turn_id}")
        turn.task = task
        self.turns[body.turn_id] = turn
        task.add_done_callback(self._report_task_error)
        # `/avatar-stream/` is a websocket-only nginx route directly to this
        # private worker. Audio PCM and JPEG frames share PTS=0 in one socket.
        return f"/avatar-stream/v1/live/{body.turn_id}", f"/v1/assets/audio/{audio.name}"

    @staticmethod
    def _report_task_error(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            print("Ditto live turn failed:", repr(error), flush=True)
            traceback.print_exception(error)

    async def _run(self, body: RenderIn, audio: Path, turn: LiveTurn) -> None:
        # The browser opens the socket immediately after REST returns. Waiting
        # briefly prevents the first video/audio packets from being produced
        # before it has a consumer; legacy MJPEG requests still work after the
        # timeout, but do not activate PCM streaming.
        assert turn.websocket_connected is not None and turn.playback_started is not None and turn.packets is not None and turn.video_pts is not None
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(turn.websocket_connected.wait(), timeout=2.0)

        def packet_sink(kind: str, pts_ms: int, payload: bytes) -> None:
            if not turn.websocket_connected.is_set():
                return
            with contextlib.suppress(asyncio.QueueFull):
                turn.packets.put_nowait((kind, pts_ms, payload))
            if kind == "video":
                # Audio is allowed to advance only after its matching visual
                # timestamp has actually left Ditto's renderer. This converts
                # transient GPU frame stalls into backpressure, never A/V drift.
                with contextlib.suppress(asyncio.QueueFull):
                    turn.video_pts.put_nowait(pts_ms)

        audio_task = asyncio.create_task(self._pump_pcm(audio, turn), name=f"ditto-audio-{body.turn_id}") if turn.websocket_connected.is_set() else None
        async with self.lock:
            loop = asyncio.get_running_loop()
            # The browser receives the original WAV. Use its wall-clock
            # duration, rather than the internal 16 kHz resampled array, as
            # the authoritative 25-fps video duration.
            with wave.open(str(audio), "rb") as wav:
                expected_frames = max(1, int(np.ceil(wav.getnframes() / wav.getframerate() * 25)))
            sink = MjpegFrameSink(
                loop, turn.frames, expected_frames=expected_frames,
                packet_sink=packet_sink, playback_started=turn.playback_started,
                skip_initial_frames=DITTO_PREROLL_FRAMES, pace_output=False,
            )
            try:
                await asyncio.to_thread(self._run_blocking, body, audio, sink)
            finally:
                sink.close()
                first = None if sink.first_frame_at is None else round(sink.first_frame_at - sink.started_at, 3)
                print(
                    f"Ditto live turn metrics: first_frame_s={first} frames={sink.frame_count} "
                    f"expected_frames={expected_frames} dropped_preroll_frames={sink.dropped_preroll_frames} "
                    f"dropped_tail_frames={sink.dropped_tail_frames}",
                    flush=True,
                )
        if audio_task is not None:
            await audio_task
        if turn.websocket_connected.is_set():
            await turn.packets.put(("end", 0, b""))

    async def _pump_pcm(self, audio: Path, turn: LiveTurn) -> None:
        """Send fixed 40 ms PCM packets using the same PTS as Ditto frames."""
        assert turn.packets is not None and turn.playback_started is not None and turn.video_pts is not None
        with wave.open(str(audio), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            channels, width, sample_rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if channels == 1 and width == 2 and sample_rate == 16000:
            samples = np.frombuffer(raw, dtype=np.int16)
        else:
            import librosa
            normalized, _ = librosa.load(str(audio), sr=16000, mono=True)
            samples = np.clip(normalized * 32767.0, -32768, 32767).astype(np.int16)
        await turn.playback_started.wait()
        chunk_samples = 640  # 40 ms at 16 kHz = one 25 fps video tick
        for start in range(0, len(samples), chunk_samples):
            pts_ms = start * 1000 // 16000
            while True:
                video_pts = await turn.video_pts.get()
                if video_pts >= pts_ms:
                    break
            await turn.packets.put(("audio", pts_ms, samples[start:start + chunk_samples].tobytes()))

    def _run_blocking(self, body: RenderIn, audio: Path, sink: MjpegFrameSink) -> None:
        sdk = self._load_sdk()
        with wave.open(str(audio), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            channels, width, sample_rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if channels == 1 and width == 2 and sample_rate == 16000:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            # eSpeak defaults to 22.05 kHz. Ditto's HuBERT streaming frontend
            # is fixed at 16 kHz, so normalize the short local TTS clip here.
            import librosa
            samples, _ = librosa.load(str(audio), sr=16000, mono=True)
        # Online mode consumes 0.405 s (6,480 samples) chunks. setup_Nd lets
        # the eye/motion controls know the intended length before frames flow.
        frame_count = max(1, int(np.ceil(len(samples) / 640)))
        motion_plan = body.motion_plan or MotionPlan()
        # Keep the controls on the same source-frame clock as Ditto, then
        # shift user-visible timed gestures past the causal preroll too.
        ctrl_info = build_ditto_ctrl_info(
            motion_plan, frame_count, frame_offset=DITTO_PREROLL_FRAMES,
        )
        sdk.setup(
            "", "", frame_sink=sink, source_info=self.avatar_sources[body.avatar_id], online_mode=True,
            sampling_timesteps=self.config.sampling_timesteps,
            emo=DITTO_EMOTION_INDEX[motion_plan.expression],
            ctrl_info=ctrl_info,
        )
        # `setup_Nd` is the requested speech length. StreamSDK itself emits
        # the causal overlap in addition to this length; the frame sink trims
        # that overlap, so extending N_d here would make the turn overrun.
        sdk.setup_Nd(frame_count, ctrl_info=ctrl_info)
        # Match upstream inference.py exactly: the HuBERT streaming model
        # consumes a 6,480-sample context window but advances by 3,200 samples
        # (five 25-fps video frames). Advancing by a full window silently
        # drops half the audio and makes the face stop far before its TTS.
        chunksize = DITTO_CHUNKSIZE
        window_samples = int(sum(chunksize) * 0.04 * 16000) + 80  # 6480
        stride_samples = chunksize[1] * 640  # 3200 / 0.2 seconds
        # Do not append a full valid-clip of silence here. It makes the online
        # renderer generate 2.8 seconds of tail motion beyond the WAV, then
        # causes video to slow down/catch up relative to the browser audio.
        # The final padded window below is enough to flush the supplied speech.
        padded = np.concatenate([
            np.zeros((chunksize[0] * 640,), dtype=np.float32),
            samples,
        ])
        for start in range(0, len(padded), stride_samples):
            chunk = padded[start:start + window_samples]
            if len(chunk) < window_samples:
                chunk = np.pad(chunk, (0, window_samples - len(chunk)))
            sdk.run_chunk(chunk, chunksize)
        sdk.close()

    async def cancel(self, session_id: str) -> None:
        for turn_id, turn in list(self.turns.items()):
            if turn_id.startswith(session_id) or not turn.task.done():
                turn.task.cancel()

    def stream(self, turn_id: str):
        turn = self.turns.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)

        async def body():
            while True:
                try:
                    frame = await asyncio.wait_for(turn.frames.get(), timeout=0.25)
                except TimeoutError:
                    if turn.task.done():
                        break
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
        return body()


class RealtimePcmTimeline:
    """Audio-owned PTS timeline shared by the realtime TTS and Ditto paths.

    The renderer may generate JPEGs in bursts.  This object releases 40-ms
    PCM packets only after their matching video PTS has been accepted, so a
    fast GPU burst can never leave the mouth running after the audio ends.
    """

    def __init__(self) -> None:
        self._samples = np.zeros((0,), dtype=np.int16)
        self._complete = False
        self._cancelled = False
        self._next_packet_sample = 0
        self._lock = threading.Lock()

    def append(self, samples: np.ndarray) -> None:
        if not len(samples):
            return
        with self._lock:
            self._samples = np.concatenate([self._samples, samples.astype(np.int16, copy=False)])

    def finish(self) -> None:
        with self._lock:
            self._complete = True

    def frame_count(self) -> int:
        """Number of 25-fps video frames required by the registered PCM."""
        with self._lock:
            return max(1, int(np.ceil(len(self._samples) / 640)))

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._complete = True

    def accepts_video(self, pts_ms: int) -> bool:
        with self._lock:
            if self._cancelled:
                return False
            if not self._complete:
                return True
            return pts_ms < max(40, int(np.ceil(len(self._samples) / 640)) * 40)

    def audio_packets_through(self, pts_ms: int) -> list[tuple[int, bytes]]:
        """Return PCM blocks that have a matching generated video frame."""
        packets: list[tuple[int, bytes]] = []
        with self._lock:
            max_sample = min(len(self._samples), ((pts_ms // 40) + 1) * 640)
            while self._next_packet_sample < max_sample:
                start = self._next_packet_sample
                end = min(start + 640, len(self._samples))
                packets.append((start * 1000 // 16_000, self._samples[start:end].tobytes()))
                self._next_packet_sample = end
        return packets


@dataclass
class RealtimeTurnMetrics:
    """Monotonic, worker-side timings for one Ditto Realtime turn."""

    started_at: float = field(default_factory=time.monotonic)
    marks: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def mark(self, name: str, at: float | None = None) -> None:
        with self.lock:
            self.marks.setdefault(name, at if at is not None else time.monotonic())

    def as_milliseconds(self, **extra: int | float | None) -> dict[str, int | float | None]:
        with self.lock:
            values: dict[str, int | float | None] = {
                name: round((timestamp - self.started_at) * 1000, 1)
                for name, timestamp in self.marks.items()
            }
        return {**values, **extra}


class ObservedCallable:
    """Add a best-effort wall-clock probe around a vendor pipeline callable."""

    def __init__(self, target, stage: str, observer):
        self._target = target
        self._stage = stage
        self._observer = observer

    def __call__(self, *args, **kwargs):
        started_at = time.monotonic()
        result = self._target(*args, **kwargs)
        self._observer(self._stage, started_at, time.monotonic())
        return result

    def __getattr__(self, name: str):
        return getattr(self._target, name)


class DittoRealtimeRuntime(DittoLiveRuntime):
    """Ditto online mode fed by incremental TTS PCM instead of a complete WAV.

    This is intentionally a separate worker mode from ``ditto_live``.  The
    stable renderer remains the rollback/reference path; this runtime tests
    the production-shaped sequence: first sentence TTS → Ditto PCM chunks →
    timestamped JPEG/PCM packets.  eSpeak is retained only as an offline-free
    TTS adapter for the prototype and can be replaced with a streaming neural
    TTS service without changing the media clock.
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self._session_turns: dict[str, str] = {}
        self._timelines: dict[str, RealtimePcmTimeline] = {}
        self._profile_lock = threading.Lock()
        self._profile_first_turn_pending = config.profile_first_turn

    def _take_profile_slot(self) -> bool:
        """Enable detailed stage timing for exactly one explicitly opted-in turn."""
        with self._profile_lock:
            if not self._profile_first_turn_pending:
                return False
            self._profile_first_turn_pending = False
            return True

    def _sampling_timesteps_for(self, render_profile: str) -> int:
        return self.config.fast_sampling_timesteps if render_profile == "fast" else self.config.sampling_timesteps

    @staticmethod
    def _preroll_frames_for(render_profile: str) -> int:
        # These variants only alter which initial causal-context frames are
        # presented; they do not claim to reduce upstream model computation.
        # They are benchmark-only until first-phoneme quality and sync pass.
        return {"fast_preroll9": 9, "fast_preroll5": 5}.get(render_profile, DITTO_PREROLL_FRAMES)

    def _write_pipeline_profile(
        self,
        turn_id: str,
        started_at: float,
        events: list[tuple[str, float, float]],
        first_frame_at: float | None,
    ) -> None:
        """Persist a compact, semantic timing trace without retaining media."""
        by_stage: dict[str, list[tuple[float, float]]] = {}
        for stage, began, ended in events:
            by_stage.setdefault(stage, []).append((began, ended))
        stages = {
            stage: {
                "calls": len(values),
                "first_started_ms": round((values[0][0] - started_at) * 1000, 1),
                "first_finished_ms": round((values[0][1] - started_at) * 1000, 1),
                "first_duration_ms": round((values[0][1] - values[0][0]) * 1000, 1),
                "total_duration_ms": round(sum(ended - began for began, ended in values) * 1000, 1),
            }
            for stage, values in by_stage.items()
        }
        payload = {
            "turn_id": turn_id,
            "sampling_timesteps": self.config.sampling_timesteps,
            "first_frame_ms": None if first_frame_at is None else round((first_frame_at - started_at) * 1000, 1),
            "stages": stages,
            "note": "Thread wall-times overlap by design; use first_finished_ms to locate the first-frame critical path.",
        }
        output_dir = self.config.data_root / "benchmarks" / "profiles"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{turn_id}-pipeline.json"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Ditto realtime pipeline profile: " + json.dumps({**payload, "path": str(output)}, ensure_ascii=False, sort_keys=True), flush=True)

    @staticmethod
    def _speech_segments(text: str) -> list[str]:
        # Give the first renderer call enough phonetic context (~0.3 s) while
        # not waiting for a long answer. Korean punctuation is included.
        parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\\s+", text.strip()) if part.strip()]
        if not parts:
            return []
        segments: list[str] = []
        for part in parts:
            while len(part) > 42:
                cut = max(part.rfind(" ", 18, 42), 18)
                segments.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                segments.append(part)
        return segments

    async def _synthesize_pcm(self, text: str, output: Path) -> np.ndarray:
        await self.synthesize(text, output)
        with wave.open(str(output), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            channels, width, sample_rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if channels == 1 and width == 2 and sample_rate == 16_000:
            return np.frombuffer(raw, dtype=np.int16).copy()
        import librosa
        normalized, _ = librosa.load(str(output), sr=16_000, mono=True)
        return np.clip(normalized * 32767.0, -32768, 32767).astype(np.int16)

    async def start(self, body: RenderIn, source: Path, audio_dir: Path) -> tuple[str, str | None]:
        # Session creation has already warmed this registration. Keep the
        # defensive prepare call for direct worker clients/restarts.
        await self.prepare(body.avatar_id, source)
        frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        packets: asyncio.Queue[tuple[str, int, bytes]] = asyncio.Queue(maxsize=1024)
        websocket_connected = asyncio.Event()
        playback_started = asyncio.Event()
        turn = LiveTurn(
            frames=frames,
            audio=audio_dir / f"{body.turn_id}.realtime.wav",
            task=asyncio.create_task(asyncio.sleep(0), name=f"ditto-realtime-placeholder-{body.turn_id}"),
            packets=packets,
            websocket_connected=websocket_connected,
            playback_started=playback_started,
            video_pts=asyncio.Queue(maxsize=1024),
        )
        timeline = RealtimePcmTimeline()
        metrics = RealtimeTurnMetrics()
        task = asyncio.create_task(self._run_realtime(body, turn, timeline, metrics, audio_dir), name=f"ditto-realtime-{body.turn_id}")
        turn.task = task
        self.turns[body.turn_id] = turn
        self._timelines[body.turn_id] = timeline
        if body.session_id:
            self._session_turns[body.session_id] = body.turn_id
        task.add_done_callback(self._report_task_error)
        return f"/avatar-stream/v1/live/{body.turn_id}", None

    async def _run_realtime(
        self,
        body: RenderIn,
        turn: LiveTurn,
        timeline: RealtimePcmTimeline,
        metrics: RealtimeTurnMetrics,
        audio_dir: Path,
    ) -> None:
        assert turn.websocket_connected is not None and turn.packets is not None
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(turn.websocket_connected.wait(), timeout=2.0)
        if not turn.websocket_connected.is_set():
            return
        metrics.mark("socket_connected")

        pcm_input: queue.Queue[np.ndarray | None] = queue.Queue()
        render_task: asyncio.Task[None] | None = None
        try:
            # An external voice file (Marin/Reatime bridge) is authoritative:
            # Ditto and browser packets must consume exactly the same samples.
            if body.audio_path and body.audio_streaming:
                external = safe_data_path(self.config.data_root, body.audio_path)
                done = external.with_suffix(".done")
                metrics.mark("external_audio_stream_ready")
                render_task = asyncio.create_task(
                    asyncio.to_thread(self._run_realtime_sdk, asyncio.get_running_loop(), body, turn, timeline, metrics, pcm_input),
                    name=f"ditto-realtime-sdk-{body.turn_id}",
                )
                offset = 0
                while True:
                    if external.is_file():
                        length = external.stat().st_size
                        readable = length - (length - offset) % 2
                        if readable > offset:
                            with external.open("rb") as stream:
                                stream.seek(offset)
                                chunk = stream.read(readable - offset)
                            pcm = np.frombuffer(chunk, dtype=np.int16).copy()
                            timeline.append(pcm)
                            pcm_input.put(pcm)
                            offset = readable
                            metrics.mark("external_audio_first_pcm")
                    if done.is_file():
                        timeline.finish()
                        pcm_input.put(None)
                        break
                    await asyncio.sleep(0.012)
                await render_task
                with contextlib.suppress(FileNotFoundError):
                    external.unlink()
                with contextlib.suppress(FileNotFoundError):
                    done.unlink()
            elif body.audio_path:
                external = safe_data_path(self.config.data_root, body.audio_path)
                if not external.is_file():
                    raise RuntimeError("Realtime Ditto external audio is missing")
                metrics.mark("external_audio_ready")
                with wave.open(str(external), "rb") as wav:
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16_000:
                        raise RuntimeError("Realtime Ditto external audio must be 16 kHz mono PCM WAV")
                    pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).copy()
                metrics.mark("external_audio_loaded")
            else:
                segments = self._speech_segments(body.text)
                if not segments:
                    raise RuntimeError("Realtime Ditto received no TTS text")

                # Ditto's motion planner needs the exact media duration.  The
            # former per-sentence feed used a character-count estimate, so a
            # long voice could outlast the generated motion.  Run the tiny
            # local TTS fragments concurrently, concatenate in text order,
            # then make PCM duration the sole source of truth for both tracks.
                metrics.mark("tts_started")
                synthesis_tasks = [
                asyncio.create_task(self._synthesize_pcm(segment, audio_dir / f"{body.turn_id}-{index}.wav"))
                for index, segment in enumerate(segments)
            ]
                await asyncio.wait(synthesis_tasks, return_when=asyncio.FIRST_COMPLETED)
                metrics.mark("tts_first_pcm_ready")
                pcm_parts = await asyncio.gather(*synthesis_tasks)
                metrics.mark("tts_all_pcm_ready")
                pcm = np.concatenate(pcm_parts) if len(pcm_parts) > 1 else pcm_parts[0]
            if not body.audio_streaming:
                timeline.append(pcm)
                timeline.finish()
                render_task = asyncio.create_task(
                    asyncio.to_thread(self._run_realtime_sdk, asyncio.get_running_loop(), body, turn, timeline, metrics, pcm_input),
                    name=f"ditto-realtime-sdk-{body.turn_id}",
                )
                pcm_input.put(pcm)
                pcm_input.put(None)
                await render_task
            # Allow thread-safe frame callbacks to enter the asyncio queue
            # before publishing end-of-turn to the browser.
            await asyncio.sleep(0)
        except Exception:
            pcm_input.put(None)
            if render_task is not None:
                render_task.cancel()
            raise
        finally:
            timeline.finish()
        if turn.websocket_connected.is_set():
            await turn.packets.put(("end", 0, b""))

    async def cancel(self, session_id: str) -> None:
        turn_id = self._session_turns.pop(session_id, None)
        if turn_id is None:
            return
        timeline = self._timelines.get(turn_id)
        if timeline:
            timeline.cancel()
        turn = self.turns.get(turn_id)
        if turn and not turn.task.done():
            turn.task.cancel()

    def _run_realtime_sdk(
        self,
        loop: asyncio.AbstractEventLoop,
        body: RenderIn,
        turn: LiveTurn,
        timeline: RealtimePcmTimeline,
        metrics: RealtimeTurnMetrics,
        pcm_input: queue.Queue[np.ndarray | None],
    ) -> None:
        assert turn.packets is not None and turn.playback_started is not None
        metrics.mark("renderer_thread_started")
        sdk = self._load_sdk()
        base_profile = "fast" if body.render_profile.startswith("fast") else "quality"
        sampling_timesteps = self._sampling_timesteps_for(base_profile)
        preroll_frames = self._preroll_frames_for(body.render_profile)
        profile_enabled = self._take_profile_slot()
        profile_started_at = time.monotonic()
        profile_events: list[tuple[str, float, float]] = []
        profile_events_lock = threading.Lock()

        def observe_stage(stage: str, began: float, ended: float) -> None:
            if profile_enabled:
                with profile_events_lock:
                    profile_events.append((stage, began, ended))

        def publish(kind: str, pts_ms: int, payload: bytes) -> None:
            if kind != "video" or not timeline.accepts_video(pts_ms):
                return
            with contextlib.suppress(asyncio.QueueFull):
                turn.packets.put_nowait(("video", pts_ms, payload))
            for audio_pts, audio_payload in timeline.audio_packets_through(pts_ms):
                with contextlib.suppress(asyncio.QueueFull):
                    turn.packets.put_nowait(("audio", audio_pts, audio_payload))

        # PCM duration is the clock contract.  This gives MotionStitch the
        # same endpoint as audio and clips its causal tail to that endpoint.
        # An audio stream has no final duration during setup.  Controls are
        # therefore provisioned for a bounded response; the PCM-owned timeline
        # still clips packets exactly when the producer marks completion.
        target_frames = 750 if body.audio_streaming else timeline.frame_count()
        motion_plan = body.motion_plan or MotionPlan()
        ctrl_info = build_ditto_ctrl_info(motion_plan, target_frames, frame_offset=preroll_frames)
        sink = MjpegFrameSink(
            loop,
            turn.frames,
            expected_frames=target_frames,
            packet_sink=publish,
            playback_started=turn.playback_started,
            skip_initial_frames=preroll_frames,
            pace_output=False,
        )
        setup_started_at = time.monotonic()
        sdk.setup(
            "", "", frame_sink=sink, source_info=self.avatar_sources[body.avatar_id], online_mode=True,
            sampling_timesteps=sampling_timesteps,
            emo=DITTO_EMOTION_INDEX[motion_plan.expression], ctrl_info=ctrl_info,
        )
        if profile_enabled:
            profile_events.append(("turn_setup", setup_started_at, time.monotonic()))
        setup_nd_started_at = time.monotonic()
        sdk.setup_Nd(target_frames, ctrl_info=ctrl_info)
        if profile_enabled:
            profile_events.append(("setup_Nd", setup_nd_started_at, time.monotonic()))
            # The upstream SDK owns its six worker-loop functions, so wrap its
            # public components after setup rather than maintaining a fork of
            # the ignored, read-only vendor checkout. Attribute forwarding
            # preserves config and helper access used by those worker loops.
            sdk.wav2feat = ObservedCallable(sdk.wav2feat, "hubert_wav2feat", observe_stage)
            sdk.audio2motion = ObservedCallable(sdk.audio2motion, "audio2motion_diffusion", observe_stage)
            sdk.motion_stitch = ObservedCallable(sdk.motion_stitch, "motion_stitch", observe_stage)
            sdk.warp_f3d = ObservedCallable(sdk.warp_f3d, "warp_f3d", observe_stage)
            sdk.decode_f3d = ObservedCallable(sdk.decode_f3d, "decode_f3d", observe_stage)
            sdk.putback = ObservedCallable(sdk.putback, "putback", observe_stage)
            sdk.writer = ObservedCallable(sdk.writer, "jpeg_and_packet", observe_stage)
        metrics.mark("ditto_setup_done")
        # Ditto consumes a 6,480-sample causal window and advances 3,200
        # samples. Keep exactly that rolling overlap across TTS fragments.
        window_samples = int(sum(DITTO_CHUNKSIZE) * .04 * 16_000) + 80
        stride_samples = DITTO_CHUNKSIZE[1] * 640
        rolling = np.zeros((DITTO_CHUNKSIZE[0] * 640,), dtype=np.float32)
        try:
            done = False
            while not done:
                item = pcm_input.get()
                if item is None:
                    done = True
                else:
                    rolling = np.concatenate([rolling, item.astype(np.float32) / 32768.0])
                while len(rolling) >= window_samples:
                    sdk.run_chunk(rolling[:window_samples], DITTO_CHUNKSIZE)
                    rolling = rolling[stride_samples:]
            if len(rolling):
                sdk.run_chunk(np.pad(rolling, (0, max(0, window_samples - len(rolling))))[:window_samples], DITTO_CHUNKSIZE)
            # The online pipeline has a short causal tail. One additional
            # silent window supplies those final closing-mouth frames; the
            # exact sink limit prevents it from lengthening the utterance.
            # Without it, the pipeline consistently ended about four frames
            # short of the PCM clock on long answers.
            if sink.frame_count < target_frames:
                sdk.run_chunk(np.zeros((window_samples,), dtype=np.float32), DITTO_CHUNKSIZE)
        finally:
            sdk.close()
            sink.close()
            if sink.first_frame_at is not None:
                metrics.mark("first_frame_ready", sink.first_frame_at)
            if profile_enabled:
                self._write_pipeline_profile(body.turn_id, profile_started_at, profile_events, sink.first_frame_at)
            print(
                "Ditto realtime metrics: " + json.dumps({
                    "turn_id": body.turn_id,
                    "render_profile": body.render_profile,
                    "sampling_timesteps": sampling_timesteps,
                    "preroll_skip_frames": preroll_frames,
                    **metrics.as_milliseconds(
                        target_frames=target_frames,
                        emitted_frames=sink.frame_count,
                        dropped_tail=sink.dropped_tail_frames,
                    ),
                }, ensure_ascii=False, sort_keys=True),
                flush=True,
            )

class MuseTalkLiveRuntime:
    """Persistent one-photo MuseTalk 1.5 media path.

    It shares the public media contract with Ditto so the API and browser do
    not need a renderer-specific branch.  MuseTalk receives the whole local
    TTS WAV in this POC, but model/avatar preparation is cached and output is
    delivered as soon as individual 25fps frames are decoded.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.engine = None
        self.motion_engine = None
        self.turns: dict[str, LiveTurn] = {}
        self.lock = asyncio.Lock()

    def _load(self):
        if self.engine is None:
            from .musetalk_runtime import MuseTalkRuntime
            self.engine = MuseTalkRuntime(
                self.config.musetalk_root, self.config.musetalk_model_root, self.config.musetalk_batch_size
            )
        return self.engine

    def _load_motion(self):
        if self.motion_engine is None:
            from .liveportrait_runtime import LivePortraitMotionRuntime
            self.motion_engine = LivePortraitMotionRuntime(
                self.config.liveportrait_root,
                self.config.liveportrait_model_root,
                self.config.liveportrait_motion_frames,
            )
        return self.motion_engine

    async def prepare(self, avatar_id: str, source: Path) -> None:
        async with self.lock:
            base_frames = await asyncio.to_thread(self._load_motion().prepare, avatar_id, source)
            await asyncio.to_thread(self._load().prepare_frames, avatar_id, base_frames)

    async def synthesize(self, text: str, output: Path) -> Path:
        process = await asyncio.create_subprocess_exec(
            "espeak-ng", "-v", "ko", "-s", "165", "-w", str(output), text,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output.is_file() or output.stat().st_size < 128:
            raise HTTPException(status_code=502, detail=f"Local TTS failed: {stderr.decode(errors='replace')[-300:]}")
        return output

    async def start(self, body: RenderIn, source: Path, audio_dir: Path) -> tuple[str, str]:
        await self.prepare(body.avatar_id, source)
        audio = audio_dir / f"{body.turn_id}-{uuid.uuid4().hex[:8]}.wav"
        await self.synthesize(body.text, audio)
        frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        packets: asyncio.Queue[tuple[str, int, bytes]] = asyncio.Queue(maxsize=1024)
        video_pts: asyncio.Queue[int] = asyncio.Queue(maxsize=1024)
        websocket_connected = asyncio.Event()
        playback_started = asyncio.Event()
        placeholder = asyncio.create_task(asyncio.sleep(0), name=f"musetalk-live-placeholder-{body.turn_id}")
        turn = LiveTurn(
            frames=frames, audio=audio, task=placeholder, packets=packets,
            websocket_connected=websocket_connected, playback_started=playback_started, video_pts=video_pts,
        )
        task = asyncio.create_task(self._run(body.avatar_id, body.turn_id, audio, turn), name=f"musetalk-live-{body.turn_id}")
        turn.task = task
        self.turns[body.turn_id] = turn
        task.add_done_callback(DittoLiveRuntime._report_task_error)
        # RemoteRenderer recognizes the same private socket shape as Ditto
        # and remaps it to /avatar-stream-fast/ for this worker. Audio and
        # video packets use the same 25-fps clock.
        return f"/avatar-stream/v1/live/{body.turn_id}", f"/v1/assets/audio/{audio.name}"

    async def _run(self, avatar_id: str, turn_id: str, audio: Path, turn: LiveTurn) -> None:
        assert turn.websocket_connected is not None and turn.playback_started is not None and turn.packets is not None and turn.video_pts is not None
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(turn.websocket_connected.wait(), timeout=2.0)

        def packet_sink(kind: str, pts_ms: int, payload: bytes) -> None:
            if not turn.websocket_connected.is_set():
                return
            with contextlib.suppress(asyncio.QueueFull):
                turn.packets.put_nowait((kind, pts_ms, payload))
            if kind == "video":
                with contextlib.suppress(asyncio.QueueFull):
                    turn.video_pts.put_nowait(pts_ms)

        audio_task = asyncio.create_task(self._pump_pcm(audio, turn), name=f"musetalk-audio-{turn_id}") if turn.websocket_connected.is_set() else None
        async with self.lock:
            loop = asyncio.get_running_loop()
            with wave.open(str(audio), "rb") as wav:
                expected_frames = max(1, int(np.ceil(wav.getnframes() / wav.getframerate() * 25)))
            sink = MjpegFrameSink(
                loop, turn.frames, expected_frames=expected_frames, packet_sink=packet_sink,
                playback_started=turn.playback_started, pace_output=False,
            )
            try:
                rendered = await asyncio.to_thread(self._load().render, avatar_id, audio, sink)
                if rendered < 1:
                    raise RuntimeError("MuseTalk produced no video frames")
            finally:
                sink.close()
                first = None if sink.first_frame_at is None else round(sink.first_frame_at - sink.started_at, 3)
                print(f"MuseTalk live turn metrics: turn={turn_id} first_frame_s={first} frames={sink.frame_count}", flush=True)
        if audio_task is not None:
            await audio_task
        if turn.websocket_connected.is_set():
            await turn.packets.put(("end", 0, b""))

    async def _pump_pcm(self, audio: Path, turn: LiveTurn) -> None:
        """Release 40-ms audio blocks only once their visual PTS exists."""
        assert turn.packets is not None and turn.playback_started is not None and turn.video_pts is not None
        with wave.open(str(audio), "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            channels, width, sample_rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if channels == 1 and width == 2 and sample_rate == 16000:
            samples = np.frombuffer(raw, dtype=np.int16)
        else:
            import librosa
            normalized, _ = librosa.load(str(audio), sr=16000, mono=True)
            samples = np.clip(normalized * 32767.0, -32768, 32767).astype(np.int16)
        await turn.playback_started.wait()
        for start in range(0, len(samples), 640):
            pts_ms = start * 1000 // 16000
            while True:
                video_pts = await turn.video_pts.get()
                if video_pts >= pts_ms:
                    break
            await turn.packets.put(("audio", pts_ms, samples[start:start + 640].tobytes()))

    async def cancel(self, session_id: str) -> None:
        for turn in self.turns.values():
            if not turn.task.done():
                turn.task.cancel()

    def stream(self, turn_id: str):
        turn = self.turns.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)

        async def body():
            while True:
                try:
                    frame = await asyncio.wait_for(turn.frames.get(), timeout=0.25)
                except TimeoutError:
                    if turn.task.done():
                        break
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
        return body()


def safe_data_path(root: Path, requested: str) -> Path:
    path = Path(requested).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="file path must stay inside AVATAR_DATA_ROOT") from error
    return path


def create_app() -> FastAPI:
    config = WorkerConfig.from_env()
    cache = CacheStore(config.data_root / "avatar-cache")
    runtime = DittoBatchRuntime(config)
    # `ditto_live` is the stable/default reference. `ditto_realtime` keeps
    # the same image-to-motion model but receives incremental TTS PCM.
    live_runtime = DittoLiveRuntime(config) if config.mode == "ditto_live" else None
    realtime_runtime = DittoRealtimeRuntime(config) if config.mode == "ditto_realtime" else None
    idle_runtime = realtime_runtime or live_runtime
    musetalk_runtime = MuseTalkLiveRuntime(config) if config.mode == "musetalk_live" else None
    renders = config.data_root / "rendered"
    audio_assets = config.data_root / "audio"
    app = FastAPI(title="Empathic Avatar GPU Worker", version="0.1.0")

    @app.middleware("http")
    async def worker_access_gate(request: Request, call_next):
        if config.shared_token and request.url.path != "/health":
            supplied = request.headers.get("X-Worker-Token", "")
            if not secrets.compare_digest(supplied, config.shared_token):
                return Response(status_code=401, content='{"detail":"Unauthorized"}', media_type="application/json")
        return await call_next(request)

    @app.on_event("startup")
    async def startup() -> None:
        config.data_root.mkdir(parents=True, exist_ok=True)
        cache.setup()
        renders.mkdir(parents=True, exist_ok=True)
        audio_assets.mkdir(parents=True, exist_ok=True)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": config.mode}

    @app.post("/v1/avatars/prepare")
    async def prepare(body: PrepareIn) -> dict[str, str]:
        source = safe_data_path(config.data_root, body.source_path)
        if not source.is_file():
            raise HTTPException(status_code=404, detail="source image does not exist in shared data volume")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if live_runtime:
            await live_runtime.prepare(body.avatar_id, source)
        if realtime_runtime:
            await realtime_runtime.prepare(body.avatar_id, source)
        if musetalk_runtime:
            await musetalk_runtime.prepare(body.avatar_id, source)
        renderer_name = "musetalk" if musetalk_runtime else "ditto"
        cache_ref = f"{renderer_name}:{body.avatar_id}:{body.avatar_version}:{digest[:12]}"
        cache.save(body.avatar_id, {"cache_ref": cache_ref, "source_path": str(source), "source_sha256": digest, "avatar_version": body.avatar_version, "quality": body.quality, "renderer": renderer_name})
        return {"cache_ref": cache_ref, "state": "ready"}

    @app.post("/v1/avatars/idle")
    async def prepare_idle(body: IdleIn) -> dict[str, object]:
        if idle_runtime is None:
            raise HTTPException(status_code=409, detail="Idle loops require a Ditto live renderer")
        source = safe_data_path(config.data_root, body.source_path)
        if not source.is_file():
            raise HTTPException(status_code=404, detail="source image does not exist in shared data volume")
        outputs = await idle_runtime.prepare_idle(body.avatar_id, source, body.variants)
        return {"status": "ready", "variants": len(outputs)}

    @app.get("/v1/assets/idle/{avatar_id}/{variant}")
    async def idle_asset(avatar_id: str, variant: int) -> FileResponse:
        if idle_runtime is None or variant < 0 or variant > 2:
            raise HTTPException(status_code=404, detail="idle loop not found")
        path = idle_runtime.idle_path(avatar_id, variant)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="idle loop not prepared")
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/v1/turns/render")
    async def render(body: RenderIn) -> dict:
        try:
            avatar = cache.get(body.avatar_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="avatar must be prepared before rendering") from error
        if config.mode == "stub":
            return {"status": "media-plane-not-attached", "stream_url": None, "visemes": []}
        source = safe_data_path(config.data_root, avatar["source_path"])
        if live_runtime:
            stream_url, audio_url = await live_runtime.start(body, source, audio_assets)
            return {
                "status": "streaming-ws-ditto-controlled",
                "stream_url": stream_url,
                "audio_url": audio_url,
                "visemes": [],
                "applied_motion": (body.motion_plan or MotionPlan()).model_dump(mode="json"),
            }
        if realtime_runtime:
            stream_url, audio_url = await realtime_runtime.start(body, source, audio_assets)
            return {
                "status": "streaming-ws-ditto-realtime",
                "stream_url": stream_url,
                "audio_url": audio_url,
                "visemes": [],
                "applied_motion": (body.motion_plan or MotionPlan()).model_dump(mode="json"),
            }
        if musetalk_runtime:
            stream_url, audio_url = await musetalk_runtime.start(body, source, audio_assets)
            return {
                "status": "streaming-ws-musetalk",
                "stream_url": stream_url,
                "audio_url": audio_url,
                "visemes": [],
            }
        suffix = uuid.uuid4().hex[:8]
        filename = f"{body.turn_id}-{suffix}.mp4"
        output = renders / filename
        await runtime.render(body, source, output)
        return {
            "status": "rendered-mp4-ditto-sync-reference",
            "stream_url": f"/v1/assets/renders/{filename}",
            "visemes": [],
            "applied_motion": None,
        }

    @app.delete("/v1/avatars/{avatar_id}", status_code=204)
    async def delete_avatar(avatar_id: str):
        cache.delete(avatar_id)
        if idle_runtime is not None:
            for variant in range(3):
                idle_runtime.idle_path(avatar_id, variant).unlink(missing_ok=True)
        # Derived Ditto tensors must live under a per-avatar cache directory in
        # the streaming implementation and be removed here as well.
        return None

    @app.post("/v1/turns/cancel")
    async def cancel(body: CancelIn) -> dict[str, str]:
        await runtime.cancel(body.session_id)
        if live_runtime:
            await live_runtime.cancel(body.session_id)
        if realtime_runtime:
            await realtime_runtime.cancel(body.session_id)
        if musetalk_runtime:
            await musetalk_runtime.cancel(body.session_id)
        return {"state": "ready"}

    @app.websocket("/v1/live/{turn_id}")
    async def live_socket(websocket: WebSocket, turn_id: str) -> None:
        if config.shared_token:
            supplied = websocket.headers.get("X-Worker-Token", "")
            if not secrets.compare_digest(supplied, config.shared_token):
                await websocket.close(code=1008)
                return
        active_runtime = realtime_runtime or live_runtime or musetalk_runtime
        if active_runtime is None:
            await websocket.close(code=1008)
            return
        turn = active_runtime.turns.get(turn_id)
        if turn is None or turn.packets is None or turn.websocket_connected is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        turn.websocket_connected.set()
        packet_type = {"audio": 1, "video": 2, "end": 3}
        try:
            while True:
                kind, pts_ms, payload = await turn.packets.get()
                await websocket.send_bytes(struct.pack(">BI", packet_type[kind], pts_ms) + payload)
                if kind == "end":
                    await websocket.close()
                    break
        except WebSocketDisconnect:
            return

    @app.get("/v1/assets/live/{turn_id}")
    async def live_asset(turn_id: str) -> StreamingResponse:
        active_runtime = realtime_runtime or musetalk_runtime or live_runtime
        if not active_runtime:
            raise HTTPException(status_code=404, detail="live renderer not enabled")
        try:
            stream = active_runtime.stream(turn_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="live stream not found") from error
        return StreamingResponse(stream, media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})

    @app.get("/v1/assets/audio/{filename}")
    async def audio_asset(filename: str) -> FileResponse:
        if Path(filename).name != filename:
            raise HTTPException(status_code=404, detail="audio not found")
        path = audio_assets / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="audio not found")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=60"})

    @app.get("/v1/assets/renders/{filename}")
    async def render_asset(filename: str) -> FileResponse:
        if Path(filename).name != filename:
            raise HTTPException(status_code=404, detail="render not found")
        path = renders / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="render not found")
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=60"})

    return app


app = create_app()
