"""Isolated photo-to-Gaussian conversation lab (localhost:8030)."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import math
import array
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .gaussian_a2f import A2FClient
from .gaussian_behavior import BehaviorController
from .gaussian_realtime import RealtimeVoice, BehaviorIntent
from .gaussian_store import AvatarFiles, SessionLog, checked_id, utc_now, validate_asset_zip
from .perception import PerceptionClient


class SessionIn(BaseModel):
    avatar_id: str
    voice: Literal["marin", "cedar", "echo", "alloy", "coral", "sage", "shimmer", "ash", "ballad", "verse"] = "marin"
    instructions: str = Field(default="따뜻하고 차분하게 한국어로 짧게 대화하세요.", max_length=4000)


class ControlIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    emotion: Literal["neutral", "happy", "sad", "angry", "fear", "surprise", "disgust", "contempt"] = "neutral"
    intensity: float = Field(default=0.35, ge=0, le=1)
    gaze_x: float = Field(default=0, ge=-1, le=1)
    gaze_y: float = Field(default=0, ge=-1, le=1)
    head_yaw: float = Field(default=0, ge=-12, le=12)
    head_pitch: float = Field(default=0, ge=-10, le=10)
    head_roll: float = Field(default=0, ge=-6, le=6)
    nod: bool = False
    auto: bool = False


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=4000)
    turn_id: str | None = None


def create_gaussian_app(root: Path | None = None, api_key: str | None = None) -> FastAPI:
    data = (root or Path(os.getenv("GAUSSIAN_DATA_DIR", "data/gaussian"))).resolve()
    files = AvatarFiles(data)
    key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini")
    a2f_endpoint = os.getenv("GAUSSIAN_A2F_ENDPOINT", "127.0.0.1:52000")
    generator_url = os.getenv("GAUSSIAN_GENERATOR_URL", "http://127.0.0.1:8040").rstrip("/")
    generator_root = os.getenv("GAUSSIAN_GENERATOR_DATA_DIR", "/gaussian-data").rstrip("/")
    sessions: dict[str, dict] = {}
    jobs: set[asyncio.Task] = set()
    active_rooms: dict[str, GaussianRoom] = {}
    origins = {"http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:4173", "http://localhost:5173", "http://127.0.0.1:5173"}

    @asynccontextmanager
    async def lifespan(app):
        for avatar in files.list():
            if avatar["status"] == "preparing":
                avatar.update(status="error", error="생성 작업이 서버 재시작으로 중단되었습니다. 사진을 다시 업로드해 주세요.")
                files.save(avatar)
        yield
        for room in list(active_rooms.values()):
            await room.close()
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(title="Gaussian Avatar Lab", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.middleware("http")
    async def local_write_guard(request: Request, call_next):
        if request.method == "POST" and request.headers.get("origin") not in origins | {None}:
            return Response(status_code=403, content="Unexpected origin")
        return await call_next(request)

    def avatar_or_404(avatar_id: str):
        try:
            return files.get(avatar_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Avatar not found")

    def session_or_404(session_id: str):
        try:
            checked_id(session_id)
        except ValueError:
            raise HTTPException(404, "Session not found")
        if session_id not in sessions:
            config_file = data / "sessions" / session_id / "session.json"
            if config_file.is_file():
                return {"config": json.loads(config_file.read_text(encoding="utf-8")), "log": None}
            raise HTTPException(404, "Session not found")
        return sessions[session_id]

    async def generator_health():
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(generator_url + "/health")
                response.raise_for_status()
                result = response.json()
                result["detail"] = result.get("phase", "") if result.get("ready") else result.get("last_error") or str(result.get("missing_assets") or result.get("phase", "not ready"))
                return result
        except Exception as error:
            return {"ready": False, "detail": "생성 워커 연결 대기", "error": type(error).__name__}

    @app.get("/gaussian-api/health")
    async def health():
        a2f, generator = await asyncio.gather(A2FClient(a2f_endpoint).health(), generator_health())
        return {"openai": {"ready": bool(key), "model": model, "status": "configured" if key else "missing_key"},
                "a2f": a2f, "generator": generator, "renderer": "LAM 3DGS WebGL",
                "logging": {"enabled": True, "path": str(data / "sessions"), "audio": True, "transcripts": True},
                "controller": "SOBIA-inspired rule-based v1; separate from trained empathy research model"}

    @app.get("/gaussian-api/avatars")
    async def avatars():
        return files.list()

    async def generate(record: dict):
        directory = files.directory(record["id"])
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(1500, connect=10), trust_env=False) as client:
                response = await client.post(generator_url + "/generate", json={
                    "job_id": record["id"], "image_path": f"{generator_root}/avatars/{record['id']}/source.png",
                    "output_dir": f"{generator_root}/avatars/{record['id']}"})
                response.raise_for_status()
                result = response.json()
            # Never accept arbitrary returned host paths. Worker output must be
            # located under this avatar's shared directory.
            asset_name = Path(result.get("asset_path", "asset.zip")).name
            asset_path = directory / asset_name
            raw = asset_path.read_bytes()
            validate_asset_zip(raw)
            if asset_path.name != "asset.zip":
                (directory / "asset.zip").write_bytes(raw)
            record.update(status="ready", error=None, generation=result, asset_sha256=hashlib.sha256(raw).hexdigest())
        except Exception as error:
            detail = str(error)
            if isinstance(error, httpx.HTTPStatusError):
                detail = error.response.text[:1500]
            record.update(status="error", error=detail[:2000])
        files.save(record)

    @app.post("/gaussian-api/avatars")
    async def upload(image: UploadFile = File(...), name: str = Form("새 3DGS 아바타")):
        try:
            raw = await image.read(15*1024*1024+1)
            record = files.create(name, "photo", photo=raw)
        except ValueError as error:
            raise HTTPException(400, str(error))
        task = asyncio.create_task(generate(record))
        jobs.add(task)
        task.add_done_callback(jobs.discard)
        return record

    @app.post("/gaussian-api/avatars/import")
    async def import_avatar(file: UploadFile = File(...), name: str = Form("LAM 가져오기")):
        try:
            raw = await file.read(150*1024*1024+1)
            return await asyncio.to_thread(files.create, name, "import", asset=raw)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.get("/gaussian-api/avatars/{avatar_id}")
    async def avatar(avatar_id: str):
        return avatar_or_404(avatar_id)

    @app.get("/gaussian-api/avatars/{avatar_id}/asset.zip")
    async def asset(avatar_id: str):
        record = avatar_or_404(avatar_id)
        path = files.directory(avatar_id) / "asset.zip"
        if record["status"] != "ready" or not path.is_file():
            raise HTTPException(409, "Avatar is not ready")
        return FileResponse(path, media_type="application/zip", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/gaussian-api/avatars/{avatar_id}/source")
    async def source(avatar_id: str):
        avatar_or_404(avatar_id)
        path = files.directory(avatar_id) / "source.png"
        if not path.is_file():
            raise HTTPException(404, "No source image")
        return FileResponse(path, media_type="image/png")

    @app.get("/gaussian-api/avatars/{avatar_id}/reference-video")
    async def reference_video(avatar_id: str):
        record = avatar_or_404(avatar_id)
        path = files.directory(avatar_id) / "reference.mp4"
        if record.get("kind") != "reference_video" or not path.is_file():
            raise HTTPException(404, "No official reference video")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/gaussian-api/test-audio")
    async def test_audio(preset: str = "reference"):
        presets = {"reference": "reference.wav", "ash-en": "ash_gpt-4o-mini-tts_1x_2026-09-29T04_28_07-868Z.wav"}
        if preset not in presets:
            raise HTTPException(404, "Unknown WAV preset")
        path = data / "test-audio" / presets[preset]
        if not path.is_file():
            raise HTTPException(404, "기본 WAV가 없습니다. WAV 파일을 선택해 주세요.")
        return FileResponse(path, media_type="audio/wav")

    @app.post("/gaussian-api/sessions")
    async def create_session(body: SessionIn):
        selected = avatar_or_404(body.avatar_id)
        if selected["status"] != "ready" or selected.get("kind") == "reference_video":
            raise HTTPException(409, "Finish preparing an avatar first")
        if selected.get("kind") == "official_live":
            try:
                async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                    response = await client.get('http://127.0.0.1:8041/health')
                    response.raise_for_status()
            except Exception:
                raise HTTPException(503, "공식 GPU 렌더러를 시작해 주세요 (8041).")
        session_id = uuid.uuid4().hex[:24]
        config = {"id": session_id, **body.model_dump(), "created_at": utc_now(), "model": model,
                  "a2f_endpoint": a2f_endpoint, "avatar_sha256": selected.get("asset_sha256"),
                  "audio_format": "mono pcm16le 24000Hz", "controller": "rule_based_sobia_inspired_v1",
                  "avatar_engine": selected.get("kind", "lam"), "render_driver": "a2f-arkit-to-flame-v1" if selected.get("kind") == "official_live" else "lam-arkit"}
        log = SessionLog(data / "sessions", session_id, config)
        sessions[session_id] = {"config": config, "log": log}
        return {"id": session_id, "ws_url": f"/gaussian-ws/{session_id}", "logging": True}

    @app.get("/gaussian-api/sessions/{session_id}/logs.zip")
    async def logs(session_id: str):
        entry = session_or_404(session_id)
        if entry["log"]:
            contents = await asyncio.to_thread(entry["log"].archive)
        else:
            # Opening an archive must not append a new session-created event.
            import io, zipfile
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
                for path in (data / "sessions" / session_id).iterdir():
                    if path.is_file():
                        out.write(path, path.name)
            contents = buffer.getvalue()
        return Response(contents, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="gaussian-{session_id}.zip"'})

    @app.post("/gaussian-api/sessions/{session_id}/feedback")
    async def feedback(session_id: str, body: FeedbackIn):
        entry = session_or_404(session_id)
        record = {"at": utc_now(), **body.model_dump()}
        with (data / "sessions" / session_id / "feedback.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if entry["log"]:
            entry["log"].record("feedback", record)
        return {"saved": True}

    @app.websocket("/gaussian-ws/{session_id}")
    async def live(ws: WebSocket, session_id: str):
        if ws.headers.get("origin") not in origins | {None}:
            await ws.close(code=4403)
            return
        if session_id not in sessions or session_id in active_rooms:
            await ws.close(code=4409 if session_id in active_rooms else 4404)
            return
        entry = sessions[session_id]
        room = GaussianRoom(ws, entry["config"], entry["log"], key, a2f_endpoint)
        active_rooms[session_id] = room
        await ws.accept()
        try:
            await room.run()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await room.close()
            active_rooms.pop(session_id, None)

    app.state.gaussian_files = files
    return app


class GaussianRoom:
    def __init__(self, ws, config, log, key, endpoint):
        self.ws, self.config, self.log = ws, config, log
        self.key, self.endpoint = key, endpoint
        self.send_lock = asyncio.Lock()
        self.controller = BehaviorController()
        self.voice = RealtimeVoice(key, config["model"], config["voice"], config["instructions"], self.trace)
        self.turn_task: asyncio.Task | None = None
        self.idle_task: asyncio.Task | None = None
        self.turn_id: str | None = None
        self.input_pcm = bytearray()
        self.started = time.monotonic()
        self.manual = None
        self.manual_start = self.started
        self.closed = False
        self.state = "ready"
        self.perception_enabled = False
        self.perception = PerceptionClient(Path(os.getenv("GAUSSIAN_BASE_DATA_DIR", "data")))
        self.perception.token_path = Path(os.getenv("PERCEPTION_TOKEN_FILE", "data/perception/token"))
        self.last_observation = ""
        self.awaiting_playback: str | None = None

    def trace(self, event, payload):
        self.log.record(event, {"turn_id": self.turn_id, "details": payload})

    async def emit(self, kind, **data):
        if self.closed:
            return
        async with self.send_lock:
            await self.ws.send_json({"type": kind, **data})

    async def set_state(self, state):
        self.state = state
        self.trace("state", {"state": state})
        await self.emit("state", state=state)

    def active_plan(self, default=None):
        if self.manual:
            c = self.manual
            return self.controller.from_affect(c.emotion, c.intensity, intent="explaining", nod=c.nod,
                gaze={"x": c.gaze_x, "y": c.gaze_y}, head={"pitch": c.head_pitch, "yaw": c.head_yaw, "roll": c.head_roll}, source="manual_expression")
        return default or self.controller.from_affect("neutral", .2, intent="attentive")

    async def idle(self):
        count = 0
        while not self.closed:
            await asyncio.sleep(.05)
            count += 1
            if (not self.turn_task or self.turn_task.done()) and not self.awaiting_playback:
                elapsed = time.monotonic() - (self.manual_start if self.manual else self.started)
                mixed = self.controller.mix_frame({}, elapsed, self.active_plan(), speaking=False)
                packet = {"turn_id": "idle", "pts_ms": elapsed*1000, **mixed, "source": "behavior_controller"}
                await self.emit("animation.frame", **packet)
                self.trace("animation.idle", packet)
            if count % 20 == 0 and self.perception_enabled:
                obs, detail = await self.perception.snapshot(self.config["id"], True, 3000, self.state == "listening")
                self.last_observation = obs.context()
                self.trace("perception.snapshot", detail)
                await self.emit("perception", enabled=True, observation=obs.model_dump())

    async def run(self):
        await self.emit("session.ready", session_id=self.config["id"], model=self.config["model"], logging=True)
        self.idle_task = asyncio.create_task(self.idle())
        while True:
            try:
                packet = await self.ws.receive_json()
                if not isinstance(packet, dict):
                    raise ValueError("Expected an object command")
                kind = packet.get("type")
                if kind == "input.start":
                    await self.interrupt()
                    self.input_pcm.clear()
                    await self.set_state("listening")
                elif kind == "input.audio":
                    raw = base64.b64decode(packet.get("pcm_base64", ""), validate=True)
                    if len(raw) % 2 or len(raw) > 192000:
                        raise ValueError("Invalid microphone PCM chunk")
                    if len(self.input_pcm)+len(raw) > 24000*2*90:
                        self.input_pcm.clear()
                        raise ValueError("한 번에 90초 이하로 말씀해 주세요.")
                    self.input_pcm.extend(raw)
                    self.trace("input.audio", {"bytes": len(raw), "buffer_bytes": len(self.input_pcm)})
                elif kind == "test.commit":
                    if self.turn_task and not self.turn_task.done():
                        raise ValueError("현재 테스트를 중단한 뒤 재생해 주세요.")
                    if self.awaiting_playback:
                        await self.interrupt()
                    pcm = bytes(self.input_pcm)
                    self.input_pcm.clear()
                    if not 4800 <= len(pcm) <= 24000*2*90:
                        raise ValueError("WAV는 0.1초~90초여야 합니다.")
                    control = ControlIn.model_validate({**packet.get("control", {}), "auto": False})
                    self.manual = control
                    self.turn_id = uuid.uuid4().hex[:24]
                    self.trace("wav_test.input", {"filename": str(packet.get("filename", "WAV"))[:240],
                        "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "bytes": len(pcm), "control": control.model_dump()})
                    self.turn_task = asyncio.create_task(self.respond(self.turn_id, None, None, test_pcm=pcm))
                elif kind in {"input.commit", "input.text"}:
                    if self.turn_task and not self.turn_task.done():
                        raise ValueError("현재 응답을 중단한 후 새 발화를 보내 주세요.")
                    if not self.key:
                        raise ValueError("서버 OPENAI_API_KEY가 필요합니다.")
                    if self.awaiting_playback:
                        await self.interrupt()
                    text = str(packet.get("text", "")).strip()[:8000] if kind == "input.text" else None
                    audio = bytes(self.input_pcm) if kind == "input.commit" else None
                    self.input_pcm.clear()
                    if (audio is not None and len(audio) < 4800) or (text is not None and not text):
                        raise ValueError("100ms 이상의 음성 또는 대화 내용을 입력해 주세요.")
                    self.turn_id = uuid.uuid4().hex[:24]
                    self.turn_task = asyncio.create_task(self.respond(self.turn_id, text, audio))
                elif kind == "interrupt":
                    await self.interrupt()
                    self.input_pcm.clear()
                elif kind == "control":
                    body = packet.get("control") or {k: v for k, v in packet.items() if k != "type"}
                    control = ControlIn.model_validate(body)
                    self.manual = None if control.auto else control
                    self.voice.manual_intent = None if control.auto else BehaviorIntent(
                        emotion=control.emotion, intensity=control.intensity, intent="explaining", nod=control.nod,
                        head={"pitch": control.head_pitch, "yaw": control.head_yaw, "roll": control.head_roll},
                        gaze={"x": control.gaze_x, "y": control.gaze_y})
                    self.manual_start = time.monotonic()
                    self.trace("control.override", control.model_dump())
                    await self.emit("behavior", plan=self.active_plan().as_dict(), manual=self.manual is not None)
                elif kind == "perception":
                    enabled = bool(packet.get("enabled"))
                    try:
                        await self.perception.command("start" if enabled else "stop", self.config["id"])
                        self.perception_enabled = enabled
                        if not enabled:
                            self.last_observation = ""
                        await self.emit("perception", enabled=enabled)
                    except Exception as error:
                        raise ValueError("얼굴 분석 연결 실패: " + type(error).__name__)
                elif kind == "telemetry":
                    if len(json.dumps(packet)) > 24000:
                        raise ValueError("Telemetry payload too large")
                    self.trace("playback.telemetry", packet)
                    if packet.get("event") == "playback.complete" and packet.get("turn_id") == self.awaiting_playback:
                        self.voice.commit_playback()
                        self.awaiting_playback = None
                        self.turn_id = None
                        await self.set_state("ready")
                elif kind == "feedback":
                    feedback = FeedbackIn.model_validate({k: v for k, v in packet.items() if k != "type"})
                    self.trace("feedback", feedback.model_dump())
                    await self.emit("feedback.saved")
                else:
                    raise ValueError("Unknown command")
            except (ValueError, ValidationError) as error:
                self.trace("command.error", {"message": str(error)})
                await self.emit("error", message=str(error))

    async def respond(self, turn_id, text, audio, test_pcm=None):
        started = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        a2f_task = None
        samples = frames = 0
        first_audio = first_motion = None
        plan = self.active_plan()
        energy_windows = []
        energy_pending = bytearray()
        await self.emit("turn.started", turn_id=turn_id)
        self.awaiting_playback = turn_id
        await self.set_state("thinking")
        self.trace("turn.input", {"text": text, "audio_bytes": len(audio or b"")})
        if audio:
            self.log.audio(turn_id, "input", audio)

        async def chunks():
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item

        async def animate():
            nonlocal frames, first_motion
            client = A2FClient(self.endpoint, trace=self.trace)
            async for frame in client.stream(chunks()):
                frames += 1
                if first_motion is None:
                    first_motion = (time.monotonic()-started)*1000
                mixed = self.controller.mix_frame(frame.coefficients, frame.time_seconds, self.active_plan(plan))
                packet = {"turn_id": turn_id, "pts_ms": frame.time_seconds*1000, "speech_energy": energy_windows[min(int(frame.time_seconds*50),len(energy_windows)-1)] if energy_windows else 0., **mixed, "source": "nvidia_a2f+behavior_controller"}
                self.trace("animation.frame", packet)
                await self.emit("animation.frame", **packet)

        async def intent(chosen: BehaviorIntent):
            nonlocal plan, a2f_task
            plan = self.controller.from_affect(chosen.emotion, chosen.intensity, intent=chosen.intent, nod=chosen.nod,
                head=chosen.head.model_dump(), gaze=chosen.gaze.model_dump(),
                source="manual_expression" if self.manual else "llm_tool_call")
            self.trace("behavior.plan", plan.as_dict())
            await self.emit("behavior", turn_id=turn_id, plan=self.active_plan(plan).as_dict(), manual=self.manual is not None)
            a2f_task = asyncio.create_task(animate())

        async def enqueue(item):
            if a2f_task is None:
                raise RuntimeError("A2F was not initialized before audio output")
            put = asyncio.create_task(queue.put(item))
            try:
                done, _ = await asyncio.wait({put, a2f_task}, return_when=asyncio.FIRST_COMPLETED)
                if a2f_task in done:
                    await a2f_task
                    if item is not None or put not in done:
                        raise RuntimeError("A2F ended before all output audio was sent")
                await put
            finally:
                if not put.done():
                    put.cancel()
                    await asyncio.gather(put, return_exceptions=True)

        async def speech(pcm):
            nonlocal samples, first_audio
            if first_audio is None:
                first_audio = (time.monotonic()-started)*1000
                await self.set_state("speaking")
            energy_pending.extend(pcm)
            while len(energy_pending)>=960:
                window=array.array('h',energy_pending[:960]);del energy_pending[:960]
                rms=math.sqrt(sum((v/32768.)**2 for v in window)/len(window))
                energy_windows.append(min(1.,rms*8.))
            self.log.audio(turn_id, "output", pcm)
            await enqueue(pcm)
            await self.emit("audio.chunk", turn_id=turn_id, seq=samples, pts_ms=samples/24,
                            sample_rate=24000, pcm_base64=base64.b64encode(pcm).decode())
            samples += len(pcm)//2

        async def transcript(role, value, final):
            await self.emit("transcript.final" if final else "transcript.delta", turn_id=turn_id, role=role, text=value)
            if final:
                self.trace("transcript.final", {"role": role, "text": value})

        try:
            if test_pcm is not None:
                chosen = BehaviorIntent(emotion=plan.emotion, intensity=plan.intensity, intent=plan.intent,
                    nod=plan.nod, head=plan.head, gaze=plan.gaze)
                await intent(chosen)
                for offset in range(0, len(test_pcm), 12000):
                    await speech(test_pcm[offset:offset+12000])
                result = {"mode": "wav_test", "intent": chosen.model_dump(), "llm_called": False}
            else:
                result = await self.voice.turn(text, audio, self.last_observation, intent, speech, transcript)
            await enqueue(None)
            if a2f_task:
                await asyncio.wait_for(a2f_task, timeout=40)
            metrics = {"first_audio_ms": first_audio, "first_motion_ms": first_motion,
                       "duration_ms": samples/24, "animation_frames": frames,
                       "elapsed_ms": (time.monotonic()-started)*1000}
            self.trace("turn.done", {**result, **metrics})
            await self.emit("diagnostics", turn_id=turn_id, **metrics)
            await self.emit("turn.done", turn_id=turn_id, duration_ms=samples/24, **{"metrics": metrics})
        except asyncio.CancelledError:
            self.awaiting_playback = None
            self.voice.discard_playback()
            self.trace("turn.cancelled", {"audio_samples": samples, "frames": frames})
            raise
        except Exception as error:
            self.awaiting_playback = None
            self.voice.discard_playback()
            self.trace("turn.error", {"message": str(error), "class": type(error).__name__})
            await self.emit("error", turn_id=turn_id, message=str(error))
            await self.emit("turn.cancelled", turn_id=turn_id)
            await self.voice.close()
        finally:
            if a2f_task and not a2f_task.done():
                a2f_task.cancel()
            if a2f_task:
                await asyncio.gather(a2f_task, return_exceptions=True)
            if not self.awaiting_playback:
                await self.set_state("ready")

    async def interrupt(self):
        current = self.turn_id
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
            await asyncio.gather(self.turn_task, return_exceptions=True)
        self.turn_task = None
        # Reset upstream even after generation finished because browser may
        # still be playing queued speech. Never leave unheard output in context.
        if current:
            self.voice.discard_playback()
            await self.voice.close()
            await self.emit("turn.cancelled", turn_id=current)
            self.trace("interrupt", {"turn_id": current})
        self.turn_id = None
        self.awaiting_playback = None
        await self.set_state("ready")

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.turn_task:
            self.turn_task.cancel()
        if self.idle_task:
            self.idle_task.cancel()
        await asyncio.gather(*[t for t in (self.turn_task, self.idle_task) if t], return_exceptions=True)
        await self.voice.close()
        if self.perception_enabled:
            with contextlib.suppress(Exception):
                await self.perception.command("stop", self.config["id"])
        self.trace("session.closed", {})


app = create_gaussian_app()
