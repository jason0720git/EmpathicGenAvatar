# Facial expression and conversational dynamics audit — 2026-09-29

## Findings and corrections

The previous input/GPU check did not establish that emotion combinations were good. A full native-rig audit and SDK inspection found hidden multipliers: jawOpen 1.2, mouthClose 0.2, mouthShrugUpper 0.1, mouthLowerDown 0.7, and multiple lip channels 1.3. The renderer now explicitly sets all 52 channel scales to 1 and offsets to 0. A browser sweep verified requested → SDK → uploaded values of 1 for all 52 channels. This fixes coefficient interpretation, not the quality of the underlying learned deformation.

Native Emma and Seoyeon assets have 51 visibly deforming fields. `tongueOut` has zero deformation within the 20,018 native splats; its older supplemental geometry is hidden. Diagnostics now report this as no visible deformation. No new tongue geometry is claimed or introduced.

Shared `apps/api/app/emotion_profiles.json` defines eight profiles (neutral plus seven emotions). Full intensity means the calibrated profile endpoint, with defining channels reaching 1, rather than setting all antagonistic muscles to 1. Browser contact sheets reviewed both Emma and Seoyeon. The first angry candidate produced a smile-like lip corner due to mouthPress/roll coupling, so press was reduced from .65 to .12, rolls from .3 to .08, and frown increased from .2 to .65. This is an inspected engineering calibration, not an exhaustive mathematical search or a human-validated emotion optimum.

## SOBIA-derived motion

Read-only references in SOBIA-Unity: `EmpathicEmotion.SpeechDynamics.cs`, `Interaction/CausalProsodyTracker.cs`, `Base/BaseHeadMotion.cs`, and `EmpathicEmotion.cs` under `SharedPackages/com.etri.sobia/Runtime/EmpathicBehavior`.

`CausalProsody` tracks normalized, audio-aligned 20 ms energy windows with fast attack, slower release, local prominence, accent refractory periods and silence boundaries. `NaturalMotion` layers accents onto smooth head orientation, gaze shifts, independent brow/eye/cheek/corner envelopes, asymmetry, and idle micro-movements. It retains the 380 ms blink pulse. A2F upper-face changes are reintroduced as bounded high-pass residuals; raw coefficients are interpolated at playback time.

Speech articulation retains ownership of jaw, lip rounding and articulation channels. Emotional smile is attenuated during rounded vowels, negative expressions suppress smile/dimple, and eye widening suppresses squint. This is procedural, audio-conditioned motion; it is not captured human motion or a newly trained empathy model. Auto keeps LLM behavior selection upstream; manual WAV mode keeps the selected emotion upstream. Both use this same playback controller.

`움직임 생동감` controls the dynamic layer from 0–150%. Expression intensity controls the profile endpoint separately. At 100% intensity with dynamics enabled, muscles contract and relax; they are deliberately not held at their maximum continuously. `/gaussian/rig-check` supports static maximum, every single channel, channel ablation and idle dynamics preview.

## Diagnostics and evidence

- All-channel requested/SDK/GPU values, visible support and maximum vertex displacement.
- Logged source `sobia_causal_dynamics_v8`, energy, accent, boundary, accent count, per-region envelopes, measured residual peak, head offsets and blink.
- Browser WAV sessions `138c4cac97e046639837c5fb` and `3f6199ce78a9497bbb22439c`: Ash English male, 4.6 seconds, 139 A2F frames, 19 audio chunks, zero synchronization timeouts; speaking telemetry confirms v8 and changing facial groups/head offsets.
- `artifacts/dynamics-v8/emotion-contact.png` and `seoyeon-contact.png`: static full-strength browser renders.
- `gpu-channel-audit-calibrated.json`: calibrated 52-channel sweep. `seoyeon-emotion-gpu-audit.json`: native Seoyeon profile checks. Earlier `emotion-gpu-audit.json` predates the final angry correction; final screenshots use the correction.
- `validate_dynamics.cjs`: replays recorded Ash coefficients through the actual TypeScript controller at 60 Hz, with articulation-preservation and finite/range assertions for all eight emotions. Happy speech spans: browInnerUp .148, cheekSquint .265, smile .223; head pitch 2.66°, yaw 2.65°, roll 1.09°. These are this short sample's ranges, not global motion limits.
- `render_dynamics_replay.py`: renders the replay with the official 306 GPU checkpoint and muxes the source WAV, with 2 seconds of leading idle. `official-causal-dynamics.mp4` contains 258 rendered frames. This is a controller replay, not a browser screen recording. Official ARKit→FLAME retargeting is approximate and does not imply equivalent expressive range to the original captured sequences.

Validation: 29 frontend tests passed; 51 backend tests passed, 1 skipped; targeted ESLint and production build passed. Existing large-renderer-chunk and httpx deprecation warnings remain. An end-to-end paid Realtime/LLM call was not repeated; WAV verified the changed downstream expression and animation path.

## Reproduction

Run `node workers/gaussian_lab/validate_dynamics.cjs`, then `.venv/Scripts/python.exe workers/gaussian_lab/render_dynamics_replay.py` with the official live renderer on port 8041. Native deformation audit: `workers/gaussian_lab/audit_blendshapes.py`.

In the studio, select an avatar, enter WAV mode, connect, select Ash, set expression intensity to 100%, select an emotion, and replay. Compare dynamics off/on or 100–150% vitality. Use the rig checker for a stationary profile endpoint. Logs remain in `data/gaussian/sessions/<session-id>`.
