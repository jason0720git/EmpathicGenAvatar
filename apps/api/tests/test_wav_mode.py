from pathlib import Path
import wave
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import create_app
from app.settings import Settings
from app.models import RendererOut


def test_wav_mode_never_opens_or_calls_conversation_provider(tmp_path, monkeypatch):
    start = AsyncMock(side_effect=AssertionError('WAV must not open Realtime'))
    respond = AsyncMock(side_effect=AssertionError('WAV must not generate speech'))
    monkeypatch.setattr('app.conversation.SafeDemoConversation.start_session', start)
    monkeypatch.setattr('app.conversation.SafeDemoConversation.respond', respond)
    render = AsyncMock(return_value=([], RendererOut(mode='preview', status='ready')))
    monkeypatch.setattr('app.renderers.PreviewRenderer.render', render)
    settings = Settings(data_dir=tmp_path, database_path=tmp_path/'test.db', allowed_origins=())
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/live/sessions', json={'avatar_id':'demo-doyun','mode':'wav_test'})
        assert response.status_code == 201, response.text
        session = response.json()['id']
        assert response.json()['mode'] == 'wav_test'
        for emotion in ('angry','disgust','fear','happy','neutral','sad','surprise','contempt'):
            result = client.post(f'/api/live/sessions/{session}/turns',json={'text':'WAV','affect_override':{'emotion':emotion,'intensity':1}})
            assert result.status_code == 200, result.text
            kwargs = render.call_args.kwargs
            assert kwargs['motion_plan'].expression == emotion
            assert kwargs['audio_streaming'] is False
            assert Path(kwargs['audio_path']).name == 'reference.wav'
        assert client.post(f'/api/live/sessions/{session}/turns',json={'text':'no automatic emotion'}).status_code == 422
        assert client.get(f'/api/live/sessions/{session}/turns/test/caption').json()['done'] is True
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f'/ws/live/{session}'):
                pass
        assert error.value.code == 4403
        assert client.get('/api/test-audio').status_code == 200
        with wave.open(str(tmp_path/'test-audio/reference.wav')) as wav:
            assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate()) == (1,2,16000)
        (tmp_path/'test-audio/reference.wav').unlink()
        assert client.post(f'/api/live/sessions/{session}/turns',json={'text':'WAV','affect_override':{'emotion':'happy','intensity':1}}).status_code == 503
        start.assert_not_called()
        respond.assert_not_called()
