# Native eight-channel expression presets

> Historical v2 notes. Current implementation and research: [v3 calibration](native8-expression-v3.md).

The public UI, API and Realtime function enum use Ditto's native order:
angry, disgust, fear, happy, neutral, sad, surprise, contempt.
Old joy/warm/concern/apology values are no longer accepted; reload the UI and
start a new live session after deployment so its tool schema is refreshed.

## Implementation

The eight-channel interface is rendered with `native8-speech-brow-v2`.
These experimental residuals adapt the smile, eyebrow and lip controls in
`vendor/LivePortrait/src/gradio_pipeline.py` to Ditto's 21x3 expression offsets,
flattened to `(1, 63)`. They are not a learned or universally calibrated emotion
classifier. They are applied through `ctrl_motion`, after MotionStitch's
source-expression masks, so the mouth/brow offsets survive those masks.

Ditto normally retains the source expression outside the lip region and replaces
eye motion with source/blink controls. This explains why an emotion input alone
does not necessarily produce a conspicuous face expression. The old arbitrary
20-point presets are removed. Points 11, 13, 15, 16 and 18 (the upstream eye group)
receive zero direct residual. This does not guarantee zero indirect deformation.

Manual gain is 1.0; auto gain is 0.35. Intensity scales the residual, with an
attack/release envelope. The existing streamed-turn duration estimate remains
30 seconds, so its final release is not guaranteed to coincide with speech end.
Independent pupil control is not implemented; gaze remains a pose cue.

### Speech-safe v2 changes

- Happy, Angry and Neutral residuals are unchanged.
- Surprise and Fear have zero direct residual at all upstream lip points
  (6, 12, 14, 17, 19, 20). Their Audio2Motion emotion condition is **Neutral**,
  intentionally: native Fear/Surprise motion still produced smiling/open-mouth
  bias in the first same-audio test despite zero lip residuals. The selected
  emotion remains Fear/Surprise in the plan, rendered by distinct brow offsets.
  This is not a claim that Ditto independently supports separate lip emotion.
- Surprise's brow reaction peaks for the first 0.5 seconds, then exponentially
  settles toward 65% with a 0.7-second time constant. No Happy nod is attached.
- Fear uses raised, inward-tension brows; Sad uses milder tension and lowered
  lip corners. Disgust uses asymmetric contracted brows/downturned corners;
  Contempt uses a stronger unilateral corner lift and asymmetric brow.
- Retuned states do not add lip-center/jaw offsets. Corner offsets can still
  indirectly affect lip shape: no preset is guaranteed perfectly lip-sync safe.
- No extra LLM call, prompt field or token cost was added. Manual mode still
  skips the affect tool; automatic mode retains the existing tool contract.

## Verification and limits

Run `python3 -m app.benchmark_affect` in the TRT10 worker. It renders all eight
states with identical synthetic speech and zero pose/nod, saving full short
videos, frames at 1/2/3 seconds and a 2-second contact sheet under
`/data/benchmarks/native8-v2`. One second of silence is appended, with a second
contact sheet sampled 400 ms into that silence. No external LLM tokens are used.

On demo-seoyeon, the v2 run produces 134 video frames and 110 audio packets per
state. Fear/Sad and Disgust/Contempt remain less reliable semantic distinctions;
the eight labels should not be interpreted as eight equally strong or
production-calibrated performances. Audio2Motion sampling is stochastic,
so this comparison controls the audio and pose but not all model randomness.
The final v2 silence sheet shows closed lips for both Fear and Surprise, unlike
the initial v2 attempt using their native emotion condition. Disgust still has
a teeth-showing bias and Contempt is subtle: these remain experimental presets,
not a solved eight-way recognizable emotion set. Check the early reaction and
the speaking video as well as stills; a 2-second frame misses Surprise's peak.

The worker log `/data/telemetry/ditto-affect-applied.jsonl` records the preset
version, gain, protected points and residual magnitude. It records prepared SDK
inputs, not perceptual recognition or proof that a human sees the named emotion.
For Fear/Surprise the recorded dominant emotion index is intentionally 4
(Neutral); the requested expression and v2 residual still identify the selected
emotion. Unit tests check protected eyes, protected lips, neutral conditioning,
reaction decay and the absence of a Surprise nod. These plus rendered comparisons
are regression checks, not a formal audiovisual synchronization score.
