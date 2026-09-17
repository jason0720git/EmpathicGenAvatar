from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.conversation import AFFECT_TOOL, AFFECT_TOOL_NAME, OpenAIRealtimeConversation


@pytest.mark.parametrize('session_instruction', [None, '답변은 열 문장으로 길게 해주세요.'])
def test_spoken_limit_is_explicit_and_follows_custom_preferences(session_instruction):
    from app.conversation import SPOKEN_REPLY_LIMIT
    prompt = OpenAIRealtimeConversation._instructions('친절한 아바타', session_instruction)
    assert prompt.endswith(SPOKEN_REPLY_LIMIT)
    assert 'TWO SHORT sentences in total' in prompt
    assert 'ALL output items' in prompt
    assert 'Before every spoken reply, call' not in prompt


def test_realtime_affect_tool_is_a_two_field_contract() -> None:
    assert AFFECT_TOOL["name"] == AFFECT_TOOL_NAME
    parameters = AFFECT_TOOL["parameters"]
    assert parameters["required"] == ["emotion", "intensity"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["emotion"]["enum"] == [
        "angry", "disgust", "fear", "happy", "neutral", "sad", "surprise", "contempt",
    ]


def test_realtime_affect_parser_accepts_the_supported_contract() -> None:
    affect = OpenAIRealtimeConversation._parse_affect(json.dumps({"emotion": "sad", "intensity": 0.32}))

    assert affect.emotion == "sad"
    assert affect.intensity == 0.32


def test_realtime_affect_tool_phase_forces_one_function_call() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.events = iter([
                json.dumps({
                    "type": "response.function_call_arguments.done",
                    "name": AFFECT_TOOL_NAME,
                    "call_id": "call-affect-1",
                    "arguments": json.dumps({"emotion": "sad", "intensity": 0.4}),
                }),
                json.dumps({"type": "response.done"}),
            ])

        async def send(self, raw: str) -> None:
            self.sent.append(json.loads(raw))

        async def recv(self) -> str:
            return next(self.events)

    async def run() -> None:
        conversation = OpenAIRealtimeConversation("test-key", "test-model", Path("/tmp"))
        socket = FakeSocket()
        affect, call_id = await conversation._request_affect(socket)
        assert affect.emotion == "sad"
        assert affect.intensity == 0.4
        assert call_id == "call-affect-1"
        assert socket.sent[0]["type"] == "response.create"
        assert socket.sent[0]["response"] == {"tool_choice": {"type": "function", "name": AFFECT_TOOL_NAME}}

    asyncio.run(run())


@pytest.mark.parametrize("payload", [
    "not-json",
    json.dumps({"emotion": "anger", "intensity": 0.5}),
    json.dumps({"emotion": "happy", "intensity": 1.2}),
    json.dumps({"emotion": "happy"}),
])
def test_realtime_affect_parser_rejects_anything_outside_the_contract(payload: str) -> None:
    with pytest.raises(RuntimeError, match="invalid affect"):
        OpenAIRealtimeConversation._parse_affect(payload)
