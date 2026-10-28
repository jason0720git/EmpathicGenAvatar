# Gaussian expression and oral material v7 — 2026-09-29

## Diagnosis and changes

- Previous manual presets limited primary affect channels to 0.3–0.65 even at 100% intensity. NaturalMotion further multiplied affect by 0.64–1.0. The browser and backend also had different preset values.
- A shared `apps/api/app/emotion_profiles.json` now defines whole-face action combinations. Each non-neutral emotion has a primary channel reaching 1.0 at 100%. Supporting brow, eye, cheek, nose and mouth actions differ by emotion. This is the rig's nominal range, not a measured physiological maximum or a claim to reproduce all motion in a recorded example.
- Resting mouth shapes now distinguish happiness, fear, surprise and anger. All speech articulation channels remain owned by A2F; only mouth corners retain the selected affect. NaturalMotion varies affect over time up to near-full peaks, without overriding lip synchronization.
- Natural blink pulse: 190 → 380 ms; fallback preview: 150 → 300 ms; server idle: 180 → 360 ms. Blink frequency unchanged.

## Emma oral appearance

The visible native LAM mouth has pale/blue-gray reconstructed internal splats; the independently added tongue from older experiments remains disabled. A selected region of jaw-driven inner tissue and recessed, stationary oral backing is chroma-calibrated to muted warm tissue colors. Masks use 3D position and deformation, with smooth falloffs. No projected image patch or supplemental surface is used.

The visible upper crown band and rigid lower dental arc are excluded by the calibration mask. This is a conservative appearance heuristic, not anatomical segmentation. Geometry, morph buffers, opacity and Gaussian scales are byte-identical to the preceding asset. 77 splats have mask weight above 0.01; 68 have a channel change above 0.01. There is still no separately articulated anatomical tongue, and the single-image reconstruction still limits oral detail at extreme poses.

Applied to Emma `2a80fe76d5f44beba2a3c0ac` only. Original asset and record are preserved as `asset.pre-material-v7.zip` / `record.pre-material-v7.json`. Reproducible script: `workers/gaussian/calibrate_oral_material.py`. Material version/count appears in rig diagnostics and playback telemetry. The anatomical-tongue control remains disabled.

## Validation

- Web Gaussian tests: 23 passed. API Gaussian tests: 51 passed, 1 skipped. TypeScript/Vite build passed. Targeted ESLint passed.
- Regression tests cover doubled blink duration, unchanged blink cadence, full-range expression endpoints, natural-motion full-strength peaks and preserved A2F articulation.
- Browser: Emma six emotion poses at 100%, actual uploaded rig values checked before capture. Official GaussianAvatars 306: all six poses rendered with the same profiles.
- Ash English WAV: session `209a8f948304482ca63de3d5`, 4.6 sec, 220800 PCM bytes, 139 A2F frames; happy 100% with natural motion. `turn.done` and no error events.
- Artifacts: `artifacts/oral-v7/emma-expressions-100.png`, `official-expressions-100.png`, `material-validation.json`, `studio-verified.png`.
