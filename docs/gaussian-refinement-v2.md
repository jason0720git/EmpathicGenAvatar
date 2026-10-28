# Avatar refinement, oral anatomy and Auto/manual modes — 2026-09-28

## Delivered avatars

- 서연 · 정밀 보정·구강 v2: `88546d4a362b4a97979c5360`
- Emma · 정밀 보정·구강 v2: `2a80fe76d5f44beba2a3c0ac`

The previous assets and original source photos are preserved. Choose these new library entries at `/gaussian`. The changes are calibrated for these two identities; this does not silently retrofit every imported/generated avatar.

## Identity comparison

A further smooth 3D residual-fitting pass used fresh renders of the previous corrected avatars. Covariance, base positions and every existing expression delta were transformed consistently. The extra-pass maximum displacement was 3.64 mm / 3.91 mm for Seoyeon / Emma, with minimum Jacobian determinants 0.865 / 0.846 (no folding).

| Same-source landmark metric | Previous delivered | Current delivered |
| --- | --- | --- |
| Seoyeon, all 68 | 2.22% | 1.64% |
| Seoyeon, mouth | 2.34% | 1.38% |
| Emma, all 68 | 2.20% | 1.53% |
| Emma, mouth | 2.04% | 1.12% |

Metric: mean landmark distance normalized by eye-center distance after eye-center similarity alignment. This is a fit measurement, **not a likeness score or independent recognition benchmark**. Not every region improves (eye-region residuals remain). Fine skin, hair, eye details and unobserved geometry still differ from the original image. Single-photo LAM reconstruction plus calibration does not reproduce the photo exactly.

An experimental source-color projection was implemented and tested, but **not adopted**: it increased Emma's measured residual to 2.08% and degraded lip appearance during articulation. Delivered assets retain the learned appearance, with oral shading applied only while opening the mouth. `project_portrait_color.py` and `*-color.zip` remain experiment/provenance artifacts, not the served assets.

## Why the mouth was white, and what changed

The actual `vendor/LAM/configs/inference/lam-20k-8gpu.yaml` sets `add_teeth: false` and `oral_mesh_flag: false`. The exported template had 51 channels, with no `tongueOut`. Upstream contains optional teeth code, but it was not enabled in this checkpoint. The visible white patches were therefore not evidence of an independently reconstructed anatomical tongue/teeth assembly.

`refine_oral_asset.py` adds 890 jaw-driven 3D Gaussian points: 375 dark cavity points, 275 tongue points, and 120 points each for upper and lower teeth. A new `tongueOut` morph acts only on the added tongue, bringing the rig to 52 channels and 20,908 points. Jaw opening moves the oral floor; tongueOut adds a bounded forward displacement. These are procedural supplemental surfaces, not a tongue inferred from the closed-mouth photo or a full physiological speech model.

The renderer clips the added surfaces to a rounded mouth opening and hides them at rest. Recessed bright reconstructed fragments are darkened only within the open oral volume. Permanent recoloring was rejected because it could stain closed-mouth corners. The diagnostic panel reports oral occlusion and tongue-channel availability; rig check exposes jaw, tongue, blink, emotion and yaw controls. Extreme poses and lip boundaries can still show reconstruction artifacts; this is not a claim of flawless anatomy from every view.

## Auto and manual behavior

- **Auto checked:** a forced `set_avatar_behavior` LLM tool call plans emotion, intensity, response intent, nod, bounded head angles and gaze before speech. The app validates the plan and sends the tool result before requesting audio. A2F owns articulation; the deterministic controller composes nonverbal expression. This follows the tool-before-speech approach inspected in SOBIA-Unity's `SharedPackages/com.etri.sobia/Runtime/Conversation/RealtimeManager.cs`; it does not claim to port its full 11-state/timeline policy.
- **Select an emotion:** switches to manual immediately. The selection survives starting a new conversation. Manual speech skips the LLM behavior-planning call, and playback-time expression composition also overrides already-buffered affect while retaining interpolated A2F articulation. This allows deliberately testing a sad face while speaking a positive sentence.
- Starting a new session clears prior turn diagnostics/counters. Auto idle no longer shows a stale manual emotion.
- Backend logs retain LLM arguments, selected plan, raw/composed A2F data, mode switches and once-per-second actual rendered weights/head/gaze. Diagnostic provenance distinguishes `llm_tool_call`, `manual_expression`, and rule-based idle behavior.

Official protocol reference: [OpenAI Realtime with tools](https://developers.openai.com/api/docs/guides/realtime-mcp). The app uses application-owned function tools and returns `function_call_output` before continuing speech.

## Validation

- 30 Gaussian API/mode/behavior tests passed, including manual-tool bypass and bounded head/gaze parsing.
- 11 web tests passed, including changing buffered happy articulation to a sad expression without losing lip-sync channels.
- 12 Gaussian worker tests passed.
- Both real ZIPs passed structural integration checks: all per-vertex attributes/morph counts agree, values are finite, indices are valid, and tongueOut affects exactly the 275 new tongue points without moving original facial vertices.
- Web production build and scoped ESLint passed; the renderer bundle-size warning remains non-blocking.
- Browser tests covered neutral, jaw 0.6, blink, head rotation and tongueOut; also actual Realtime/A2F playback in Auto and manual modes. Microphone capture was not part of this regression pass.

Live evidence:

| Session | Test | Result |
| --- | --- | --- |
| `dd336c8529a247b887fc9a36` | Auto distress, Seoyeon | LLM chose sad/supportive 0.7, pitch −4°, 392 motion frames |
| `ee27aa803220499498a48335` | Manual sad with positive input, Emma | Sad retained, browInnerUp max 0.4, smile max 0.012, 103 motion frames |
| `149f99b0e5d64462a8c80d73` | Browser manual sad | Selection survived connect; 178 frames, actual playback source `nvidia_a2f+manual_expression` |
| `201b42d452d74e3a960e5ce3` | Browser Auto positive news | LLM happy/celebrating 0.8, 185 frames; 7 captured playback telemetry samples, rendered smile max 0.1728 and jaw max 0.177 |

Artifacts are under `data/gaussian/identity-fit/`: `v2-ids.json`, `v2-asset-checks.json`, `v2-validation.json`, `*-v2-final-neutral.png`, `*-v2-final-measure.json`, `*-v2-final-mouth.png`, and live screenshots. Measurements use a full viewport screenshot and the explicitly checked 450×450 canvas crop at `[24,234,450,450]`; do not reuse this crop after scrolling/layout changes. Earlier candidate screenshots and source-color experiments are not final evidence. Logs are under `data/gaussian/sessions/<session-id>/` and downloadable from the UI.
