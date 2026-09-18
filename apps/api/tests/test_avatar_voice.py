import asyncio
import json

from app.conversation import OpenAIRealtimeConversation
from app.store import Store


def test_doyun_voice_seed_and_existing_database_migration(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    assert store.get_avatar('demo-doyun').voice == 'echo'
    with store._connect() as connection:
        connection.execute("UPDATE avatars SET voice = 'Calm Korean' WHERE id = 'demo-doyun'")
    store.initialize()
    assert store.get_avatar('demo-doyun').voice == 'echo'
    assert store.get_avatar('demo-seoyeon').voice == 'Calm Korean'


def test_realtime_uses_selected_voice_and_preserves_existing_session(monkeypatch, tmp_path):
    class Socket:
        def __init__(self):
            self.sent = []

        async def send(self, message):
            self.sent.append(json.loads(message))

        async def close(self):
            pass

    async def connect(*args, **kwargs):
        return Socket()

    monkeypatch.setattr('app.conversation.connect', connect)

    async def check():
        provider = OpenAIRealtimeConversation('test', 'test', tmp_path)
        await provider.start_session('doyun', persona='test', voice='echo')
        entry = provider._sessions['doyun']
        assert entry.socket.sent[0]['session']['audio']['output']['voice'] == 'echo'
        assert entry.voice == 'echo'
        await provider.start_session('doyun', persona='test')
        assert len(entry.socket.sent) == 1
        await provider.start_session('other', persona='test', voice='Calm Korean')
        assert provider._sessions['other'].voice == 'marin'
        await provider.close_session('doyun')
        await provider.start_session('doyun', persona='test', voice='echo')
        assert provider._sessions['doyun'].voice == 'echo'

    asyncio.run(check())
