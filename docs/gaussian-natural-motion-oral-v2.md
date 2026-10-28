# Natural motion and oral v2 — 2026-09-28

## Reproduction
Recording: bandicam 2026-09-28 16-22-31-466.mp4. Reviewed 1/4/5/6/10/12/14/18/19-second samples and mouth crops.
ManualSpeechFrame deliberately replaced head/gaze and upper-face expression with static manual targets; it preserved only speech articulation. The backend's tiny idle head overlay was therefore discarded in WAV/manual playback.
Reference inspected (read-only): SOBIA-Unity/SharedPackages/com.etri.sobia/Runtime/EmpathicBehavior/Base/BaseHeadMotion.cs and BaseBlink.cs. SOBIA separates baseline idle, speaking vitality, smoothing, angular speed limits, and timed blinks. This implementation adapts those concepts; it is not a complete port of Unity full-body controllers.

## Motion changes
NaturalMotion is the final playback-time additive layer shared by Auto, manual, WAV and disconnected preview. Default enabled; UI checkbox allows comparison. Separate smoothed idle and talking head offsets, bounded speeds, drifting eye contact, irregular blink intervals, smoothed affect envelopes and energy-driven brow accents. Jaw/funnel/pucker and tongue articulation values are unchanged.
Audio energy comes from 20ms PCM windows (continuous across chunk boundaries), is interpolated on the audio timeline, and influences speaking motion. Continuity uses a monotonic clock across turns. Stops and pauses decay speech activation instead of freezing a pose.
Telemetry logs natural_motion, speech energy, head offsets, blink, oralVersion, oralAperture and oralOpen. UI shows live head angles, energy and oral version.

## Oral root causes and corrections
V1 upper crowns extended upward from the mouth seam while the jaw-only mask clipped above that seam; whole-Gaussian clipping could erase crowns abruptly. Its jaw mask also used raw weights although the SDK scales jawOpen by 1.2 and mouthClose by .2.
V2 corrects crown direction, tooth spacing/shading and tongue depth. Aperture is computed from identity-specific lip anchors and their actual morph deltas, using SDK-calibrated weights. Upper/lower anchors are selected from distinct jaw-deformation regions so a closed-mouth portrait cannot bind both lips to the same surface.
Per-fragment projected clipping replaces whole-splat removal; it follows head pose and lip geometry. Legacy inner-mouth points are suppressed within the opening instead of recoloring their overlapping white blobs as tissue.
Emma and Seoyeon current v2 entries upgraded in place. Full asset.pre-oral-v2.zip and record.pre-oral-v2.json backups retained. Exact comparisons confirmed original 20,018 face vertices and all morph deltas unchanged. Only supplemental oral surface geometry/colors and metadata changed.
Reproducible upgrader: workers/gaussian/upgrade_oral_v2.py.

## Validation
31 backend tests, 6 targeted frontend tests passed; production build and scoped lint passed. Browser checked Emma jaw .30/.60 and Seoyeon jaw .60 at frontal and +20 degree yaw; no shader compilation errors. These large opening tests are stress cases.
Live Emma WAV session: 173386866af044a2af2249ca. Five speaking telemetry samples show energy .084–.850, pitch .330–1.072 degrees, yaw -.422–.380, roll -.292–.190; continued idle motion recorded separately. No turn errors. See data/gaussian/natural-motion-validation.json.

Live Seoyeon sad WAV session: 7d7555b81d0147f3804e9ffb. Completed 4.65 seconds / 140 motion frames, no turn errors, no LLM invocation. Speaking energy and all three head axes varied; see data/gaussian/natural-motion-validation-seoyeon.json. Final browser: 59 FPS, zero playback underruns/sync timeouts, no console errors.

## Limits
Supplemental teeth/tongue are generic procedural geometry, not dental anatomy recovered from a closed-mouth photo. Broad opening stress views still have a synthetic-looking cavity/crown shape. This fixes identified clipping/overlap and motion-composition faults; it does not establish artifact-free photorealism at every pose, nor add a full-body rig. A real oral scan/multiview asset or a validated mesh-mouth renderer would be needed for that stronger claim.
