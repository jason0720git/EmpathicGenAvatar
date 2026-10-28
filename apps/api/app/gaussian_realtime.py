"""Realtime voice transport for the Gaussian lab. Keys never reach the browser."""
from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from websockets.asyncio.client import connect


class HeadIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pitch: float = Field(default=0, ge=-10, le=10)
    yaw: float = Field(default=0, ge=-12, le=12)
    roll: float = Field(default=0, ge=-6, le=6)

    @model_validator(mode="before")
    @classmethod
    def normalize_tilt(cls, value):
        # Some tool responses use the natural-language name for lateral roll.
        # Preserve strict validation and bounds after translating this alias.
        if isinstance(value, dict) and "tilt" in value:
            value = dict(value)
            tilt = value.pop("tilt")
            if "roll" in value and value["roll"] != tilt:
                raise ValueError("head.tilt and head.roll must agree when both are supplied")
            value.setdefault("roll", tilt)
        return value


class GazeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)


class BehaviorIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    emotion: Literal["neutral", "happy", "sad", "angry", "fear", "surprise", "disgust", "contempt"] = "neutral"
    intensity: float = Field(default=0.25, ge=0, le=1)
    intent: Literal["attentive", "supportive", "encouraging", "celebrating", "explaining"] = "attentive"
    nod: bool = False
    head: HeadIntent = Field(default_factory=HeadIntent)
    gaze: GazeIntent = Field(default_factory=GazeIntent)

    @model_validator(mode="before")
    @classmethod
    def normalize_nested_nod(cls, value):
        if isinstance(value, dict) and isinstance(value.get("head"), dict) and "nod" in value["head"]:
            value = {**value, "head": dict(value["head"])}
            nod = value["head"].pop("nod")
            if "nod" in value and value["nod"] != nod:
                raise ValueError("nod and head.nod must agree when both are supplied")
            value.setdefault("nod", nod)
        return value


TOOL = {"type": "function", "name": "set_avatar_behavior",
        "description": "Plan the avatar's empathetic display before speaking. Choose response intent and a restrained visible emotion appropriate to the user's words and context, not automatic emotion mirroring. Do not smile at distress or loss. Never diagnose the user.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": ["emotion", "intensity", "intent", "nod"],
                       "properties": {
                           "emotion": {"type": "string", "enum": ["neutral", "happy", "sad", "angry", "fear", "surprise", "disgust", "contempt"]},
                           "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                           "intent": {"type": "string", "enum": ["attentive", "supportive", "encouraging", "celebrating", "explaining"]},
                           "nod": {"type": "boolean"}}}}

INSTRUCTIONS = """You are an explicitly AI-generated avatar and a warm Korean conversation partner.
Answer naturally in the user's language in at most two short sentences. Do not narrate tool use.
Before every spoken reply call set_avatar_behavior exactly once. Select a suitable empathetic response intent and visible expression. User facial cues, if supplied, are uncertain appearance observations, not an emotion diagnosis; their words take priority. Sadness or distress calls for restrained attention and concern, not a default smile. Empathy need not mirror the user's emotion.
The controller, not you, owns low-level facial motion. Never claim to be human or a clinician.
Choose a clearly visible but appropriate intensity (usually 0.55-0.85 for emotional replies).
Head angles are degrees. Use only head.pitch (up/down), head.yaw (left/right), and head.roll (sideways tilt); never output a head.tilt key. Keep angles small and mostly direct eye contact.
The boolean nod belongs at the top level, never inside head. Example: {"emotion":"happy","intensity":0.7,"intent":"celebrating","nod":true,"head":{"pitch":0,"yaw":0,"roll":0},"gaze":{"x":0,"y":0}}.
For direct expression requests, show the requested emotion. For distress, choose concern/support rather than a smile.
"""

TOOL["parameters"] = BehaviorIntent.model_json_schema()


class RealtimeVoice:
    def __init__(self, api_key: str, model: str, voice: str, instructions: str, trace: Callable):
        self.api_key, self.model, self.voice = api_key, model, voice
        self.instructions = instructions
        self.trace = trace
        self.socket = None
        self.history: list[dict] = []
        self.pending_reply: list[dict] | None = None
        self.response_id: str | None = None
        self.manual_intent: BehaviorIntent | None = None

    async def send(self, event: dict):
        if self.socket is None:
            raise RuntimeError("Realtime socket is not connected")
        self.trace("realtime.send", {"event": event})
        await self.socket.send(json.dumps(event))

    def parse_behavior(self, arguments: str) -> BehaviorIntent:
        raw = json.loads(arguments)
        chosen = BehaviorIntent.model_validate(raw)
        aliases = []
        if isinstance(raw, dict) and isinstance(raw.get("head"), dict):
            aliases = [key for key in ("tilt", "nod") if key in raw["head"]]
        if aliases:
            self.trace("behavior.normalized", {"head_aliases": aliases, "canonical": chosen.model_dump()})
        return chosen

    async def receive(self, timeout: float = 35) -> dict:
        event = json.loads(await asyncio.wait_for(self.socket.recv(), timeout=timeout))
        logged = dict(event)
        if event.get("type") == "response.output_audio.delta":
            logged.pop("delta", None)
            logged["audio_base64_chars"] = len(event.get("delta", ""))
        self.trace("realtime.receive", {"event": logged})
        if event.get("type") == "error":
            raise RuntimeError("Realtime: " + event.get("error", {}).get("message", "Unknown error"))
        return event

    async def start(self):
        if self.socket is not None:
            return
        self.socket = await connect(f"wss://api.openai.com/v1/realtime?model={self.model}",
                                    additional_headers={"Authorization": f"Bearer {self.api_key}"},
                                    open_timeout=15, close_timeout=2, max_size=8*1024*1024)
        await self.send({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["audio"],
            "instructions": INSTRUCTIONS + "\n" + self.instructions,
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None,
                                 "transcription": {"model": "whisper-1"}},
                      "output": {"voice": self.voice, "format": {"type": "audio/pcm", "rate": 24000}}},
            "tools": [TOOL], "tool_choice": "auto"}})
        while True:
            event = await self.receive(15)
            if event["type"] == "session.updated":
                break
        # A cancellation closes the upstream socket. Restore only completed turns;
        # unheard/unfinished output cannot reappear as conversation history.
        for message in self.history[-16:]:
            await self.send({"type": "conversation.item.create", "item": {
                "type": "message", "role": message["role"], "content": [
                    {"type": "input_text" if message["role"] == "user" else "text", "text": message["text"]}]}})

    async def close(self):
        socket, self.socket = self.socket, None
        if socket:
            await socket.close()

    def commit_playback(self):
        if self.pending_reply is not None:
            self.history.extend(item for item in self.pending_reply if item.get("text"))
            self.history = self.history[-16:]
            self.pending_reply = None

    def discard_playback(self):
        # Preserve the user's utterance but never pretend unheard output was heard.
        if self.pending_reply is not None:
            self.history.extend(item for item in self.pending_reply if item["role"] == "user" and item.get("text"))
            self.history = self.history[-16:]
            self.pending_reply = None

    async def turn(self, text: str | None, audio: bytes | None, observation: str,
                   on_intent: Callable[[BehaviorIntent], Awaitable[None]],
                   on_audio: Callable[[bytes], Awaitable[None]],
                   on_transcript: Callable[[str, str, bool], Awaitable[None]]):
        await self.start()
        if self.pending_reply is not None:
            raise RuntimeError("Previous response playback must be committed or discarded before a new turn")
        self.pending_reply = []
        user_text = text or ""
        current_audio_item_id = None
        early_transcripts: dict[str, str] = {}

        async def stage_user(transcript: str):
            nonlocal user_text
            user_text = transcript
            # Stage the accepted/recognized user immediately. Cancellation may
            # occur while planning or speaking, before any response.done event.
            # Blank/unrecognized audio never becomes a fabricated transcript.
            if transcript:
                self.pending_reply = [{"role": "user", "text": transcript}]
            await on_transcript("user", transcript, True)

        if audio:
            await self.send({"type": "input_audio_buffer.clear"})
            for offset in range(0, len(audio), 24000):
                await self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(audio[offset:offset+24000]).decode()})
            await self.send({"type": "input_audio_buffer.commit"})
        else:
            await self.send({"type": "conversation.item.create", "item": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
            await stage_user(user_text)

        async def transcription(event):
            nonlocal current_audio_item_id
            kind = event.get("type")
            if audio and kind == "input_audio_buffer.committed":
                current_audio_item_id = event.get("item_id")
                if current_audio_item_id in early_transcripts:
                    await stage_user(early_transcripts[current_audio_item_id])
                early_transcripts.clear()
            elif kind == "conversation.item.input_audio_transcription.completed":
                item_id = event.get("item_id")
                transcript = event.get("transcript", "")
                if audio and item_id and item_id == current_audio_item_id:
                    await stage_user(transcript)
                elif audio and item_id and current_audio_item_id is None:
                    # Normally committed precedes transcription. Keep a small
                    # out-of-order buffer but require the committed ID match.
                    if len(early_transcripts) < 8:
                        early_transcripts[item_id] = transcript
                else:
                    self.trace("realtime.transcription.ignored", {"item_id": item_id, "reason": "not_current_input_item"})

        if self.manual_intent is not None:
            chosen = self.manual_intent
            await on_intent(chosen)
            self.trace("behavior.manual", chosen.model_dump())
        else:
            await self.send({"type": "response.create", "response": {
                "tool_choice": {"type": "function", "name": TOOL["name"]},
                "instructions": INSTRUCTIONS + ("\nCurrent uncertain appearance cues: " + observation if observation else "")}})
            chosen = None
            call_id = None
            while True:
                event = await self.receive()
                await transcription(event)
                if event["type"] == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call" and item.get("name") == TOOL["name"]:
                        chosen = self.parse_behavior(item.get("arguments", "{}"))
                        call_id = item["call_id"]
                if event["type"] == "response.function_call_arguments.done" and event.get("name") == TOOL["name"]:
                    chosen = self.parse_behavior(event.get("arguments", "{}"))
                    call_id = event["call_id"]
                if event["type"] == "response.done":
                    if event.get("response", {}).get("status") not in {"completed", None}:
                        raise RuntimeError("Realtime behavior response failed: " + json.dumps(event.get("response", {}).get("status_details")))
                    break
            if chosen is None or call_id is None:
                raise RuntimeError("Realtime did not return a valid behavior plan")
            await on_intent(chosen)
            await self.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id, "output": json.dumps({"applied": True, **chosen.model_dump()})}})
        await self.send({"type": "response.create", "response": {"tool_choice": "none"}})
        response_text = ""
        output_samples = 0
        while True:
            event = await self.receive()
            kind = event["type"]
            await transcription(event)
            if kind == "response.created":
                self.response_id = event.get("response", {}).get("id")
            elif kind == "response.output_audio.delta":
                pcm = base64.b64decode(event["delta"], validate=True)
                if len(pcm) % 2:
                    raise RuntimeError("Realtime returned malformed PCM")
                output_samples += len(pcm)//2
                if output_samples > 24000*120:
                    raise RuntimeError("Reply exceeded the 120 second audio bound")
                await on_audio(pcm)
            elif kind == "response.output_audio_transcript.delta":
                response_text += event.get("delta", "")
                await on_transcript("assistant", response_text, False)
            elif kind == "response.output_audio_transcript.done":
                response_text = event.get("transcript", response_text)
                await on_transcript("assistant", response_text, True)
            elif kind == "response.done":
                status = event.get("response", {}).get("status")
                if status != "completed":
                    raise RuntimeError(f"Realtime audio response {status}: {event.get('response', {}).get('status_details')}")
                break
        if not output_samples:
            raise RuntimeError("Realtime completed without speech audio")
        self.pending_reply = [item for item in (self.pending_reply or []) if item["role"] == "user"]
        self.pending_reply.append({"role": "assistant", "text": response_text})
        return {"text": response_text, "user_text": user_text, "samples": output_samples, "intent": chosen.model_dump()}
