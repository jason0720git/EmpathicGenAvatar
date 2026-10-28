"""Gaussian API contracts, archive safety and cancellation with fake upstreams."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import gaussian_main
from app.gaussian_a2f import A2FFrame
from app.gaussian_main import create_gaussian_app
from app.gaussian_realtime import BehaviorIntent, RealtimeVoice
from app.gaussian_store import SessionLog, validate_asset_zip


def test_official_reference_stays_first_and_cannot_start_voice_session(tmp_path):
    from app.gaussian_store import AvatarFiles
    files = AvatarFiles(tmp_path)
    ref_id = '306000000000000000000001'
    files.save({'id': ref_id, 'name': 'Official 306', 'status': 'ready',
                'kind': 'reference_video', 'pinned': True, 'created_at': '2020-01-01'})
    (files.directory(ref_id) / 'reference.mp4').write_bytes(b'reference-test')
    with TestClient(create_gaussian_app(tmp_path, api_key='test')) as client:
        avatar = import_avatar(client)
        assert files.list()[0]['id'] == ref_id
        assert client.post('/gaussian-api/sessions', json={'avatar_id': ref_id}).status_code == 409
        assert client.get(f'/gaussian-api/avatars/{ref_id}/reference-video').content == b'reference-test'
        assert client.get(f"/gaussian-api/avatars/{avatar['id']}/reference-video").status_code == 404


@pytest.mark.parametrize('upstream_ready', [True, False])
def test_live_official_requires_renderer_and_records_driver(tmp_path, monkeypatch, upstream_ready):
    from app.gaussian_store import AvatarFiles
    from types import SimpleNamespace
    class RendererClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            assert url == 'http://127.0.0.1:8041/health'
            if not upstream_ready: raise ConnectionError('offline')
            return SimpleNamespace(raise_for_status=lambda: None)
    monkeypatch.setattr(gaussian_main.httpx, 'AsyncClient', lambda **kwargs: RendererClient())
    avatar_id = '306000000000000000000001'
    AvatarFiles(tmp_path).save({'id': avatar_id, 'name': 'Official live', 'status': 'ready',
                               'kind': 'official_live', 'created_at': '2026-09-29'})
    with TestClient(create_gaussian_app(tmp_path, api_key='test')) as client:
        result = client.post('/gaussian-api/sessions', json={'avatar_id': avatar_id})
        assert result.status_code == (200 if upstream_ready else 503)
        if upstream_ready:
            config = json.loads((tmp_path/'sessions'/result.json()['id']/'session.json').read_text(encoding='utf-8'))
            assert config['render_driver'] == 'a2f-arkit-to-flame-v1'
            assert config['avatar_engine'] == 'official_live'


def avatar_zip(extra: tuple[str, bytes] | None = None) -> bytes:
    # Structurally valid, tiny glTF fixture; rendering is tested separately.
    doc = json.dumps({"asset": {"version": "2.0"}, "nodes": [], "scenes": [{"nodes": []}], "scene": 0}).encode()
    doc += b" " * ((-len(doc)) % 4)
    glb = struct.pack("<4sII", b"glTF", 2, 20 + len(doc)) + struct.pack("<I4s", len(doc), b"JSON") + doc
    ply = b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("offset.ply", ply), ("skin.glb", glb), ("animation.glb", glb)):
            entry = zipfile.ZipInfo(name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
        if extra:
            archive.writestr(*extra)
    return output.getvalue()


def import_avatar(client: TestClient) -> dict:
    response = client.post("/gaussian-api/avatars/import", files={"file": ("avatar.zip", avatar_zip(), "application/zip")})
    assert response.status_code == 200, response.text
    return response.json()


def read_event(ws, event_type: str) -> dict:
    for _ in range(100):
        message = ws.receive_json()
        if message["type"] == event_type:
            return message
    raise AssertionError(f"Did not receive {event_type}")


def test_session_and_downloadable_logs_survive_restart_without_exposing_api_key(tmp_path):
    secret = "sk-test-only-credential-for-redaction"
    with TestClient(create_gaussian_app(tmp_path, api_key=secret)) as client:
        avatar = import_avatar(client)
        assert avatar["status"] == "ready"
        assert client.get(avatar["asset_url"]).content == avatar_zip()
        created = client.post("/gaussian-api/sessions", json={"avatar_id": avatar["id"], "instructions": "짧게 한국어로 답해주세요."})
        assert created.status_code == 200
        session = created.json()
        feedback = client.post(f"/gaussian-api/sessions/{session['id']}/feedback", json={"rating": 3, "comment": "표정이 약합니다."})
        assert feedback.status_code == 200
        log_path = f"/gaussian-api/sessions/{session['id']}/logs.zip"
        contents = client.get(log_path)
        assert contents.status_code == 200
        with zipfile.ZipFile(io.BytesIO(contents.content)) as archive:
            assert {"session.json", "events.jsonl", "feedback.jsonl", "audio-format.txt"} <= set(archive.namelist())
            assert secret.encode() not in b"".join(archive.read(name) for name in archive.namelist())
            config = json.loads(archive.read("session.json"))
            assert config["avatar_id"] == avatar["id"]
            assert config["controller"] == "rule_based_sobia_inspired_v1"
    # Retrieval after process restart must not create a second session event.
    old = (tmp_path / "sessions" / session["id"] / "events.jsonl").read_bytes()
    with TestClient(create_gaussian_app(tmp_path, api_key="")) as restarted:
        assert restarted.get(log_path).status_code == 200
    assert (tmp_path / "sessions" / session["id"] / "events.jsonl").read_bytes() == old


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "dir/../../outside", r"dir\..\..\outside"])
def test_asset_zip_rejects_path_escape(tmp_path, name):
    with TestClient(create_gaussian_app(tmp_path, api_key="")) as client:
        response = client.post("/gaussian-api/avatars/import", files={"file": ("bad.zip", avatar_zip((name, b"x")), "application/zip")})
        assert response.status_code == 400
        assert list((tmp_path / "avatars").iterdir()) == []


def test_asset_zip_rejects_symlink_and_missing_required_files():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        member = zipfile.ZipInfo("skin.glb")
        member.create_system = 3
        member.external_attr = 0o120777 << 16
        archive.writestr(member, "../../secret")
    with pytest.raises(ValueError, match="symlink"):
        validate_asset_zip(output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("offset.ply", "x")
    with pytest.raises(ValueError, match="requires"):
        validate_asset_zip(output.getvalue())


@pytest.mark.parametrize("mutation", ["junk_glb", "wrong_glb_size", "junk_ply", "duplicate", "split_folders", "too_many_files"])
def test_asset_zip_rejects_unusable_or_ambiguous_bundles(mutation):
    with zipfile.ZipFile(io.BytesIO(avatar_zip())) as original:
        entries = [(item.filename, original.read(item)) for item in original.infolist()]
    if mutation == "junk_glb":
        entries[1] = ("skin.glb", b"not a GLB file")
    elif mutation == "wrong_glb_size":
        name, raw = entries[1]
        entries[1] = (name, raw[:8] + struct.pack("<I", len(raw) + 100) + raw[12:])
    elif mutation == "junk_ply":
        entries[0] = ("offset.ply", b"not a Gaussian file")
    elif mutation == "duplicate":
        entries.append(("extra/skin.glb", entries[1][1]))
    elif mutation == "split_folders":
        entries[1] = ("other/skin.glb", entries[1][1])
    else:
        entries.extend((f"extra-{index}.txt", b"x") for index in range(65))
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as out:
        for name, data in entries:
            out.writestr(name, data)
    with pytest.raises(ValueError):
        validate_asset_zip(target.getvalue())


def test_origin_guard_and_missing_ids(tmp_path):
    with TestClient(create_gaussian_app(tmp_path, api_key="")) as client:
        assert client.post("/gaussian-api/sessions", json={"avatar_id": "a" * 24}, headers={"origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/gaussian-api/sessions", json={"avatar_id": "a" * 24}).status_code == 404
        assert client.get("/gaussian-api/sessions/not-a-valid-id/logs.zip").status_code == 404
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/gaussian-ws/" + "a" * 24, headers={"origin": "https://untrusted.example"}):
                pass
        assert rejected.value.code == 4403


def test_session_logs_redact_nested_credentials_and_keep_raw_audio_separate(tmp_path):
    log = SessionLog(tmp_path, "a" * 24, {"authorization": "Bearer abc", "config": {"api_key": "secret"}})
    log.record("upstream", {"details": {"audio": "A" * 1200, "access_token": "token", "message": "value sk-secret-secret-secret"}})
    log.audio("b" * 24, "output", b"\x00\x01" * 10)
    with zipfile.ZipFile(io.BytesIO(log.archive())) as archive:
        events = archive.read("events.jsonl").decode()
        assert "Bearer abc" not in events
        assert "sk-secret-secret-secret" not in events
        assert "A" * 100 not in events
        assert '"audio_base64_chars": 1200' in events
        assert archive.read("b" * 24 + "-output-24000.pcm") == b"\x00\x01" * 10


def test_websocket_interrupt_cancels_upstream_and_records_turn(tmp_path, monkeypatch):
    instances = []

    class FakeVoice(RealtimeVoice):
        def __init__(self, *args):
            super().__init__(*args)
            self.cancelled = False
            self.closed = False
            instances.append(self)

        async def turn(self, text, audio, observation, on_intent, on_audio, on_transcript):
            try:
                await on_intent(BehaviorIntent(emotion="sad", intensity=.4, intent="supportive", nod=True))
                await on_transcript("user", text, True)
                await on_audio(b"\x01\x00" * 2400)
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

        async def close(self):
            self.closed = True

    class FakeA2F:
        def __init__(self, *_args, **_kwargs):
            pass

        async def stream(self, chunks):
            timestamp = 0.
            async for _ in chunks:
                yield A2FFrame(timestamp, {"jawOpen": .3})
                timestamp += .1

    monkeypatch.setattr(gaussian_main, "RealtimeVoice", FakeVoice)
    monkeypatch.setattr(gaussian_main, "A2FClient", FakeA2F)
    with TestClient(create_gaussian_app(tmp_path, api_key="configured-test-value")) as client:
        avatar = import_avatar(client)
        session = client.post("/gaussian-api/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(session["ws_url"]) as ws:
            assert ws.receive_json()["type"] == "session.ready"
            ws.send_json({"type": "input.text", "text": "오늘은 슬퍼요."})
            audio = read_event(ws, "audio.chunk")
            assert audio["sample_rate"] == 24000
            assert audio["pts_ms"] == 0
            assert base64.b64decode(audio["pcm_base64"]) == b"\x01\x00" * 2400
            ws.send_json({"type": "interrupt"})
            cancelled = read_event(ws, "turn.cancelled")
            assert cancelled["turn_id"] == audio["turn_id"]
            assert instances[0].cancelled and instances[0].closed
            ws.send_json({"type": "input.audio", "pcm_base64": "invalid/base64!!!"})
            assert "message" in read_event(ws, "error")
            ws.send_json(["not", "an", "object"])
            assert "object" in read_event(ws, "error")["message"]
            ws.send_text("invalid JSON")
            assert "message" in read_event(ws, "error")
            ws.send_json({"type": "control", "emotion": "sad", "intensity": .6})
            assert read_event(ws, "behavior")["manual"]
        logs = (tmp_path / "sessions" / session["id"] / "events.jsonl").read_text(encoding="utf-8")
        assert '"event": "interrupt"' in logs
        assert '"event": "turn.cancelled"' in logs
        assert '"event": "command.error"' in logs


def test_websocket_rejects_second_live_owner(tmp_path):
    with TestClient(create_gaussian_app(tmp_path, api_key="")) as client:
        avatar = import_avatar(client)
        session = client.post("/gaussian-api/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(session["ws_url"]) as first:
            assert first.receive_json()["type"] == "session.ready"
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(session["ws_url"]):
                    pass
            assert error.value.code == 4409


def test_realtime_does_not_commit_unheard_assistant_history(monkeypatch):
    async def run():
        voice = RealtimeVoice("not-sent", "test-model", "marin", "", lambda *_args: None)
        events = iter([
            {"type": "response.function_call_arguments.done", "name": "set_avatar_behavior", "call_id": "tool1",
             "arguments": json.dumps({"emotion": "sad", "intensity": .4, "intent": "supportive", "nod": False})},
            {"type": "response.done", "response": {"status": "completed"}},
            {"type": "response.created", "response": {"id": "response1"}},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(bytes(4800)).decode()},
            {"type": "response.output_audio_transcript.done", "transcript": "마음이 무거우셨겠어요."},
            {"type": "response.done", "response": {"status": "completed"}},
        ])
        sent = []
        async def start():
            pass
        async def send(event):
            sent.append(event)
        async def receive():
            return next(events)
        async def noop(*_args):
            pass
        monkeypatch.setattr(voice, "start", start)
        monkeypatch.setattr(voice, "send", send)
        monkeypatch.setattr(voice, "receive", receive)
        await voice.turn("슬퍼요.", None, "", noop, noop, noop)
        assert voice.history == []
        assert voice.pending_reply[-1]["role"] == "assistant"
        voice.discard_playback()
        assert voice.history == [{"role": "user", "text": "슬퍼요."}]
        assert voice.pending_reply is None
        voice.pending_reply = [{"role": "user", "text": "고마워요."}, {"role": "assistant", "text": "함께 이야기해요."}]
        voice.commit_playback()
        assert voice.history[-1] == {"role": "assistant", "text": "함께 이야기해요."}
        voice.commit_playback()
        assert len(voice.history) == 3  # duplicated telemetry is idempotent
        assert sent[1]["response"]["tool_choice"]["name"] == "set_avatar_behavior"
    asyncio.run(run())


def test_room_keeps_speaking_until_matching_playback_complete(tmp_path, monkeypatch):
    class CompletedVoice(RealtimeVoice):
        async def turn(self, text, audio, observation, on_intent, on_audio, on_transcript):
            chosen = BehaviorIntent(emotion="happy", intensity=.4, intent="encouraging")
            await on_intent(chosen)
            await on_audio(bytes(48000))
            self.pending_reply = [{"role": "user", "text": text}, {"role": "assistant", "text": "응원해요."}]
            return {"text": "응원해요.", "user_text": text, "samples": 24000, "intent": chosen.model_dump()}

    class FakeA2F:
        def __init__(self, *_args, **_kwargs):
            pass
        async def stream(self, chunks):
            async for _ in chunks:
                yield A2FFrame(0., {"jawOpen": .2})
                yield A2FFrame(1., {"jawOpen": .1})

    monkeypatch.setattr(gaussian_main, "RealtimeVoice", CompletedVoice)
    monkeypatch.setattr(gaussian_main, "A2FClient", FakeA2F)
    with TestClient(create_gaussian_app(tmp_path, api_key="configured-test-value")) as client:
        avatar = import_avatar(client)
        session = client.post("/gaussian-api/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(session["ws_url"]) as ws:
            read_event(ws, "session.ready")
            ws.send_json({"type": "input.text", "text": "고마워요."})
            turn = read_event(ws, "turn.done")
            # Force a command roundtrip after generation; no idle/ready may
            # overwrite the animation still queued on the browser audio clock.
            ws.send_json({"type": "control", "emotion": "neutral", "intensity": .3})
            while True:
                packet = ws.receive_json()
                assert not (packet["type"] == "state" and packet["state"] == "ready")
                assert not (packet["type"] == "animation.frame" and packet["turn_id"] == "idle")
                if packet["type"] == "behavior":
                    break
            ws.send_json({"type": "telemetry", "event": "playback.complete", "turn_id": turn["turn_id"]})
            assert read_event(ws, "state")["state"] == "ready"
            assert read_event(ws, "animation.frame")["turn_id"] == "idle"


def test_a2f_failure_with_full_queue_cannot_deadlock_end_of_audio(tmp_path, monkeypatch):
    async def run():
        fail = asyncio.Event()
        emitted = []
        class FakeSocket:
            async def send_json(self, message):
                emitted.append(message)
        class BurstVoice(RealtimeVoice):
            async def turn(self, text, audio, observation, on_intent, on_audio, on_transcript):
                await on_intent(BehaviorIntent())
                for _ in range(256):
                    await on_audio(bytes(160))
                fail.set()
                return {"text": "test"}
        class FailedA2F:
            def __init__(self, *_args, **_kwargs):
                pass
            async def stream(self, chunks):
                await fail.wait()
                raise RuntimeError("simulated A2F failure")
                yield  # make this an async generator without consuming input
        monkeypatch.setattr(gaussian_main, "A2FClient", FailedA2F)
        config = {"id": "a" * 24, "model": "test", "voice": "marin", "instructions": ""}
        log = SessionLog(tmp_path, config["id"], config)
        room = gaussian_main.GaussianRoom(FakeSocket(), config, log, "test", "not-used")
        room.voice = BurstVoice("test", "test", "marin", "", lambda *_args: None)
        room.turn_id = "b" * 24
        try:
            await asyncio.wait_for(room.respond(room.turn_id, "test", None), timeout=1.)
            assert any(event["type"] == "error" and "simulated A2F" in event["message"] for event in emitted)
            assert room.awaiting_playback is None
        finally:
            await room.close()
    asyncio.run(run())


def test_interruption_during_generation_keeps_accepted_user_text(monkeypatch):
    async def run():
        voice = RealtimeVoice("not-sent", "test", "marin", "", lambda *_args: None)
        accepted = asyncio.Event()
        async def noop(*_args):
            pass
        async def transcription(role, text, final):
            if role == "user":
                accepted.set()
        async def receive():
            await asyncio.Event().wait()
        monkeypatch.setattr(voice, "start", noop)
        monkeypatch.setattr(voice, "send", noop)
        monkeypatch.setattr(voice, "receive", receive)
        task = asyncio.create_task(voice.turn("이 이야기를 기억해주세요.", None, "", noop, noop, transcription))
        await asyncio.wait_for(accepted.wait(), .5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        voice.discard_playback()
        assert voice.history == [{"role": "user", "text": "이 이야기를 기억해주세요."}]
    asyncio.run(run())


def test_late_previous_audio_transcript_does_not_overwrite_current_user(monkeypatch):
    async def run():
        voice = RealtimeVoice("not-sent", "test", "marin", "", lambda *_args: None)
        events = iter([
            {"type": "input_audio_buffer.committed", "item_id": "current-item"},
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "current-item", "transcript": "현재 질문입니다."},
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "previous-item", "transcript": "지난 질문입니다."},
            {"type": "response.function_call_arguments.done", "name": "set_avatar_behavior", "call_id": "tool1",
             "arguments": json.dumps({"emotion": "neutral", "intensity": .2, "intent": "explaining", "nod": False})},
            {"type": "response.done", "response": {"status": "completed"}},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(bytes(4800)).decode()},
            {"type": "response.output_audio_transcript.done", "transcript": "답변입니다."},
            {"type": "response.done", "response": {"status": "completed"}},
        ])
        async def noop(*_args):
            pass
        async def receive():
            return next(events)
        monkeypatch.setattr(voice, "start", noop)
        monkeypatch.setattr(voice, "send", noop)
        monkeypatch.setattr(voice, "receive", receive)
        result = await voice.turn(None, bytes(4800), "", noop, noop, noop)
        assert result["user_text"] == "현재 질문입니다."
        voice.commit_playback()
        assert voice.history[0]["text"] == "현재 질문입니다."
    asyncio.run(run())


def test_interrupt_before_audio_transcription_does_not_invent_user_history(monkeypatch):
    async def run():
        voice = RealtimeVoice("not-sent", "test", "marin", "", lambda *_args: None)
        waiting = asyncio.Event()
        async def noop(*_args):
            pass
        async def receive():
            waiting.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(voice, "start", noop)
        monkeypatch.setattr(voice, "send", noop)
        monkeypatch.setattr(voice, "receive", receive)
        task = asyncio.create_task(voice.turn(None, bytes(4800), "", noop, noop, noop))
        await asyncio.wait_for(waiting.wait(), .5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        voice.discard_playback()
        assert voice.history == []
        assert voice.pending_reply is None
    asyncio.run(run())


def test_wav_replay_without_api_key_preserves_audio_and_selected_emotion(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("WAV test must never call Realtime")
    monkeypatch.setattr(RealtimeVoice, "turn", forbidden)
    received = bytearray()
    class FakeA2F:
        def __init__(self, *args, **kwargs): pass
        async def stream(self, chunks):
            async for chunk in chunks:
                received.extend(chunk)
                yield A2FFrame(time_seconds=.5, coefficients={"jawOpen":.4})
    monkeypatch.setattr(gaussian_main, "A2FClient", FakeA2F)
    pcm = bytes([1,2])*6000
    with TestClient(create_gaussian_app(tmp_path, api_key="")) as client:
        avatar = import_avatar(client)
        session = client.post('/gaussian-api/sessions',json={"avatar_id":avatar['id']}).json()
        with client.websocket_connect(session['ws_url']) as ws:
            read_event(ws,'session.ready')
            ws.send_json({'type':'input.start'})
            ws.send_json({'type':'input.audio','pcm_base64':base64.b64encode(pcm).decode()})
            ws.send_json({'type':'test.commit','filename':'fixture.wav','control':{'emotion':'sad','intensity':.8}})
            audio = bytearray(); frames=[]
            for _ in range(100):
                event=ws.receive_json()
                assert event['type'] != 'error', event
                if event['type']=='audio.chunk': audio.extend(base64.b64decode(event['pcm_base64']))
                if event['type']=='animation.frame' and event['turn_id']!='idle': frames.append(event)
                if event['type']=='turn.done': break
            else: raise AssertionError('WAV test did not finish')
            assert audio == pcm and received == pcm
            assert frames and frames[0]['behavior']['emotion']=='sad'
            assert frames[0]['weights']['mouthFrownLeft'] >= .28
            assert frames[0]['weights']['jawOpen'] == .4
