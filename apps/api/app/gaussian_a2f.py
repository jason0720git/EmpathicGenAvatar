"""Streaming NVIDIA ACE Audio2Face-3D -> canonical ARKit animation.

Uses the documented controller v1 wire contract (NIM 1.3 and 2.0), with a
private, minimal protobuf descriptor so no generated code or Unity install is
needed. Unknown protocol fields are left to protobuf's normal forward-compatible
handling. This module never substitutes synthetic lip motion for failed A2F.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import grpc
import numpy as np
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


# Apple ARKit naming, with the same 52-name order as NVIDIA's documented list.
# Consumers must map by name, never assume an inference service's output order.
ARKIT_NAMES = (
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft",
    "eyeSquintLeft", "eyeWideLeft", "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight",
    "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight", "jawForward",
    "jawLeft", "jawRight", "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft",
    "mouthRight", "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight", "mouthRollLower",
    "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthPressLeft", "mouthPressRight",
    "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight", "browDownLeft",
    "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "cheekPuff",
    "cheekSquintLeft", "cheekSquintRight", "noseSneerLeft", "noseSneerRight", "tongueOut",
)
_CANONICAL = {"".join(c for c in name.lower() if c.isalnum()): name for name in ARKIT_NAMES}
TraceCallback = Callable[[str, dict[str, Any]], None]
RPC_METHOD = "/nvidia_ace.services.a2f_controller.v1.A2FControllerService/ProcessAudioStream"


def canonical_name(name: str) -> str | None:
    return _CANONICAL.get("".join(c for c in name.lower() if c.isalnum()))


def canonical_weights(weights: Mapping[str, float]) -> dict[str, float]:
    result = dict.fromkeys(ARKIT_NAMES, 0.0)
    for name, value in weights.items():
        key = canonical_name(name)
        if key is not None:
            number = float(value)
            result[key] = max(0.0, min(1.0, number)) if math.isfinite(number) else 0.0
    return result


@dataclass(frozen=True)
class A2FFrame:
    time_seconds: float
    coefficients: dict[str, float]
    received_elapsed_ms: float = 0.0

    @property
    def weights(self) -> dict[str, float]:
        return self.coefficients

    def values(self, names: tuple[str, ...] = ARKIT_NAMES) -> list[float]:
        return [self.coefficients.get(name, 0.0) for name in names]


class A2FError(RuntimeError):
    """Actionable A2F failure; callers must expose it instead of faking success."""


@lru_cache(maxsize=1)
def _protocol() -> dict[str, type]:
    """Subset of the public ACE schema; package names do not affect wire data.

    Field numbers/types match NVIDIA's Apache-2.0 ACE proto definitions:
    https://docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/interacting/a2f-rpc.html
    Proto2 permits explicit zero emotion_strength so A2E cannot add a smile
    against the behavior controller's chosen affect.
    """
    fd = descriptor_pb2.FileDescriptorProto(name="egavatar_a2f_wire.proto", package="egavatar.a2f", syntax="proto2")
    F = descriptor_pb2.FieldDescriptorProto
    definitions = {
        "AudioHeader": [("audio_format", 1, F.TYPE_INT32), ("channel_count", 2, F.TYPE_UINT32),
                        ("samples_per_second", 3, F.TYPE_UINT32), ("bits_per_sample", 4, F.TYPE_UINT32)],
        "EmotionPostProcessing": [("emotion_strength", 5, F.TYPE_FLOAT)],
        "AudioStreamHeader": [("audio_header", 1, "AudioHeader"), ("emotion_post_processing_params", 3, "EmotionPostProcessing")],
        "AudioWithEmotion": [("audio_buffer", 1, F.TYPE_BYTES)],
        "EndOfAudio": [],
        "AudioStream": [("audio_stream_header", 1, "AudioStreamHeader"), ("audio_with_emotion", 2, "AudioWithEmotion"),
                        ("end_of_audio", 3, "EndOfAudio")],
        "SkelAnimationHeader": [("blend_shapes", 1, F.TYPE_STRING, True), ("joints", 2, F.TYPE_STRING, True)],
        "AnimationDataStreamHeader": [("audio_header", 1, "AudioHeader"), ("skel_animation_header", 2, "SkelAnimationHeader"),
                                      ("start_time_code_since_epoch", 3, F.TYPE_DOUBLE)],
        "FloatArrayWithTimeCode": [("time_code", 1, F.TYPE_DOUBLE), ("values", 2, F.TYPE_FLOAT, True)],
        "SkelAnimation": [("blend_shape_weights", 1, "FloatArrayWithTimeCode", True)],
        "AnimationData": [("skel_animation", 1, "SkelAnimation")],
        "Event": [("event_type", 1, F.TYPE_INT32)],
        "Status": [("code", 1, F.TYPE_INT32), ("message", 2, F.TYPE_STRING)],
        "AnimationDataStream": [("animation_data_stream_header", 1, "AnimationDataStreamHeader"),
                                ("animation_data", 2, "AnimationData"), ("event", 3, "Event"), ("status", 4, "Status")],
        "HealthCheckRequest": [("service", 1, F.TYPE_STRING)],
        "HealthCheckResponse": [("status", 1, F.TYPE_INT32)],
    }
    for name, fields in definitions.items():
        message = fd.message_type.add(name=name)
        for spec in fields:
            field_name, number, field_type, *rest = spec
            repeated = bool(rest and rest[0])
            field = message.field.add(name=field_name, number=number, label=F.LABEL_REPEATED if repeated else F.LABEL_OPTIONAL)
            if isinstance(field_type, str):
                field.type = F.TYPE_MESSAGE
                field.type_name = ".egavatar.a2f." + field_type
            else:
                field.type = field_type
                if repeated and field_type == F.TYPE_FLOAT:
                    field.options.packed = True
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fd)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName("egavatar.a2f." + name)) for name in definitions}


class PCM16Resampler:
    """Chunk-boundary independent, band-limited mono PCM16 resampling.

    A 33-tap windowed sinc polyphase filter keeps ~0.7 ms lookahead at 24 kHz.
    The same source always gives the same result regardless of websocket chunk
    sizes, including odd byte boundaries. Output timestamps remain source-time.
    """

    def __init__(self, input_rate: int = 24000, output_rate: int = 16000):
        if input_rate not in (16000, 24000, 44100, 48000) or output_rate != 16000:
            raise ValueError("Supported A2F input rates: 16000, 24000, 44100, 48000 Hz; output: 16000 Hz")
        self.input_rate, self.output_rate = input_rate, output_rate
        self._buffer = np.empty(0, dtype=np.float64)
        self._start = 0
        self._total = 0
        self._next = 0
        self._odd = b""
        self._closed = False
        self._half = 16
        self._filters: dict[int, np.ndarray] = {}

    def push(self, data: bytes, *, final: bool = False) -> bytes:
        if self._closed:
            raise ValueError("Resampler already flushed")
        combined = self._odd + data
        even_size = len(combined) - len(combined) % 2
        self._odd = combined[even_size:]
        if final and self._odd:
            raise ValueError("PCM16 stream ended with an incomplete sample")
        if self.input_rate == self.output_rate:
            self._closed = final
            return combined[:even_size]
        samples = np.frombuffer(combined[:even_size], dtype="<i2").astype(np.float64)
        self._buffer = np.concatenate((self._buffer, samples))
        self._total += len(samples)
        maximum = math.ceil(self._total * self.output_rate / self.input_rate) if final else max(
            0, math.ceil((self._total - self._half - 1) * self.output_rate / self.input_rate))
        indices = np.arange(self._next, maximum, dtype=np.int64)
        if not len(indices):
            self._closed = final
            return b""
        numerator = indices * self.input_rate
        centers, phases = numerator // self.output_rate, numerator % self.output_rate
        offsets = np.arange(-self._half, self._half + 1)
        result = np.zeros(len(indices), dtype=np.float64)
        for phase in np.unique(phases):
            phase_int = int(phase)
            if phase_int not in self._filters:
                distance = offsets - phase_int / self.output_rate
                cutoff = min(1.0, self.output_rate / self.input_rate) * 0.94
                kernel = cutoff * np.sinc(cutoff * distance) * np.hanning(len(offsets))
                self._filters[phase_int] = kernel / kernel.sum()
            selected = phases == phase
            source = centers[selected, None] + offsets[None, :] - self._start
            valid = (source >= 0) & (source < len(self._buffer))
            window = self._buffer[np.clip(source, 0, max(0, len(self._buffer) - 1))]
            result[selected] = (np.where(valid, window, 0.0) * self._filters[phase_int]).sum(axis=1)
        self._next = maximum
        keep_from = max(self._start, self._next * self.input_rate // self.output_rate - self._half)
        self._buffer = self._buffer[keep_from - self._start:]
        self._start = keep_from
        self._closed = final
        return np.clip(np.rint(result), -32768, 32767).astype("<i2").tobytes()


class A2FClient:
    def __init__(self, endpoint: str = "localhost:52000", *, timeout_seconds: float = 180.0,
                 connect_timeout_seconds: float = 3.0, trace: TraceCallback | None = None):
        parsed = urlsplit(endpoint if "://" in endpoint else "http://" + endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
            raise ValueError("A2F endpoint must be host:port, http://host:port, or https://host:port")
        self.target = parsed.netloc
        self.secure = parsed.scheme == "https"
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.trace = trace

    def _emit(self, event: str, **payload: Any) -> None:
        if self.trace:
            self.trace(event, payload)

    def _channel(self):
        options = [("grpc.max_receive_message_length", 16 * 1024 * 1024)]
        return grpc.aio.secure_channel(self.target, grpc.ssl_channel_credentials(), options=options) if self.secure else grpc.aio.insecure_channel(self.target, options=options)

    async def health(self) -> dict[str, Any]:
        proto = _protocol()
        try:
            async with self._channel() as channel:
                await asyncio.wait_for(channel.channel_ready(), self.connect_timeout_seconds)
                rpc = channel.unary_unary("/grpc.health.v1.Health/Check", request_serializer=lambda msg: msg.SerializeToString(),
                                          response_deserializer=proto["HealthCheckResponse"].FromString)
                try:
                    status = await rpc(proto["HealthCheckRequest"](), timeout=self.connect_timeout_seconds)
                    return {"ready": status.status == 1, "endpoint": self.target, "health_status": int(status.status), "transport": "grpc"}
                except grpc.aio.AioRpcError as exc:
                    if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
                        return {"ready": False, "reachable": True, "endpoint": self.target, "error": "gRPC health service unavailable; run audio probe"}
                    raise
        except (grpc.aio.AioRpcError, TimeoutError) as exc:
            return {"ready": False, "endpoint": self.target, "error": type(exc).__name__}

    async def stream(self, pcm: AsyncIterator[bytes], *, input_sample_rate: int = 24000) -> AsyncIterator[A2FFrame]:
        proto = _protocol()
        resampler = PCM16Resampler(input_sample_rate)
        started = time.monotonic()
        input_bytes = output_bytes = frame_count = 0
        last_time = -1.0
        names: list[str] = []
        terminal_success = False
        producer_error: Exception | None = None

        async def produce_requests():
            nonlocal input_bytes, output_bytes
            header = proto["AudioStream"]()
            audio = header.audio_stream_header.audio_header
            audio.audio_format, audio.channel_count, audio.samples_per_second, audio.bits_per_sample = 0, 1, 16000, 16
            header.audio_stream_header.emotion_post_processing_params.emotion_strength = 0.0
            yield header
            self._emit("a2f.header.sent", sample_rate=16000, input_sample_rate=input_sample_rate, emotion_owner="behavior_controller")
            async for chunk in pcm:
                if not isinstance(chunk, bytes):
                    raise ValueError("A2F PCM chunks must be bytes")
                input_bytes += len(chunk)
                converted = resampler.push(chunk)
                # Bound request sizes to 100 ms even if upstream bursts arrive.
                for offset in range(0, len(converted), 3200):
                    message = proto["AudioStream"]()
                    message.audio_with_emotion.audio_buffer = converted[offset:offset + 3200]
                    output_bytes += len(message.audio_with_emotion.audio_buffer)
                    yield message
            tail = resampler.push(b"", final=True)
            if tail:
                message = proto["AudioStream"]()
                message.audio_with_emotion.audio_buffer = tail
                output_bytes += len(tail)
                yield message
            if not output_bytes:
                raise A2FError("No PCM audio received for A2F")
            end = proto["AudioStream"]()
            end.end_of_audio.SetInParent()
            yield end
            self._emit("a2f.audio.complete", input_bytes=input_bytes, output_bytes=output_bytes,
                       duration_seconds=output_bytes / 32000)

        async def requests():
            nonlocal producer_error
            try:
                async for request in produce_requests():
                    yield request
            except Exception as exc:
                # grpc.aio otherwise turns iterator failures into an opaque
                # CancelledError, indistinguishable from user interruption.
                producer_error = exc
                raise

        call = None
        self._emit("a2f.connecting", endpoint=self.target)
        try:
            async with self._channel() as channel:
                await asyncio.wait_for(channel.channel_ready(), self.connect_timeout_seconds)
                rpc = channel.stream_stream(RPC_METHOD, request_serializer=lambda msg: msg.SerializeToString(),
                                            response_deserializer=proto["AnimationDataStream"].FromString)
                call = rpc(requests(), timeout=self.timeout_seconds)
                async for response in call:
                    if response.HasField("animation_data_stream_header"):
                        names = list(response.animation_data_stream_header.skel_animation_header.blend_shapes)
                        mapped = sum(canonical_name(name) is not None for name in names)
                        if mapped == 0:
                            raise A2FError("A2F returned no recognizable ARKit channels")
                        self._emit("a2f.header.received", channel_count=len(names), mapped_channels=mapped, channels=names)
                    if response.HasField("animation_data"):
                        if not names:
                            raise A2FError("A2F animation arrived before channel header")
                        for keyframe in response.animation_data.skel_animation.blend_shape_weights:
                            if len(keyframe.values) != len(names):
                                raise A2FError("A2F channel/value count mismatch")
                            timestamp = float(keyframe.time_code)
                            if not math.isfinite(timestamp) or timestamp < 0 or timestamp <= last_time:
                                raise A2FError("A2F timestamps must be finite and strictly increasing")
                            last_time = timestamp
                            frame_count += 1
                            elapsed = (time.monotonic() - started) * 1000
                            if frame_count == 1:
                                self._emit("a2f.first_frame", elapsed_ms=round(elapsed, 2), time_seconds=timestamp)
                            weights = canonical_weights(dict(zip(names, keyframe.values)))
                            yield A2FFrame(timestamp, weights, elapsed)
                    if response.HasField("event"):
                        self._emit("a2f.event", event_type=int(response.event.event_type))
                    if response.HasField("status"):
                        code = int(response.status.code)
                        self._emit("a2f.status", code=code, message=response.status.message)
                        if code == 3:
                            raise A2FError("NVIDIA A2F rejected audio: " + response.status.message)
                        terminal_success = code == 0 or terminal_success
                if not frame_count:
                    raise A2FError("A2F closed without producing animation frames")
                if not terminal_success:
                    raise A2FError("A2F closed without its required SUCCESS status")
                self._emit("a2f.complete", frame_count=frame_count, duration_seconds=last_time,
                           elapsed_ms=round((time.monotonic() - started) * 1000, 2))
        except asyncio.CancelledError:
            if producer_error is not None:
                self._emit("a2f.error", code="INVALID_AUDIO", detail=str(producer_error))
                raise A2FError(f"A2F audio producer failed: {producer_error}") from producer_error
            raise
        except grpc.aio.AioRpcError as exc:
            self._emit("a2f.error", code=exc.code().name, detail=exc.details())
            raise A2FError(f"NVIDIA A2F {exc.code().name}: {exc.details()}") from exc
        except TimeoutError as exc:
            self._emit("a2f.error", code="CONNECT_TIMEOUT", endpoint=self.target)
            raise A2FError(f"NVIDIA A2F connection timed out: {self.target}") from exc
        finally:
            if call is not None and not call.done():
                call.cancel()
