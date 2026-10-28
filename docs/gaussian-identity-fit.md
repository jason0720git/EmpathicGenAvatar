# Photo identity fitting — 2026-09-28

Final library entries:

| Avatar | ID | Baseline |
| --- | --- | --- |
| 서연 · 원본 정합 최종 | `18b71a0877154454921e80c2` | `57f19b81b75546458028bbf2` |
| Emma · 원본 정합 최종 | `e125a4186373447aa784a7f2` | `77fac2aa3a8e4141a296cc53` |

## Method

Preserve each original source photo, learned LAM texture, source camera, skeleton and 51 expression channels. Detect 68 landmarks in the source and a neutral browser render. Align eye centers using a similarity transform, then fit the remaining local residual with a regularized smooth RBF deformation in the source camera plane. Boundary anchors and front-depth gating limit spill into the rear head and neck; displacement is capped at 6 mm. Apply the same deformation to Gaussian centers, mesh anchors, morph targets and Gaussian covariance. Reject folded/non-finite transformations. Do not apply the rejected blanket lower-face shortening profile.

This is per-identity calibration from measurements, with no ethnicity-specific deformation rule. It is not another image-generation pass or a painted overlay.

## Fresh rendered measurements

Errors are mean landmark distances divided by eye-center distance, expressed as percentages. Lower is better. These measure fit to the same photo landmarks used for calibration; they are **not recognition accuracy, likeness percentages, or an independent generalization benchmark**.

| Avatar | All 68, before → after | Mouth, before → after | Contour, before → after |
| --- | --- | --- | --- |
| Seoyeon | 5.47% → 2.22% | 7.44% → 2.34% | 9.12% → 3.95% |
| Emma | 4.91% → 2.20% | 4.85% → 2.04% | 8.70% → 4.39% |

Emma's eye-region error changed from 0.63% to 0.67%; not every region improved. Maximum point displacement is 6 mm. Minimum deformation Jacobian determinant is 0.6833 for Seoyeon and 0.6805 for Emma, above the 0.2 rejection threshold.

## Verification and evidence

- Worker suite: 12 tests passed, including similarity alignment, identity deformation, displacement bound, rear-neck preservation, camera, export and calibration tests.
- Gaussian web suite: 9 tests passed. Production TypeScript/Vite build and Gaussian ESLint passed. Build retains a non-blocking renderer bundle-size warning.
- Manual browser checks for both final assets: neutral source view; blink 0, 0.5 and 1; jaw 0.3; yaw +12° and −8°. Fixed-pose captures verify the rig remains usable. The former large iris patches above fully closed lids were not observed in these tested views. Fine pale/grainy eyelid edges remain, especially during partial closure; this is not a claim of flawless animation at every pose.
- Live Realtime → NVIDIA A2F tests: Seoyeon session `728eddb581f84a77b3b5e813`, 7 audio chunks / 85 motion frames / max jaw 0.678; Emma session `a778a3fc265142d6bc66032e`, 6 audio chunks / 64 motion frames / max jaw 0.642. Both completed and exported logs. These tests used text input to obtain streamed speech and animation; they did not test microphone recognition or human-rated lip-sync quality.

Evidence directory: `data/gaussian/identity-fit/`. Authoritative files are `*-baseline.json`, `*-final-measure.json`, `*-before-full.png`, `*-after-full.png`, `*-motion-full.png`, `*-half-blink-full.png`, and `validation.json`. Session logs are in `data/gaussian/sessions/` and summaries in `data/gaussian/smoke-<session-id>.json`.

Early captures without `-full` had a browser clip/scale mismatch and are **invalid for comparison**. Their candidate assets were replaced; all reported numbers come from full-viewport captures with an explicit `[24,234,450,450]` analysis crop. This crop is specific to the captured viewport; measure the actual canvas again after a layout change.

## Reproduction

Use `workers/gaussian/measure_identity.py` in the Gaussian worker to measure the original source and neutral screenshot (`--render-box X Y W H`). Pass that measurement and the original baseline avatar directory to `fit_identity_asset.py`. Never fit an already-fitted ZIP. Load the resulting asset in `/gaussian/rig-check`, capture a fresh neutral render, and measure again before publishing it. The embedded `identity_fit.json` records generation-time provenance; the avatar record and external `validation.json` record the subsequent validation.

## Remaining limits

Single-photo LAM reconstruction still changes skin texture, fine eye/lip details, hair and unseen geometry. The correction is constrained to a source-view facial landmark fit, not multiview photometric optimization. Camera rotation cannot by itself restore details already lost during reconstruction. Frontal similarity improved for these two examples; no claim is made about ethnic-group performance or exact photo reproduction.
