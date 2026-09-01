from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationResponse:
    """Response text plus an optional authoritative audio asset for Ditto."""

    text: str
    audio_path: str | None = None
    audio_streaming: bool = False
    voice: str | None = None


class ConversationProvider:
    name = "demo"

    async def respond(self, *, persona: str, user_text: str, session_instruction: str | None = None, session_id: str | None = None, turn_id: str | None = None) -> ConversationResponse:
        raise NotImplementedError

    async def start_session(self, session_id: str, *, persona: str, session_instruction: str | None = None) -> None:
        return None

    async def close_session(self, session_id: str) -> None:
        return None

    def caption_status(self, session_id: str, turn_id: str) -> tuple[str, bool] | None:
        """Return the latest streamed caption without retaining it persistently."""
        return None


class SafeDemoConversation(ConversationProvider):
    """A deterministic fallback with alternating Korean/English demo turns."""

    def __init__(self) -> None:
        self._reply_count = 0

    def _next_language(self) -> str:
        language = "ko" if self._reply_count % 2 == 0 else "en"
        self._reply_count += 1
        return language

    async def respond(self, *, persona: str, user_text: str, session_instruction: str | None = None, session_id: str | None = None, turn_id: str | None = None) -> ConversationResponse:
        text = user_text.strip()
        lowered = text.lower()
        if any(word in lowered for word in ("미성년", "아동", "아이 사진", "유명인 사칭", "딥페이크 범죄")):
            return ConversationResponse("그 용도는 도와드릴 수 없어요. 이 공간에서는 권리를 보유한 성인 인물의 private 아바타만 다루며, 사칭이나 위해 목적의 생성은 지원하지 않습니다.")
        language = self._next_language()
        if any(word in lowered for word in ("안녕", "hello", "반가")):
            if language == "ko":
                return ConversationResponse(f"안녕하세요. 저는 AI 생성 아바타이며, {persona}라는 역할로 대화하고 있어요. 한국어 립싱크를 확인하기 위해 자연스럽게 답변하고 있습니다.")
            return ConversationResponse(f"Hello. I am an AI-generated avatar speaking as {persona}. This English response is for comparing real-time lip sync and pacing.")
        if any(word in lowered for word in ("힘들", "불안", "기분", "걱정")):
            if language == "ko":
                return ConversationResponse("그렇게 느끼고 계셨군요. 바로 해결하려 하기보다 지금 가장 무겁게 느껴지는 지점을 하나만 골라 이야기해 볼까요? 필요한 속도에 맞춰 함께 생각하겠습니다.")
            return ConversationResponse("That sounds difficult. Rather than solving everything at once, could we identify the part that feels heaviest right now and take one small step?")
        if "?" in text or "어떻" in lowered or "무엇" in lowered:
            if language == "ko":
                return ConversationResponse(f"좋은 질문이에요. {persona}의 관점에서 보면, 먼저 목표와 현재 제약을 나눈 뒤 가장 작은 다음 행동을 정하는 편이 좋습니다. 지금 가장 중요하게 두는 기준은 무엇인가요?")
            return ConversationResponse(f"That is a good question. From the perspective of {persona}, separate the goal from the constraints first, then choose the smallest useful next action. What matters most to you?")
        subject = re.sub(r"[.?!。]+$", "", text)
        if language == "ko":
            return ConversationResponse(f"말씀해 주셔서 고마워요. “{subject[:72]}”라는 부분을 들었어요. 핵심을 놓치지 않도록, 그 상황에서 바꾸고 싶은 결과를 먼저 함께 정해 볼까요?")
        return ConversationResponse(f"Thank you for sharing that. I heard the part about “{subject[:72]}.” To keep the focus clear, what outcome would you most like to change?")


class OllamaConversation(ConversationProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def respond(self, *, persona: str, user_text: str, session_instruction: str | None = None, session_id: str | None = None, turn_id: str | None = None) -> ConversationResponse:
        system = (
            "You are an explicitly AI-generated private avatar in a live conversation. "
            "Answer in the user's language, concisely and warmly. Never claim to be human. "
            "Do not help impersonation, misuse of likenesses, or sexual content involving minors. "
            f"Persona: {persona}"
        )
        payload = {"model": self.model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}]}
        async with httpx.AsyncClient(timeout=18) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        content = response.json().get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Ollama returned an empty response")
        return ConversationResponse(content)


class OpenAIRealtimeConversation(ConversationProvider):
    """Server-side Realtime Marin PCM bridge for Ditto's shared audio clock."""

    name = "openai-realtime"

    @dataclass
    class _Session:
        socket: object
        lock: asyncio.Lock = field(default_factory=asyncio.Lock)
        connected_ms: float = 0.0

    def __init__(self, api_key: str, model: str, data_dir: Path) -> None:
        self.api_key = api_key
        self.model = model
        # `/data/audio` is owned by the GPU worker because it also contains
        # legacy local-TTS assets.  Keep Realtime inputs in an API-owned
        # sibling so a non-root control-plane process can write safely.
        self.audio_dir = data_dir / "realtime-audio"
        self._sessions: dict[str, OpenAIRealtimeConversation._Session] = {}
        # Captions exist only in this process while the browser needs updates.
        # They are cleared when the live room is closed and are never written to
        # the database or telemetry log.
        self._captions: dict[str, tuple[str, str, bool]] = {}

    @staticmethod
    def _instructions(persona: str, session_instruction: str | None) -> str:
        base = (
            "You are an explicitly AI-generated private avatar in a live conversation. "
            "Reply in the user's language, warmly and concisely (normally one or two sentences). "
            "Never claim to be human. Do not assist impersonation, likeness misuse, "
            "or sexual content involving minors. "
            f"Persona: {persona}"
        )
        return f"{base}\n\nSession instruction (follow when it does not conflict with safety):\n{session_instruction.strip()}" if session_instruction and session_instruction.strip() else base

    async def start_session(self, session_id: str, *, persona: str, session_instruction: str | None = None) -> None:
        if session_id in self._sessions:
            return
        started = time.perf_counter()
        socket = await connect(
            f"wss://api.openai.com/v1/realtime?model={self.model}",
            additional_headers={"Authorization": f"Bearer {self.api_key}"}, open_timeout=12, close_timeout=3,
        )
        await socket.send(json.dumps({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["audio"], "instructions": self._instructions(persona, session_instruction),
            "audio": {"output": {"voice": "marin", "format": {"type": "audio/pcm", "rate": 24000}}},
        }}))
        elapsed = (time.perf_counter() - started) * 1000
        self._sessions[session_id] = self._Session(socket=socket, connected_ms=elapsed)
        print("OpenAI Realtime session connected: " + json.dumps({"session_id": session_id, "connect_ms": round(elapsed, 1), "model": self.model, "voice": "marin"}), flush=True)

    async def close_session(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        self._captions = {
            key: state for key, state in self._captions.items() if state[0] != session_id
        }
        if entry is not None:
            await entry.socket.close()  # type: ignore[union-attr]

    def caption_status(self, session_id: str, turn_id: str) -> tuple[str, bool] | None:
        state = self._captions.get(turn_id)
        if state is None or state[0] != session_id:
            return None
        return state[1], state[2]

    async def respond(self, *, persona: str, user_text: str, session_instruction: str | None = None, session_id: str | None = None, turn_id: str | None = None) -> ConversationResponse:
        started = time.perf_counter()
        key = session_id or f"one-turn-{uuid.uuid4().hex}"
        caption_key = turn_id or f"caption-{uuid.uuid4().hex}"
        self._captions[caption_key] = (key, "", False)
        if key not in self._sessions:
            await self.start_session(key, persona=persona, session_instruction=session_instruction)
        entry = self._sessions[key]
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        filename = f"realtime-marin-{uuid.uuid4().hex}.pcm"
        audio_path = self.audio_dir / filename
        done_path = audio_path.with_suffix(".done")
        ready: asyncio.Future[ConversationResponse] = asyncio.get_running_loop().create_future()

        async def produce() -> None:
            fragments: list[str] = []
            completed_text = ""
            connected_ms: float | None = None
            first_event_ms: float | None = None
            first_text_ms: float | None = None
            first_audio_ms: float | None = None
            audio_started = False
            async with entry.lock:
                socket = entry.socket
                connected_ms = entry.connected_ms
                await socket.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": user_text}]},
                }))
                await socket.send(json.dumps({"type": "response.create"}))
                while True:
                    raw = await asyncio.wait_for(socket.recv(), timeout=35)  # type: ignore[union-attr]
                    event = json.loads(raw)
                    if first_event_ms is None:
                        first_event_ms = (time.perf_counter() - started) * 1000
                    event_type = event.get("type")
                    if event_type == "error":
                        raise RuntimeError(event.get("error", {}).get("message", "OpenAI Realtime request failed"))
                    if event_type in {"response.output_audio.delta", "response.audio.delta"}:
                        encoded = event.get("delta")
                        if isinstance(encoded, str):
                            try:
                                chunk = base64.b64decode(encoded, validate=True)
                            except ValueError as error:
                                raise RuntimeError("OpenAI Realtime returned invalid PCM") from error
                            if chunk:
                                if first_audio_ms is None:
                                    first_audio_ms = (time.perf_counter() - started) * 1000
                                # `marin` arrives as 24 kHz S16LE PCM. Convert
                                # each independent 3-sample block to 16 kHz as
                                # it arrives, so Ditto can start before the
                                # model has finished speaking.
                                samples = memoryview(chunk).cast("h")
                                usable = len(samples) - (len(samples) % 3)
                                if usable:
                                    downsampled = bytearray((usable // 3) * 4)
                                    for output_index, input_index in enumerate(range(0, usable, 3)):
                                        a, b, c = samples[input_index:input_index + 3]
                                        downsampled[output_index * 4:output_index * 4 + 4] = int(a).to_bytes(2, "little", signed=True) + int((b + c) // 2).to_bytes(2, "little", signed=True)
                                    with audio_path.open("ab") as output:
                                        output.write(downsampled)
                                    audio_started = True
                                    if not ready.done() and fragments:
                                        ready.set_result(ConversationResponse(text="".join(fragments).strip(), audio_path=f"/data/realtime-audio/{filename}", voice="marin", audio_streaming=True))
                    elif event_type in {"response.output_audio_transcript.delta", "response.audio_transcript.delta", "response.output_text.delta", "response.text.delta"}:
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            if first_text_ms is None:
                                first_text_ms = (time.perf_counter() - started) * 1000
                            fragments.append(delta)
                            self._captions[caption_key] = (key, "".join(fragments).strip(), False)
                    elif event_type in {"response.output_audio_transcript.done", "response.audio_transcript.done", "response.output_text.done", "response.text.done"}:
                        text = event.get("transcript") or event.get("text")
                        if isinstance(text, str):
                            completed_text = text
                    elif event_type in {"response.done", "response.completed"}:
                        break
            if not ready.done():
                text = (completed_text or "".join(fragments)).strip()
                if text and audio_started:
                    ready.set_result(ConversationResponse(text=text, audio_path=f"/data/realtime-audio/{filename}", voice="marin", audio_streaming=True))
                else:
                    raise RuntimeError("OpenAI Realtime returned no initial transcript/audio")
            final_caption = (completed_text or "".join(fragments)).strip()
            self._captions[caption_key] = (key, final_caption, True)
            complete_ms = (time.perf_counter() - started) * 1000
            done_path.touch()
            pcm_ms = audio_path.stat().st_size / 32 if audio_path.exists() else 0
            # Keep a structured, content-free line for field latency diagnosis.
            print("OpenAI Realtime metrics: " + json.dumps({
                "model": self.model,
                "voice": "marin",
                "session_connect_ms": round(connected_ms or -1, 1),
                "turn_connect_ms": 0.0,
                "first_event_ms": round(first_event_ms, 1) if first_event_ms is not None else None,
                "first_audio_ms": round(first_audio_ms, 1) if first_audio_ms is not None else None,
                "first_transcript_ms": round(first_text_ms, 1) if first_text_ms is not None else None,
                "complete_ms": round(complete_ms, 1),
                "pcm_ms": round(pcm_ms, 1),
            }, sort_keys=True), flush=True)
        try:
            producer = asyncio.create_task(produce(), name=f"openai-realtime-marin-{filename}")
            def report(task: asyncio.Task[None]) -> None:
                if task.cancelled():
                    return
                error = task.exception()
                if error and not ready.done():
                    ready.set_exception(error)
                elif error:
                    previous = self._captions.get(caption_key)
                    if previous is not None:
                        self._captions[caption_key] = (previous[0], previous[1], True)
                    done_path.touch()
                    print(f"OpenAI Realtime stream failed after first packet: {error}", flush=True)
            producer.add_done_callback(report)
            return await asyncio.wait_for(ready, timeout=12)
        except TimeoutError as error:
            raise RuntimeError("OpenAI Realtime first audio timed out") from error
