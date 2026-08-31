from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.settings import Settings


def image_payload() -> bytes:
    image = Image.new("RGB", (640, 720), color=(125, 93, 142))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def client_for(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "test.db",
        allowed_origins=("http://testserver",),
    )
    return TestClient(create_app(settings))


def create_avatar(client: TestClient) -> dict:
    response = client.post(
        "/api/avatars",
        data={
            "name": "테스트 아바타",
            "persona": "차분한 안내자",
            "voice": "Calm Korean",
            "consent_likeness": "true",
            "consent_adult": "true",
            "consent_ai_label": "true",
        },
        files={"image": ("avatar.png", image_payload(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_avatar_lifecycle_and_turn_do_not_store_transcript(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        avatar = create_avatar(client)
        assert avatar["status"] == "ready"
        assert avatar["quality"]["width"] == 640
        assert client.get(avatar["source_url"]).status_code == 200

        session_response = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]})
        assert session_response.status_code == 201
        session = session_response.json()
        assert session["renderer_method"] == "ditto"
        turn_response = client.post(f"/api/live/sessions/{session['id']}/turns", json={"text": "안녕하세요"})
        assert turn_response.status_code == 200
        turn = turn_response.json()
        assert "AI 생성 아바타" in turn["assistant_text"]
        assert turn["renderer"]["mode"] == "preview"
        assert turn["visemes"]

        database = client.app.state.settings.database_path.read_bytes()
        assert "안녕하세요".encode() not in database
        assert client.delete(f"/api/avatars/{avatar['id']}").status_code == 204
        assert client.get(avatar["source_url"]).status_code == 404


def test_avatar_requires_all_explicit_consents(tmp_path):
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/avatars",
            data={
                "name": "테스트 아바타",
                "persona": "차분한 안내자",
                "voice": "Calm Korean",
                "consent_likeness": "true",
                "consent_adult": "false",
                "consent_ai_label": "true",
            },
            files={"image": ("avatar.png", image_payload(), "image/png")},
        )
        assert response.status_code == 422
        assert "동의" in response.json()["detail"]


def test_websocket_turn_and_interrupt(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(f"/ws/live/{session['id']}") as websocket:
            assert websocket.receive_json()["type"] == "room.state"
            websocket.send_json({"type": "turn", "text": "무엇을 할 수 있나요?"})
            assert websocket.receive_json()["type"] == "turn.started"
            assert websocket.receive_json()["type"] == "caption.final"
            assert websocket.receive_json()["type"] == "renderer"
            websocket.send_json({"type": "interrupt"})
            assert websocket.receive_json()["type"] == "turn.cancelled"


def test_turn_accepts_bounded_motion_plan(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        response = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={
                "text": "고개를 끄덕이며 답해 주세요.",
                "motion_plan": {
                    "expression": "concern",
                    "head": {"yaw_deg": 3, "pitch_deg": 0, "roll_deg": 0},
                    "gaze": {"x": 0, "y": 0},
                    "nod": {"start_ms": 300, "duration_ms": 460, "amplitude_deg": 5},
                },
            },
        )
        assert response.status_code == 200, response.text
        applied = response.json()["renderer"]["applied_motion"]
        assert applied["expression"] == "concern"
        assert applied["nod"]["amplitude_deg"] == 5


def test_fast_session_requires_deployed_fast_renderer(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post("/api/live/sessions", json={"avatar_id": avatar["id"], "renderer_method": "fast"})
        assert response.status_code == 409
        assert "Fast Live" in response.json()["detail"]


def test_realtime_session_requires_deployed_realtime_renderer(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post("/api/live/sessions", json={"avatar_id": avatar["id"], "renderer_method": "ditto_realtime"})
        assert response.status_code == 409
        assert "Ditto Realtime" in response.json()["detail"]


def test_realtime_fast_lane_requires_deployed_realtime_renderer(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post("/api/live/sessions", json={"avatar_id": avatar["id"], "renderer_method": "ditto_realtime_fast"})
        assert response.status_code == 409
        assert "Ditto Realtime" in response.json()["detail"]


def test_timing_telemetry_persists_no_conversation_content(tmp_path):
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/telemetry/turn",
            json={"turn_id": "turn-123", "event": "playback_started", "elapsed_ms": 1234, "details": {"buffer_target_ms": 250}},
        )
        assert response.status_code == 204
        saved = (tmp_path / "data" / "telemetry" / "turn-events.jsonl").read_text(encoding="utf-8")
        assert "turn-123" in saved
        assert "conversation" not in saved
