from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import struct
import sys
import time
import traceback
import uuid
import wave
from dataclasses import dataclass
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


class RenderIn(BaseModel):
    avatar_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    audio_path: str | None = None
    text: str = Field(default="", max_length=4_000)
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


class CancelIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class WorkerConfig:
    data_root: Path
    mode: Literal["stub", "ditto_batch", "ditto_live", "musetalk_live"]
    ditto_root: Path
    model_root: Path
    config_path: Path
    sampling_timesteps: int
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
        if mode not in {"stub", "ditto_batch", "ditto_live", "musetalk_live"}:
            raise ValueError("AVATAR_RENDER_MODE must be stub, ditto_batch, ditto_live, or musetalk_live")
        # Ditto's public default is aimed at offline quality.  Four steps is
        # our explicit conversational preset: it materially reduces the
        # first-audio-frame wait while retaining enough denoising for the
        # small, front-facing live-avatar plane.  Deployments can raise this
        # independently for a quality tier.
        sampling_timesteps = int(os.getenv("DITTO_SAMPLING_TIMESTEPS", "4"))
        if not 1 <= sampling_timesteps <= 50:
            raise ValueError("DITTO_SAMPLING_TIMESTEPS must be between 1 and 50")
        return cls(
            data_root=Path(os.getenv("AVATAR_DATA_ROOT", "/data")).resolve(),
            mode=mode,
            ditto_root=Path(os.getenv("DITTO_ROOT", "/opt/ditto")).resolve(),
            model_root=Path(os.getenv("DITTO_MODEL_ROOT", "/models/ditto/ditto_pytorch")).resolve(),
            config_path=Path(os.getenv("DITTO_CONFIG", "/models/ditto/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl")).resolve(),
            sampling_timesteps=sampling_timesteps,
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

    def _warm_avatar(self, avatar_id: str) -> None:
        """Move lazy CUDA/ONNX/PyTorch work out of the first spoken turn.

        Ditto creates its per-turn workers lazily.  Without this small silent
        pass, the first conversational turn pays for allocator setup, kernel
        selection and the first Audio2Motion execution before it can emit a
        frame.  Avatar preparation already runs before the avatar is marked
        ready, so this is the right place to pay that one-time cost.
        """
        if avatar_id in self.warmed_avatars:
            return
        sdk = self._load_sdk()
        chunksize = DITTO_CHUNKSIZE
        window_samples = int(sum(chunksize) * 0.04 * 16000) + 80
        sink = DiscardFrameSink()
        started = time.monotonic()
        sdk.setup(
            "", "", frame_sink=sink, source_info=self.avatar_sources[avatar_id], online_mode=True,
            sampling_timesteps=self.config.sampling_timesteps,
            emo=DITTO_EMOTION_INDEX["neutral"], ctrl_info={},
        )
        try:
            # Two causal windows are enough to execute the feature extractor,
            # diffusion path, warp/decode and writer workers at least once.
            sdk.setup_Nd(10, ctrl_info={})
            silence = np.zeros((window_samples,), dtype=np.float32)
            sdk.run_chunk(silence, chunksize)
            sdk.run_chunk(silence, chunksize)
        finally:
            sdk.close()
        self.warmed_avatars.add(avatar_id)
        print(f"Ditto avatar warm-up: avatar={avatar_id} elapsed_s={time.monotonic() - started:.3f}", flush=True)

    async def prepare(self, avatar_id: str, source: Path) -> None:
        async with self.lock:
            await asyncio.to_thread(self._register_avatar, avatar_id, source)
            await asyncio.to_thread(self._warm_avatar, avatar_id)

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
        task = asyncio.create_task(self._run(body.avatar_id, body.turn_id, audio, frames), name=f"musetalk-live-{body.turn_id}")
        self.turns[body.turn_id] = LiveTurn(frames=frames, audio=audio, task=task)
        task.add_done_callback(DittoLiveRuntime._report_task_error)
        return f"/v1/assets/live/{body.turn_id}", f"/v1/assets/audio/{audio.name}"

    async def _run(self, avatar_id: str, turn_id: str, audio: Path, frames: asyncio.Queue[bytes]) -> None:
        async with self.lock:
            loop = asyncio.get_running_loop()
            sink = MjpegFrameSink(loop, frames)
            try:
                rendered = await asyncio.to_thread(self._load().render, avatar_id, audio, sink)
                if rendered < 1:
                    raise RuntimeError("MuseTalk produced no video frames")
            finally:
                sink.close()
                first = None if sink.first_frame_at is None else round(sink.first_frame_at - sink.started_at, 3)
                print(f"MuseTalk live turn metrics: turn={turn_id} first_frame_s={first} frames={sink.frame_count}", flush=True)

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
    # `ditto_batch` is Ditto's official offline pipeline: it produces a single
    # MP4 with the exact input WAV muxed in, which is the sync reference path.
    # The MJPEG adapter remains available behind `ditto_live` while its
    # incremental PCM/clocking implementation is benchmarked separately.
    live_runtime = DittoLiveRuntime(config) if config.mode == "ditto_live" else None
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
        if musetalk_runtime:
            await musetalk_runtime.prepare(body.avatar_id, source)
        renderer_name = "musetalk" if musetalk_runtime else "ditto"
        cache_ref = f"{renderer_name}:{body.avatar_id}:{body.avatar_version}:{digest[:12]}"
        cache.save(body.avatar_id, {"cache_ref": cache_ref, "source_path": str(source), "source_sha256": digest, "avatar_version": body.avatar_version, "quality": body.quality, "renderer": renderer_name})
        return {"cache_ref": cache_ref, "state": "ready"}

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
                "status": "streaming-mjpeg-ditto-controlled",
                "stream_url": stream_url,
                "audio_url": audio_url,
                "visemes": [],
                "applied_motion": (body.motion_plan or MotionPlan()).model_dump(mode="json"),
            }
        if musetalk_runtime:
            stream_url, audio_url = await musetalk_runtime.start(body, source, audio_assets)
            return {
                "status": "streaming-mjpeg-musetalk",
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
        # Derived Ditto tensors must live under a per-avatar cache directory in
        # the streaming implementation and be removed here as well.
        return None

    @app.post("/v1/turns/cancel")
    async def cancel(body: CancelIn) -> dict[str, str]:
        await runtime.cancel(body.session_id)
        if live_runtime:
            await live_runtime.cancel(body.session_id)
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
        active_runtime = live_runtime or musetalk_runtime
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
        active_runtime = musetalk_runtime or live_runtime
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
