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


def test_expression_feedback_and_correlated_report(tmp_path):
    with client_for(tmp_path, empathic_debug_log=True) as client:
        avatar = create_avatar(client)
        session = client.post('/api/live/sessions', json={'avatar_id': avatar['id']}).json()
        for mode in ('off', 'native', 'legacy', 'speech_safe'):
            turn_id = 'feedback-test-' + mode
            response = client.post(f"/api/live/sessions/{session['id']}/turns", json={
                'text':'hello', 'client_turn_id':turn_id, 'expression_render_mode':mode,
                'affect_override':{'emotion':'happy','intensity':1}})
            assert response.status_code == 200, response.text
            assert response.json()['renderer']['applied_motion']['expression_render_mode'] == mode
            payload = {'session_id':session['id'], 'turn_id':turn_id, 'issue':'mouth_blur', 'severity':2, 'at_ms':1200, 'note':'synthetic test'}
            assert client.post('/api/debug/expression-feedback',json=payload).status_code == 201
            report = client.get('/api/debug/expression-turn/' + turn_id).json()
            assert len(report['expression-feedback']) == 1
            assert report['expression-feedback'][0]['note'] == 'synthetic test'
            assert report['empathic-decisions']
            assert report['media_included'] is False
        assert client.post('/api/debug/expression-feedback',json={**payload,'severity':4}).status_code == 422
        assert client.post('/api/debug/expression-feedback',json={**payload,'note':'x'*1001}).status_code == 422
        assert client.post(f"/api/live/sessions/{session['id']}/turns",json={'text':'test','expression_render_mode':'invalid'}).status_code == 422


def test_expression_debug_is_disabled_by_default(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get('/api/debug/expression-turn/test').status_code == 403
        assert client.post('/api/debug/expression-feedback',json={'session_id':'test','turn_id':'test','issue':'good'}).status_code == 403


def client_for(tmp_path, *, empathic_debug_log: bool = False):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "test.db",
        allowed_origins=("http://testserver",),
        empathic_debug_log=empathic_debug_log,
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
                    "expression": "sad",
                    "intensity": 0.5,
                    "head": {"yaw_deg": 3, "pitch_deg": 0, "roll_deg": 0},
                    "gaze": {"x": 0, "y": 0},
                    "nod": {"start_ms": 300, "duration_ms": 460, "amplitude_deg": 5},
                },
                "motion_override": True,
            },
        )
        assert response.status_code == 200, response.text
        applied = response.json()["renderer"]["applied_motion"]
        assert applied["expression"] == "sad"
        assert applied["nod"]["amplitude_deg"] == 5


def test_demo_backend_uses_declared_neutral_fallback_without_text_classification(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()

        serious = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={"text": "요즘 너무 불안하고 힘들어요."},
        )
        assert serious.status_code == 200, serious.text
        assert serious.json()["renderer"]["applied_motion"]["expression"] == "neutral"

        override = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={
                "text": "요즘 너무 불안하고 힘들어요.",
                "motion_plan": {
                    "expression": "sad",
                    "intensity": 0.5,
                    "head": {"yaw_deg": 0, "pitch_deg": 0, "roll_deg": 0},
                    "gaze": {"x": 0, "y": 0},
                },
                "motion_override": True,
            },
        )
        assert override.status_code == 200, override.text
        assert override.json()["renderer"]["applied_motion"]["expression"] == "sad"


def test_manual_affect_override_applies_without_a_motion_plan(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        response = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={"text": "일반 답변도 표정 테스트로 렌더링합니다.", "affect_override": {"emotion": "surprise", "intensity": 0.75}},
        )

        assert response.status_code == 200, response.text
        applied = response.json()["renderer"]["applied_motion"]
        assert applied["expression"] == "surprise"
        assert applied["intensity"] == 0.75


def test_opt_in_empathic_debug_log_records_decision_evidence(tmp_path):
    with client_for(tmp_path, empathic_debug_log=True) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        response = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={
                "text": "어제 너무 슬펐어요.", "client_turn_id": "sadness-turn",
                "motion_plan": {"expression": "sad", "intensity": 0.5}, "motion_override": True,
            },
        )

        assert response.status_code == 200, response.text
        applied_motion = response.json()["renderer"]["applied_motion"]
        assert applied_motion["expression"] == "sad"
        assert applied_motion["intensity"] == 0.5
        debug = client.get("/api/debug/empathic-decisions?limit=10")
        assert debug.status_code == 200
        records = debug.json()["records"]
        decision = next(record for record in records if record["event"] == "behavior.decision")
        rendered = next(record for record in records if record["event"] == "renderer.completed")
        assert decision["turn_id"] == "sadness-turn"
        assert decision["user_text"] == "어제 너무 슬펐어요."
        assert decision["behavior"]["motion_plan"]["expression"] == "sad"
        assert decision["behavior"]["motion_plan"]["intensity"] == 0.5
        assert decision["behavior"]["source"] == "manual_override"
        assert rendered["renderer"]["applied_motion"]["expression"] == "sad"


def test_websocket_demo_turn_uses_the_same_neutral_fallback(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(f"/ws/live/{session['id']}") as websocket:
            assert websocket.receive_json()["type"] == "room.state"
            websocket.send_json({"type": "turn", "text": "안녕하세요"})
            assert websocket.receive_json()["type"] == "turn.started"
            assert websocket.receive_json()["type"] == "caption.final"
            renderer = websocket.receive_json()
            assert renderer["type"] == "renderer"
            assert renderer["renderer"]["applied_motion"]["expression"] == "neutral"


def test_websocket_explicit_neutral_override_has_rest_parity(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        with client.websocket_connect(f"/ws/live/{session['id']}") as websocket:
            assert websocket.receive_json()["type"] == "room.state"
            websocket.send_json({
                "type": "turn",
                "text": "요즘 너무 불안하고 힘들어요.",
                "motion_plan": {
                    "expression": "neutral",
                    "head": {"yaw_deg": 0, "pitch_deg": 0, "roll_deg": 0},
                    "gaze": {"x": 0, "y": 0},
                },
                "motion_override": True,
            })
            assert websocket.receive_json()["type"] == "turn.started"
            assert websocket.receive_json()["type"] == "caption.final"
            renderer = websocket.receive_json()
            assert renderer["renderer"]["applied_motion"]["expression"] == "neutral"


def test_motion_override_requires_an_explicit_plan(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        session = client.post("/api/live/sessions", json={"avatar_id": avatar["id"]}).json()
        response = client.post(
            f"/api/live/sessions/{session['id']}/turns",
            json={"text": "안녕하세요", "motion_override": True},
        )

        assert response.status_code == 422
        assert "motion_override requires motion_plan" in response.text


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


def test_trt10_realtime_session_requires_deployed_trt10_renderer(tmp_path):
    with client_for(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post("/api/live/sessions", json={"avatar_id": avatar["id"], "renderer_method": "ditto_realtime_trt10"})
        assert response.status_code == 409
        assert "TensorRT 10" in response.json()["detail"]


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
