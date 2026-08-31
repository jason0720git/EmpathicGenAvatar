# Ditto Realtime sampling-step benchmark — 2026-08-28

## Conditions

- GPU: RTX 5090
- Renderer: `ditto_realtime`, PyTorch checkpoint path (no supplied Ampere/TRT-8 engines)
- Avatar: `demo-seoyeon`
- Text: fixed Korean sentence, 230 generated 25-fps frames / 9,160 ms media timeline
- Protocol: local worker WebSocket; browser's separate 600 ms playout buffer is not included
- Each step value used a newly recreated worker, one avatar preparation/warm-up, then ten sequential turns. Audio/video packet count and final PTS were checked on every turn.

## Results

| Sampling steps | First packet p50 | Observed first-spoken outlier | Completion p50 | A/V end skew | Visual result | Decision |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 4 | 3,039 ms | 3,850 ms | 9,983 ms | 0 ms | Stable | Keep as current baseline |
| 3 | 2,798 ms | 3,650 ms | 10,897 ms | 0 ms | Failed: white/blank face region at 1 s, 3 s, and 6 s | Reject |
| 2 | 2,529 ms | 3,319 ms | 9,537 ms | 0 ms | Representative frames remained natural enough for a fast lane | Candidate, not default yet |

The 4-step suite's tenth-to-first distribution was 3,850, 3,061, 2,960, 2,994, 3,092, 2,989, 3,037, 3,057, 3,042, and 3,004 ms. The first real speech after avatar preparation is materially slower than the following turns. This is a valid product metric, not noise to remove from reporting.

## Internal timing finding

Representative 2-step worker timing was: TTS all PCM ready 83 ms, Ditto setup complete 108 ms, first generated frame 2,520 ms. Therefore TTS and worker setup are not the dominant first-packet bottlenecks; the initial Ditto inference/decode path is.

## Next action

Keep `DITTO_REALTIME_SAMPLING_TIMESTEPS=4` as the deployed quality baseline. Treat 2-step as an explicit experiment behind a renderer/quality flag. Do not pursue 3-step without diagnosing the blank-frame failure.

## Pipeline profile — 2026-08-28

One controlled 4-step turn on the same RTX 5090 produced its first visible Ditto frame in **2,947 ms after renderer start** (worker-wide first frame: 3,616 ms, including local TTS and scheduling). The independently repeated profile was within 2 ms of this result.

| First completion on the initial pipeline fill | Time after renderer start | First-call wall time |
| --- | ---: | ---: |
| HuBERT feature extraction | 40 ms | 13 ms |
| Audio-to-motion diffusion | 605 ms | 403 ms |
| Motion stitch | 610 ms | 4 ms |
| Warp | 668 ms | 58 ms |
| Decode | 848 ms | 180 ms |
| Put-back + JPEG/packet | 860 ms | 12 ms + negligible callback |
| First visible browser-eligible frame | **2,947 ms** | — |

The ~2.09 s gap after the first internally rendered frame is not WebSocket/JPEG overhead. The online SDK requires a 13-frame causal context (`DITTO_PREROLL_FRAMES`) which is intentionally discarded so that video PTS 0 aligns with PCM PTS 0. At the current per-frame render throughput, producing those context frames is the dominant first-frame cost. The profile is produced only when `DITTO_PROFILE_FIRST_TURN=true`, uses no retained audio/video, and is saved beneath `/data/benchmarks/profiles/`.

**Optimization implication:** reducing the first packet below ~2 seconds requires changing the causal/preroll contract or using a separate fast first-frame renderer; more JPEG warming or TTS work cannot remove this fixed Ditto online pipeline fill. The safe next experiment is a selectable 2-step Fast Lane with the same causal trimming and full visual regression gate, not a silent change to the 4-step baseline.

## Selectable 2-step Fast Lane — implementation check

`ditto_realtime_fast` is now a session-level renderer choice. It sends the fixed `render_profile: "fast"` contract to the existing Ditto Realtime worker, which selects `DITTO_FAST_SAMPLING_TIMESTEPS=2`; normal `ditto_realtime` remains fixed at 4 steps. The control plane never accepts an arbitrary client-provided step number.

Three direct worker runs confirmed that the SDK received `sampling_timesteps=2`, each emitted 230 audio and 230 video packets, and each ended at the same 9,160 ms PTS (0 ms A/V end skew). Representative 1 s and 3 s frames retained full-face identity and showed no blank-frame failure. During this run, however, the RTX 5090 had roughly 27/32 GB already occupied by other GPU processes, so first-packet times were 96.7 s, 8.6 s, and 2.59 s. Only the final value is representative of a settled turn; do not use the aggregate as a latency claim. Re-run the 10-turn suite on an otherwise idle GPU before promoting Fast Lane beyond an explicit experiment.

## End-to-end telemetry and preroll experiment — 2026-08-28

The deployed browser now writes timing-only events keyed by the worker turn ID to `/data/telemetry/turn-events.jsonl`; no prompt text, audio, or frames are recorded. In two real browser Fast Lane turns, API response and socket open took 22–41 ms, the first JPEG arrived at 2.764 s / 2.876 s, JPEG decoding added 5–6 ms, and actual playout began at 4.072 s / 4.025 s. There were no JPEG decode failures or video PTS gaps. The second completed turn reduced the adaptive playout target from 350 to 300 ms.

The 10-turn direct 2-step/13-preroll run had one intentionally cold avatar-preparation turn (60.2 s first packet), which is excluded from steady-state interpretation. The remaining nine turns achieved **2.56 s p50**, **2.87 s p95**, and **0 ms** final A/V skew. This validates `fast` as the only selectable Fast Lane profile.

| Benchmark-only profile | First packet p50 | Apparent saving vs 13 | Decision |
| --- | ---: | ---: | --- |
| `fast` / 13-frame causal trim | 2.56 s | baseline | selectable experiment |
| `fast_preroll9` | 1.98 s | 0.58 s | reject for product: exposes 4 context frames early |
| `fast_preroll5` | 1.34 s | 1.22 s | reject for product: exposes 8 context frames early |

Both 9- and 5-frame variants retained packet counts and final PTS, and did not show blank faces in still-frame inspection. They nevertheless re-label causal context as speech PTS 0; the existing 13-frame contract explicitly marks that content as non-speech context. Therefore their apparent latency saving is a likely first-phoneme lip-sync error (160 ms / 320 ms), not a valid latency optimization. They remain hidden benchmark controls only.
