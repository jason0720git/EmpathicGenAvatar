# Turn-boundary flashes and incomplete captions — 2026-09-17

Investigated the supplied 48-second recording and the 17:05/17:06 turn logs.
The original initial REST text and final caption were different; the former
is intentionally just a streaming prefix, not the final answer. The caption
implementation also overwrote all earlier completed output parts with the
last part while PCM from every part was appended. This is a reproducible
failure path; the original full event payloads were not retained, so exact
historical part boundaries cannot be reconstructed from old logs.

## Changes

- Accumulate transcript by output_index/content_index. A done event replaces
  only its own part; response.done reconciles the complete output. Delta and
  done are not appended twice. The final caption includes every spoken part.
- Poll captions for up to 180 seconds, retrying transient request failures.
- Persist caption.final in existing opt-in local decision logs when the final
  caption is retrieved. Provider timing logs now include turn_id, part count,
  and character count (no extra model requests).
- Keep the same loaded idle MJPEG URL across listening/thinking/playback.
- Reveal the speech canvas only after drawImage, not after JPEG decode while
  frames are still waiting in the playout buffer.
- End playback at the maximum of actual audio end and last video PTS + frame
  duration. Remove the arbitrary extra 560 ms hold and idle reload.
- Guard old decode/draw/end callbacks against another turn/unmount. Cancel
  the end timer and free buffered image bitmaps on interruption.
- Log first_frame_presented separately from first_video_decoded.

## Tests

API: 35 passed, including a mocked full Realtime PCM producer with two spoken
items and both final captions retained. Web: 12 passed, including mounted React
LiveRoom tests with delayed frame presentation, stable idle URL, end-of-playback
handoff, and transient caption retry. Production web build passed.
GPU proxy smoke: 110 audio packets, 134 video frames, end marker.

No expression presets or model were changed. This removes source-image exposure
and fixed post-playback holds; it is not interpolation between arbitrary speaking
and idle poses. Browser-background throttling and network/GPU stalls can still
pause visible motion. Real Korean perceptual validation remains user feedback.

Event handling was checked using OpenAI Docs:
https://developers.openai.com/api/docs/guides/realtime-conversations
