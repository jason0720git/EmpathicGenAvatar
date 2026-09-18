# Motion boundary v6 — 2026-09-18

## What changed

- Idle is now **400 frames / 25 fps = 16 seconds**, previously 200 / 25 =
  8 seconds. This is newly generated motion, not half-speed playback. Four
  irregular blink gaps replace the old two-blink pattern. Cache revision 6
  prevents an existing 200-frame asset from being mistaken for the new loop.
- Idle's final driving-coordinate blend settles over 40 frames / 1.6 s at
  both ends, previously 20 frames / 0.8 s. Its source-space endpoints remain
  identical. This affects idle, not speech lip articulation.
- The browser explicitly parses and decodes idle MJPEG into a persistent
  canvas. Handoffs snapshot the canvas that was actually painted, instead of
  sampling a separately presented native MJPEG image whose frame clock is
  not exposed. Idle continues underneath speech; no turn-boundary reload.
- Serialized idle decoding plus latest-frame presentation avoids playing
  coalesced network bursts as accelerated movement. Speech rejects older PTS
  frames when asynchronous JPEG decodes or callbacks finish out of order.
- Boundary registration now considers translation plus bounded 2D roll
  (±3 degrees) and scale (±3%). Extra transform freedom requires a further
  improvement over translation alone. Low-confidence matches are rejected.
  Motion correction eases out over 480 ms; opacity mixing only lasts 160 ms.
- The worker schedules idle against a monotonic 25-fps deadline rather than
  adding socket-send time to every frame interval. It does not catch up by
  sending an arbitrarily large backlog.
- `visual_transition` logs identify `canvas_similarity_v6`, direction,
  duration, translation, angle, scale, and acceptance. `playout_drift` records
  stale speech-frame drops. No new LLM requests or token consumption.

## Evidence and tests

The prior v5 cache already had zero first/last face-pixel difference. Therefore
the remaining report cannot honestly be attributed solely to unequal cached
endpoints. These changes address presentation ownership, frame order, motion
settling, and the limited translation-only handoff separately; they do not
claim to reconstruct the exact cause of every previously observed jump.

- Web: 21 tests pass (split/coalesced MJPEG, malformed-length bounds, explicit
  canvas painting and abort cleanup, stale-PTS rejection, similarity fitting,
  and existing playback/caption regressions); TypeScript/production build pass.
- API: 39 tests pass. GPU worker: 20 fixture-free test functions pass via
  runpy inside the image, including duration, blink coverage and endpoints.
- Generated Doyun and Seoyeon, 3 variants each: all are 400 frames / 16 s;
  last-to-first face MAE is zero for all six. Adjacent seam steps are about
  0.22 (Doyun) and 0.29–0.30 (Seoyeon), reduced from v5's ~0.25 and ~0.33.
  Measurements/clips: `artifacts/idle-seam-v6-demo-doyun/` and
  `artifacts/idle-seam-v6-demo-seoyeon/`.
- Live HTTP stream through web/API: 401 frames observed, loop period
  **15.999 s**, maximum inter-frame arrival gap **41.4 ms**. Frames 399 and
  400 both matched frame 0's JPEG hash (closed endpoint and wrapped start).
- Computer Use browser check, Doyun Happy 100%, turn
  `user-1789699745133`: both entry/exit v6 alignments accepted; initial
  dx/dy .005208/.004167, exit -.005208/-.00625; no rotation/scale needed
  in this example. Zero JPEG failures, zero PTS gaps, running AudioContext,
  clean stream close, final caption and return to ready.
- GPU proxy smoke `proxy-smoke-5ec07d59a294`: 110 audio packets, 134 video
  frames, one normal end marker.

## Scope / limits

Deployed web and TRT10 worker. Doyun and Seoyeon new caches are prepared;
other avatars generate their new cache on selection. Refresh and start a
new session so the browser gets v6. Doyun's echo setting is preserved.

This is stronger 2D presentation continuity, not full stateful 3D animation.
Large yaw, expression changes, or network stalls can still produce noticeable
motion; a 160 ms mix may still show slight ghosting. The 16 s pattern still
repeats (variants are chosen per session, not randomly every loop). A fully
non-repeating idle and guaranteed pose/velocity continuity would require a
shared live motion-state generator, not merely further dissolve tuning.
Realtime canvas handoffs are covered; the batch video player is unchanged.
