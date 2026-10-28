# Expression debugging — 2026-09-28

## Reproduction and evidence
- Recording: bandicam 2026-09-28 15-23-07-302.mp4; sampled at 1, 15, 28, 46 seconds.
- Original session: 7475e4d4e1a14de5b4a2f3b2 (Emma v2).
- LLM plans: happy .75, sad .70, happy .80. Browser telemetry already contained distinct coefficients. This was not a missing LLM connection.
- Original speaking smile: .48 × .75 × .45 = .162; frown: .28 × .70 × .45 = .0882. The speech-only .45 multiplier suppressed intended affect.
- SDK calibration further scales frown by 1.3, jaw by 1.2, and mouthClose by .2. Requested values and applied values are not always identical by design.
- Controlled browser rig check: sad brow requested .48 / SDK .48 / upload .479999989; frown .28 / .364 / .363999993. Happy smile .52 / .52 / .519999981. All 52 channels exist.
- Visual inspection shows restrained changes, especially eyebrows. Nonzero buffer values do not prove perceptually strong emotion. A single photo rig has identity-dependent spatial expression response; no ethnicity-specific cause was established.
- Auto switches to neutral attentive policy after playback; expressions are not held indefinitely.

## Changes
- Removed speech-only mouth-corner attenuation; articulation channels and negative-emotion smile guard preserved.
- Happy/sad primary targets now match manual preview (.65 smile; .60 inner brow / .35 frown before intensity).
- Renderer statistics report requested, SDK-applied, and CPU-side GPU upload buffer weights, missing-channel status, and full-weight maximum morph displacement in mm. This is not GPU readback or a visible-landmark measurement.
- Main studio displays these side by side under execution diagnostics. Existing playback.telemetry records the rig snapshot once per second into events.jsonl and logs.zip.
- Rig-check page includes JSON diagnostic values without a conversation dependency. Morph displacement extrema are cached at load time.
- Live browser test also exposed head.nod schema drift. Normalize known head.tilt/head.nod aliases while retaining angle bounds and rejection of conflicting/unknown fields; record behavior.normalized events.

## Verification
- Backend expression/schema regression tests: 12 passed; frontend manual-expression tests: 2 passed.
- TypeScript + production build passed; changed Gaussian TypeScript files pass ESLint.
- Whole-project lint fails in unrelated existing files (App.tsx, TurnDiagnostics.tsx, api.ts, avatarTransition.ts and others); no blanket clean-lint claim.
- Live Auto integration: session 479a6305886c494d8dad85cd; happy .80; smile max .52; 53 motion frames and 84,000 PCM bytes.

## Remaining limits
The upload buffer confirms delivery, not final pixel quality. Small avatar framing and spatially weak portrait rig expressions can still look subtle. Further perceptual tuning should use matched camera/pose neutral-versus-expression comparisons, not indiscriminate gain on jaw or blink.

- Post-fix browser session: 0136fc02a934491a887878f7. Happy .70: requested / applied / uploaded smile .455 / .455 / .455000013. Full evidence: data/gaussian/expression-debug-validation.json.
