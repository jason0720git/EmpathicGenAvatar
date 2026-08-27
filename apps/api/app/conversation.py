from __future__ import annotations

import re

import httpx


class ConversationProvider:
    name = "demo"

    async def respond(self, *, persona: str, user_text: str) -> str:
        raise NotImplementedError


class SafeDemoConversation(ConversationProvider):
    """A deterministic fallback with alternating Korean/English demo turns."""

    def __init__(self) -> None:
        self._reply_count = 0

    def _next_language(self) -> str:
        # This runs on the single async API event loop without an await, so a
        # turn gets one unambiguous language even when requests arrive close
        # together. It intentionally resets when the demo service restarts.
        language = "ko" if self._reply_count % 2 == 0 else "en"
        self._reply_count += 1
        return language

    async def respond(self, *, persona: str, user_text: str) -> str:
        text = user_text.strip()
        lowered = text.lower()
        if any(word in lowered for word in ("미성년", "아동", "아이 사진", "유명인 사칭", "딥페이크 범죄")):
            return "그 용도는 도와드릴 수 없어요. 이 공간에서는 권리를 보유한 성인 인물의 private 아바타만 다루며, 사칭이나 위해 목적의 생성은 지원하지 않습니다."
        language = self._next_language()
        if any(word in lowered for word in ("안녕", "hello", "반가")):
            if language == "ko":
                return f"안녕하세요. 저는 AI 생성 아바타이며, {persona}라는 역할로 대화하고 있어요. 한국어 립싱크를 확인하기 위해 자연스럽게 답변하고 있습니다."
            return f"Hello. I am an AI-generated avatar speaking as {persona}. This English response is for comparing real-time lip sync and pacing."
        if any(word in lowered for word in ("힘들", "불안", "기분", "걱정")):
            if language == "ko":
                return "그렇게 느끼고 계셨군요. 바로 해결하려 하기보다 지금 가장 무겁게 느껴지는 지점을 하나만 골라 이야기해 볼까요? 필요한 속도에 맞춰 함께 생각하겠습니다."
            return "That sounds difficult. Rather than solving everything at once, could we identify the part that feels heaviest right now and take one small step?"
        if "?" in text or "어떻" in lowered or "무엇" in lowered:
            if language == "ko":
                return f"좋은 질문이에요. {persona}의 관점에서 보면, 먼저 목표와 현재 제약을 나눈 뒤 가장 작은 다음 행동을 정하는 편이 좋습니다. 지금 가장 중요하게 두는 기준은 무엇인가요?"
            return f"That is a good question. From the perspective of {persona}, separate the goal from the constraints first, then choose the smallest useful next action. What matters most to you?"
        subject = re.sub(r"[.?!。]+$", "", text)
        if language == "ko":
            return f"말씀해 주셔서 고마워요. “{subject[:72]}”라는 부분을 들었어요. 핵심을 놓치지 않도록, 그 상황에서 바꾸고 싶은 결과를 먼저 함께 정해 볼까요?"
        return f"Thank you for sharing that. I heard the part about “{subject[:72]}.” To keep the focus clear, what outcome would you most like to change?"


class OllamaConversation(ConversationProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def respond(self, *, persona: str, user_text: str) -> str:
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
        return content
