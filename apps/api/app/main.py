from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
import httpx

from .conversation import ConversationProvider, OllamaConversation, OpenAIRealtimeConversation, SafeDemoConversation
from .models import AvatarOut, CreateSessionIn, HealthOut, SessionOut, TurnIn, TurnOut, TurnTelemetryIn
from .quality import ImageValidationError, inspect_image
from .renderers import AvatarRenderer, PreviewRenderer, RemoteRenderer
from .settings import Settings
from .store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    store = Store(config.database_path)
    renderer: AvatarRenderer = RemoteRenderer(config.avatar_renderer_url, config.worker_shared_token) if config.avatar_engine == "remote" and config.avatar_renderer_url else PreviewRenderer()
    fast_renderer: AvatarRenderer | None = RemoteRenderer(
        config.fast_avatar_renderer_url, config.worker_shared_token, stream_prefix="/avatar-stream-fast/"
    ) if config.fast_avatar_renderer_url else None
    realtime_renderer: AvatarRenderer | None = RemoteRenderer(
        config.realtime_avatar_renderer_url, config.worker_shared_token, stream_prefix="/avatar-stream-realtime/"
    ) if config.realtime_avatar_renderer_url else None
    trt10_renderer: AvatarRenderer | None = RemoteRenderer(
        config.trt10_avatar_renderer_url, config.worker_shared_token, stream_prefix="/avatar-stream-trt10/"
    ) if config.trt10_avatar_renderer_url else None
    if config.conversation_backend == "openai_realtime":
        assert config.openai_api_key is not None
        conversation: ConversationProvider = OpenAIRealtimeConversation(config.openai_api_key, config.openai_realtime_model, config.data_dir)
    elif config.conversation_backend == "ollama":
        if not config.ollama_url:
            raise ValueError("OLLAMA_URL is required when CONVERSATION_BACKEND=ollama")
        conversation = OllamaConversation(config.ollama_url, config.ollama_model)
    else:
        conversation = SafeDemoConversation()
    upload_dir = config.data_dir / "uploads"
    telemetry_path = config.data_dir / "telemetry" / "turn-events.jsonl"
    telemetry_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        upload_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        store.initialize()
        yield

    app = FastAPI(title="Empathic Avatar Control API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def prototype_access_gate(request: Request, call_next):
        """Optional single-tenant gate for private deployments.

        This is intentionally not a replacement for OIDC/session-based tenant
        authorization; it prevents accidental exposure while an auth gateway is
        being integrated.
        """
        if config.api_access_token and request.url.path != "/api/health":
            supplied = request.headers.get("X-Avatar-Token", "")
            if not secrets.compare_digest(supplied, config.api_access_token):
                return Response(status_code=401, content='{"detail":"Unauthorized"}', media_type="application/json")
        return await call_next(request)

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        return HealthOut(status="ok", engine=renderer.mode, llm=conversation.name)

    @app.post("/api/telemetry/turn", status_code=204)
    async def record_turn_telemetry(body: TurnTelemetryIn) -> Response:
        # Privacy boundary: this endpoint accepts timing/status fields only.
        # It never receives prompt text, TTS PCM, or JPEG/video payloads.
        record = {"turn_id": body.turn_id, "event": body.event, "elapsed_ms": body.elapsed_ms, "details": body.details}
        with telemetry_lock:
            with telemetry_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return Response(status_code=204)

    @app.get("/api/avatars", response_model=list[AvatarOut])
    async def list_avatars() -> list[AvatarOut]:
        return store.list_avatars()

    @app.get("/api/avatars/{avatar_id}", response_model=AvatarOut)
    async def get_avatar(avatar_id: str) -> AvatarOut:
        return _avatar_or_404(store, avatar_id)

    @app.post("/api/avatars", response_model=AvatarOut, status_code=201)
    async def create_avatar(
        background_tasks: BackgroundTasks,
        image: Annotated[UploadFile, File(...)],
        name: Annotated[str, Form(min_length=1, max_length=60)],
        persona: Annotated[str, Form(min_length=1, max_length=240)],
        voice: Annotated[str, Form(min_length=1, max_length=80)],
        consent_likeness: Annotated[bool, Form(...)],
        consent_adult: Annotated[bool, Form(...)],
        consent_ai_label: Annotated[bool, Form(...)],
    ) -> AvatarOut:
        if not (consent_likeness and consent_adult and consent_ai_label):
            raise HTTPException(status_code=422, detail="권리·성인·AI 표시 동의를 모두 확인해야 합니다.")
        raw = await _read_limited_upload(image)
        try:
            quality = inspect_image(raw, image.content_type)
        except ImageValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[image.content_type or ""]
        avatar_id = str(uuid.uuid4())
        source_path = upload_dir / f"{avatar_id}{suffix}"
        source_path.write_bytes(raw)
        status = "preparing" if renderer.mode == "remote" else "ready"
        avatar = store.create_avatar(
            avatar_id=avatar_id,
            name=name.strip(),
            persona=persona.strip(),
            voice=voice.strip(),
            source_path=str(source_path),
            status=status,
            engine=renderer.mode,
            quality=quality,
            likeness=consent_likeness,
            adult=consent_adult,
            ai_label=consent_ai_label,
        )
        if renderer.mode == "remote":
            background_tasks.add_task(_prepare_remote_avatar, store, renderer, avatar.id, source_path)
        else:
            prepared = await renderer.prepare(avatar, source_path)
            store.set_avatar_status(avatar.id, "ready", engine=renderer.mode, cache_ref=prepared.cache_ref)
            avatar = store.get_avatar(avatar.id)
        return avatar

    @app.get("/api/assets/{avatar_id}")
    async def source_asset(avatar_id: str) -> FileResponse:
        try:
            path = store.get_source_path(avatar_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="아바타를 찾을 수 없습니다.") from error
        if not path or not path.is_file():
            raise HTTPException(status_code=404, detail="원본 이미지가 없습니다.")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})

    def idle_renderer() -> RemoteRenderer | None:
        # Keep idle rendering isolated on the TRT10 worker when it is present;
        # a prepared loop is then served by the same worker for every method.
        for candidate in (trt10_renderer, realtime_renderer, renderer):
            if isinstance(candidate, RemoteRenderer):
                return candidate
        return None

    @app.post("/api/avatars/{avatar_id}/idle", status_code=202)
    async def prepare_idle_avatar(avatar_id: str) -> dict[str, str]:
        avatar = _avatar_or_404(store, avatar_id)
        source_path = store.get_source_path(avatar.id)
        selected = idle_renderer()
        if selected is None or source_path is None or not source_path.is_file():
            raise HTTPException(status_code=409, detail="Ditto idle renderer is not available")
        await selected.prepare_idle(avatar, source_path)
        return {"status": "ready"}

    @app.get("/api/avatars/{avatar_id}/idle/{variant}")
    async def idle_avatar_asset(avatar_id: str, variant: int) -> Response:
        _avatar_or_404(store, avatar_id)
        selected = idle_renderer()
        if selected is None:
            raise HTTPException(status_code=404, detail="idle loop not found")
        try:
            body, media_type = await selected.read_idle_asset(avatar_id, variant)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="idle loop not prepared") from error
        return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/avatars/{avatar_id}/idle/{variant}/mjpeg")
    async def idle_avatar_mjpeg(avatar_id: str, variant: int) -> StreamingResponse:
        _avatar_or_404(store, avatar_id)
        selected = idle_renderer()
        if selected is None or variant < 0 or variant > 2:
            raise HTTPException(status_code=404, detail="idle loop not found")

        async def proxy_stream():
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, read=None)) as client:
                url = f"{selected.base_url}/v1/assets/idle/{avatar_id}/{variant}/mjpeg"
                async with client.stream("GET", url, headers=selected.headers) as upstream:
                    if upstream.status_code == 404:
                        return
                    upstream.raise_for_status()
                    async for chunk in upstream.aiter_raw():
                        yield chunk

        return StreamingResponse(
            proxy_stream(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/rendered/{filename}")
    async def rendered_asset(filename: str) -> Response:
        if not isinstance(renderer, RemoteRenderer):
            raise HTTPException(status_code=404, detail="렌더 결과를 찾을 수 없습니다.")
        try:
            body, media_type = await renderer.read_render(filename)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="렌더 결과를 찾을 수 없습니다.") from error
        return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=60"})

    @app.get("/api/live-media/{turn_id}")
    async def live_media_asset(turn_id: str) -> StreamingResponse:
        if not isinstance(renderer, RemoteRenderer):
            raise HTTPException(status_code=404, detail="라이브 스트림을 찾을 수 없습니다.")

        async def proxy_stream():
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, read=180)) as client:
                async with client.stream("GET", f"{renderer.base_url}/v1/assets/live/{turn_id}", headers=renderer.headers) as upstream:
                    if upstream.status_code == 404:
                        return
                    upstream.raise_for_status()
                    async for chunk in upstream.aiter_raw():
                        yield chunk

        return StreamingResponse(proxy_stream(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/live-audio/{filename}")
    async def live_audio_asset(filename: str) -> Response:
        if not isinstance(renderer, RemoteRenderer):
            raise HTTPException(status_code=404, detail="라이브 오디오를 찾을 수 없습니다.")
        try:
            body, media_type = await renderer.read_live_asset(filename, "audio")
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="라이브 오디오를 찾을 수 없습니다.") from error
        return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=60"})

    @app.delete("/api/avatars/{avatar_id}", status_code=204)
    async def delete_avatar(avatar_id: str) -> Response:
        _avatar_or_404(store, avatar_id)
        try:
            renderers = [renderer, *([realtime_renderer] if realtime_renderer else []), *([trt10_renderer] if trt10_renderer else []), *([fast_renderer] if fast_renderer else [])]
            await asyncio.gather(*(item.delete(avatar_id) for item in renderers))
        except Exception as error:
            raise HTTPException(status_code=502, detail="GPU 캐시를 지우지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
        try:
            source_path = store.delete_avatar(avatar_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="아바타를 찾을 수 없습니다.") from error
        if source_path and source_path.is_file():
            source_path.unlink()
        return Response(status_code=204)

    @app.post("/api/live/sessions", response_model=SessionOut, status_code=201)
    async def create_session(body: CreateSessionIn) -> SessionOut:
        avatar = _avatar_or_404(store, body.avatar_id)
        if avatar.status != "ready":
            raise HTTPException(status_code=409, detail="아바타 준비가 끝난 뒤 대화를 시작할 수 있습니다.")
        # A restarted GPU worker has no in-memory source registration. Warm it
        # while the room says "connecting", so the first utterance does not
        # pay the photo-registration cost.
        selected_renderer = _renderer_for_method(body.renderer_method, renderer, realtime_renderer, trt10_renderer, fast_renderer)
        if isinstance(selected_renderer, RemoteRenderer):
            source_path = store.get_source_path(avatar.id)
            if source_path and source_path.is_file():
                try:
                    await selected_renderer.prepare(avatar, source_path)
                except Exception as error:
                    label = "Ditto Realtime TensorRT 10" if body.renderer_method == "ditto_realtime_trt10" else "Ditto Realtime Fast Lane" if body.renderer_method == "ditto_realtime_fast" else "Ditto Realtime" if body.renderer_method == "ditto_realtime" else "Fast Live" if body.renderer_method == "fast" else "Ditto Default"
                    raise HTTPException(status_code=502, detail=f"{label} GPU 아바타 준비에 실패했습니다.") from error
        instruction = body.session_instruction.strip() if body.session_instruction else None
        session = store.create_session(str(uuid.uuid4()), avatar.id, body.renderer_method, instruction)
        try:
            await conversation.start_session(session.id, persona=avatar.persona, session_instruction=instruction)
        except Exception as error:
            store.end_session(session.id)
            raise HTTPException(status_code=502, detail="OpenAI Realtime 세션 연결에 실패했습니다.") from error
        return session

    @app.post("/api/live/sessions/{session_id}/turns", response_model=TurnOut)
    async def create_turn(session_id: str, body: TurnIn) -> TurnOut:
        session = _session_or_404(store, session_id)
        if session.state != "active":
            raise HTTPException(status_code=409, detail="종료된 세션입니다.")
        avatar = _avatar_or_404(store, session.avatar_id)
        selected_renderer = _renderer_for_method(session.renderer_method, renderer, realtime_renderer, trt10_renderer, fast_renderer)
        turn_id = body.client_turn_id or str(uuid.uuid4())
        store.set_active_turn(session_id, turn_id)
        conversation_response = await conversation.respond(persona=avatar.persona, user_text=body.text.strip(), session_instruction=session.session_instruction, session_id=session_id, turn_id=turn_id)
        if not store.is_active_turn(session_id, turn_id):
            raise HTTPException(status_code=409, detail="응답이 새 발화로 인해 취소되었습니다.")
        visemes, renderer_out = await selected_renderer.render(
            avatar,
            session_id=session_id,
            turn_id=turn_id,
            text=conversation_response.text,
            audio_path=conversation_response.audio_path,
            audio_streaming=conversation_response.audio_streaming,
            motion_plan=body.motion_plan,
        )
        if not store.is_active_turn(session_id, turn_id):
            raise HTTPException(status_code=409, detail="응답이 새 발화로 인해 취소되었습니다.")
        store.set_active_turn(session_id, None)
        return TurnOut(turn_id=turn_id, assistant_text=conversation_response.text, visemes=visemes, renderer=renderer_out)

    @app.get("/api/live/sessions/{session_id}/turns/{turn_id}/caption")
    async def get_turn_caption(session_id: str, turn_id: str) -> dict[str, str | bool | None]:
        _session_or_404(store, session_id)
        caption = conversation.caption_status(session_id, turn_id)
        if caption is None:
            return {"text": None, "done": False}
        text, done = caption
        return {"text": text, "done": done}

    @app.post("/api/live/sessions/{session_id}/interrupt")
    async def interrupt_session(session_id: str) -> dict[str, str]:
        _session_or_404(store, session_id)
        store.set_active_turn(session_id, None)
        try:
            await _renderer_for_method(_session_or_404(store, session_id).renderer_method, renderer, realtime_renderer, trt10_renderer, fast_renderer).cancel(session_id)
        except Exception:
            # The control plane must still release the UI immediately; GPU retry is observable elsewhere.
            pass
        return {"state": "ready"}

    @app.delete("/api/live/sessions/{session_id}", status_code=204)
    async def end_session(session_id: str) -> Response:
        try:
            store.end_session(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from error
        await conversation.close_session(session_id)
        return Response(status_code=204)

    @app.websocket("/ws/live/{session_id}")
    async def live_websocket(websocket: WebSocket, session_id: str) -> None:
        """Lightweight live-control channel; media tracks move to LiveKit in GPU mode."""
        supplied_token = websocket.headers.get("X-Avatar-Token") or websocket.query_params.get("access_token") or ""
        if config.api_access_token and not secrets.compare_digest(supplied_token, config.api_access_token):
            await websocket.close(code=4401)
            return
        try:
            session = _session_or_404(store, session_id)
        except HTTPException:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        await websocket.send_json({"type": "room.state", "state": "ready", "session_id": session.id})
        try:
            while True:
                payload = await websocket.receive_json()
                if payload.get("type") == "interrupt":
                    store.set_active_turn(session_id, None)
                    await _renderer_for_method(session.renderer_method, renderer, realtime_renderer, trt10_renderer, fast_renderer).cancel(session_id)
                    await websocket.send_json({"type": "turn.cancelled"})
                    continue
                if payload.get("type") != "turn" or not isinstance(payload.get("text"), str):
                    await websocket.send_json({"type": "error", "detail": "Expected {type: 'turn', text: string}"})
                    continue
                text = payload["text"].strip()
                if not text:
                    continue
                try:
                    turn_body = TurnIn.model_validate({"text": text, "motion_plan": payload.get("motion_plan")})
                except Exception as error:
                    await websocket.send_json({"type": "error", "detail": f"Invalid motion_plan: {error}"})
                    continue
                avatar = _avatar_or_404(store, session.avatar_id)
                selected_renderer = _renderer_for_method(session.renderer_method, renderer, realtime_renderer, trt10_renderer, fast_renderer)
                turn_id = str(uuid.uuid4())
                store.set_active_turn(session_id, turn_id)
                await websocket.send_json({"type": "turn.started", "turn_id": turn_id})
                answer = await conversation.respond(persona=avatar.persona, user_text=text, session_instruction=session.session_instruction, session_id=session_id, turn_id=turn_id)
                if not store.is_active_turn(session_id, turn_id):
                    await websocket.send_json({"type": "turn.cancelled", "turn_id": turn_id})
                    continue
                visemes, render_out = await selected_renderer.render(
                    avatar,
                    session_id=session_id,
                    turn_id=turn_id,
                    text=answer.text,
                    audio_path=answer.audio_path,
                    audio_streaming=answer.audio_streaming,
                    motion_plan=turn_body.motion_plan,
                )
                store.set_active_turn(session_id, None)
                await websocket.send_json({"type": "caption.final", "turn_id": turn_id, "text": answer.text})
                await websocket.send_json({"type": "renderer", "turn_id": turn_id, "visemes": [item.model_dump() for item in visemes], "renderer": render_out.model_dump()})
        except WebSocketDisconnect:
            return

    app.state.store = store
    app.state.settings = config
    return app


async def _prepare_remote_avatar(store: Store, renderer: AvatarRenderer, avatar_id: str, source_path: Path) -> None:
    try:
        avatar = store.get_avatar(avatar_id)
        preparation = await renderer.prepare(avatar, source_path)
        store.set_avatar_status(avatar_id, "ready", engine=renderer.mode, cache_ref=preparation.cache_ref)
    except Exception:
        store.set_avatar_status(avatar_id, "failed", engine=renderer.mode)


def _avatar_or_404(store: Store, avatar_id: str) -> AvatarOut:
    try:
        return store.get_avatar(avatar_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="아바타를 찾을 수 없습니다.") from error


def _renderer_for_method(method: str, ditto_renderer: AvatarRenderer, realtime_renderer: AvatarRenderer | None, trt10_renderer: AvatarRenderer | None, fast_renderer: AvatarRenderer | None) -> AvatarRenderer:
    if method == "ditto_realtime_trt10":
        if trt10_renderer is None:
            raise HTTPException(status_code=409, detail="Ditto Realtime TensorRT 10 renderer가 아직 준비되지 않았습니다.")
        return trt10_renderer
    if method in {"ditto_realtime", "ditto_realtime_fast"}:
        if realtime_renderer is None:
            raise HTTPException(status_code=409, detail="Ditto Realtime renderer가 아직 배포되지 않았습니다.")
        if method == "ditto_realtime_fast" and isinstance(realtime_renderer, RemoteRenderer):
            return RemoteRenderer(realtime_renderer.base_url, realtime_renderer.shared_token, realtime_renderer.stream_prefix, render_profile="fast")
        return realtime_renderer
    if method == "fast":
        if fast_renderer is None:
            raise HTTPException(status_code=409, detail="Fast Live renderer가 아직 배포되지 않았습니다.")
        return fast_renderer
    return ditto_renderer


def _session_or_404(store: Store, session_id: str) -> SessionOut:
    try:
        return store.get_session(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from error


async def _read_limited_upload(upload: UploadFile, limit: int = 12 * 1024 * 1024) -> bytes:
    """Bound memory use before image decoding; UploadFile may not expose size."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="이미지는 12MB 이하로 업로드해 주세요.")
        chunks.append(chunk)
    return b"".join(chunks)


app = create_app()
