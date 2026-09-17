# Component-calibrated expressions v3

Version: `native8-component-calibrated-v3` (2026-09-17).
Public enum unchanged. No additional LLM calls, schema fields or keyword policy.

## Why v2 was weak

Fear, Sad and Surprise mostly shared a brow-elevation scalar. Removing all eye
and Fear/Surprise lip residuals protected articulation but also removed useful
distinguishing cues. Point 20.y had been described as a one-sided lip corner:
the empirical sweep shows it changes mouth aperture. Implicit keypoints are
neither anatomical landmarks nor independent FACS action units. A coordinate
can influence several regions; indices 14/20 are not a left/right pair.

Ditto MotionStitch retains the source's non-lip expression and uses source blink
motion for eyes. Our residual runs after these masks. Raising the emotion
condition alone cannot reliably overcome the retained source upper-face pose.

## Literature and implementation evidence

- [LivePortrait paper](https://arxiv.org/abs/2407.03168): implicit-keypoint
  deformation with stitching and retargeting, not an anatomical AU interface.
  [Official editor](https://github.com/KlingAIResearch/LivePortrait/blob/main/src/gradio_pipeline.py)
  provides starting smile/brow controls, but combinations require measurement
  in the actual renderer and avatar.
- [Ditto paper](https://arxiv.org/abs/2411.19509) and
  [official MotionStitch](https://github.com/antgroup/ditto-talkinghead/blob/main/core/atomic_components/motion_stitch.py):
  conditioning, source/driver mixing, eye/lip masks, additive residual,
  pose compensation and stitching are different stages. Their local ordering
  was inspected before changing controls.
- [NetFACS, Mielke et al.](https://link.springer.com/article/10.3758/s13428-021-01692-5):
  in its posed-expression dataset, brow actions are shared across emotions;
  informative cues include AU20 for fear, AU2/AU5 for surprise, AU15 for sadness,
  and AU14 for contempt. Combinations matter; associations are probabilistic,
  not a universal emotion detector. These guide goals, not numeric offsets.
- [Dynamic Facial Expression of Emotion and Observer Inference](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2019.00508/full):
  considers configurations and temporal development, not only single static
  actions. Our reaction timing is an engineering choice, not a paper constant.

## Empirical calibration

`python3 -m app.calibrate_affect` renders the same source and pose, without
Audio2Motion randomness: 27 coordinates x two signed perturbations (+/-0.008),
plus baseline. Saves all 55 portraits, sheets and MediaPipe blendshape proxies.
These proxies are not ground-truth FACS and do not prove emotion recognition.

On demo-seoyeon, 13.y/16.y can open both lids; 14.y influences bilateral
smile/frown; 20.y affects aperture; 20.x plus opposing 3.y/7.y produces useful
mouth asymmetry. These are source-specific empirical observations, not
universal anatomical mappings. Final coefficients were visually checked.

## Controls

| State | Distinguishing combination | Speech safeguards |
|---|---|---|
| Fear | Raised/contracted brows, moderate lid opening, restrained mouth tension | No jaw-center offsets; neutral motion condition |
| Sad | Inner-brow elevation/tension impression, stronger downturned mouth, no lid widening | No jaw-center offsets |
| Surprise | Widest bilateral lid opening, raised but uncontracted brows | All lip offsets zero; neutral motion condition; no nod |
| Contempt | Asymmetric cheek/mouth pull with lateral/depth deformation, not a bilateral grin | No aperture offset at 20.y; no jaw-center offsets |

Happy, Angry, Neutral and Disgust residuals are unchanged from v2.
The four retuned states keep 6/12/17/19 at zero. Pupil coordinates 11/15 and
eye-group point 18 remain untouched. Only positive y offsets are allowed at
lid controls 13/16 (maximum 0.010/0.006 at manual 100%). Indirect deformation
remains possible because the representation is coupled.

`BlinkAwareMotionStitch` attenuates only lid-opening residuals using the native
blink trajectory, reaching zero at maximum closure. It does not mutate cached
controls or native blink motion. Vendor files are unchanged. Unknown/no-blink
schedules leave the residual unchanged.

Manual gain is 1.0. Auto gain is 0.65 for the retuned four (previously 0.35), and
0.35 for the others. Intensity scales linearly. Surprise holds peak for 0.5 s,
then settles toward 85% with a 0.7 s time constant. Existing attack/release
envelopes remain. Streaming still estimates a 30 s turn; its final release does
not necessarily coincide with speech end. Independent pupil control is not
implemented; gaze intent remains a small pose cue plus upstream compensation.

## Verification

- `calibrate_affect --presets-only`: fixed-source/pose comparison.
- `calibrate_affect --blink`: actual native blink with Fear/Surprise; all 15
  stages saved. Both eyes close/reopen in inspected renders. This deliberately
  schedules a blink: a short random talking clip does not guarantee one.
- `benchmark_affect`: identical synthetic speech + 1 s silence, eight states,
  manual intensity 1, zero extra pose/nod. TRT10 produced 134 frames and 110
  audio packets per state. Outputs: `/data/benchmarks/native8-v3`; v2 preserved.
- `audit_affect_video`: 67 frames per retuned state and Neutral. Median eye
  aperture increased for Fear and most for Surprise. Sampled final-silence
  mouth gaps were below 0.005 mouth widths for all four. Geometry diagnostics
  are not a formal audiovisual synchronization score.
- Unit tests: shape/bounds, pupil protection, allowed lid axes, protected jaw,
  Surprise lip protection, gain/intensity, blink attenuation, immutable cached
  controls, and structurally distinct component combinations.

Rendered separation improved: wide-eyed Surprise, frowning Sad and unilateral
Contempt. Fear remains a tense/worried approximation, not a fully calibrated
AU20 performance. No human recognition study or multi-avatar validation was
performed. Audio2Motion sampling is stochastic; only the static sweep fully
isolates parameter changes. Manual token bypass remains unchanged.

## Logs

`/data/telemetry/ditto-affect-applied.jsonl` now includes all nonzero base
components and blink-aware lid points, alongside version, gain, intensity and
condition weights. Fear/Surprise intentionally use native index 4 (Neutral),
with the requested affect supplied by residuals. These are SDK-input logs,
not proof of perceptual emotion recognition.
