# Eye / mouth visibility repair — 2026-09-29

## Finding and correction of earlier assumption
Reviewed the supplied 9.13-second Bandicam recording. The previous supplemental crowns remained conspicuously detached. LAM's official FlameHead defaults add_teeth=True and constructs upper/lower dental surfaces with separate attachment. The earlier statement that LAM has no oral geometry was incorrect. Source: https://github.com/aigc3d/LAM/blob/master/lam/models/rendering/flame_model/flame_arkit.py . This does not imply detailed dental anatomy can be recovered from a closed-mouth photo, or that every export is artifact-free.

Native-vs-supplemental browser comparison showed the original oral representation already contains dental appearance. The supplemental surface and elliptical replacement mask were introducing a separate appearance/motion system. Default rendering now suppresses all 890 supplemental points and bypasses the replacement mouth mask, keeping the original learned mouth with its native morphs. This deliberately disables the supplemental tongueOut too; diagnostics no longer advertise it as active. The optional rig-check checkbox can compare the old supplemental path, which remains experimental. No amplitude reduction or disabling of speech was used to hide the issue.

## Eye correction
The old position-only alpha mask failed to distinguish eyeball splats from eyelid splats. In addition, iris color was baked into some moving lid points. For the two calibrated avatars the shader now distinguishes gaze-moving / blink-stationary globe points from moving lids using morph deltas. Globe opacity fades on closure, while the closing lid uses an identity-specific neighboring skin color and eyelash seam. Eye-wide and gaze channels are suppressed during closure. This is a rig classification and appearance correction, not new multi-view eye reconstruction. Uncalibrated avatars retain the old fallback.

prepare_visibility_v4.py writes per-identity eyeSurface metadata, sampling color above each eye and locating closed-lid seam from learned offsets plus blink deformation. Backups asset.pre-visibility-v4.zip and record.pre-visibility-v4.json retained. All positions and all morph arrays exactly unchanged in both assets.

## Validation
18 existing Gaussian frontend tests passed; scoped lint and production build passed. Visual checks: Emma full closure and jaw .30/.60; Seoyeon full closure, surprise+closure at yaw +20, native jaw .60 at yaw +20. The closed-eye screenshots no longer show the iris ghost. Native mouth remains soft at large openings; this is not a claim of fully reconstructed teeth/tongue.

WAV session b8497a2f3689447d84270f2d: 4.65s, 140 A2F frames, no turn errors, no LLM call. Telemetry confirms rig-globe-and-lid-appearance and native-lam-oral. Captures in data/gaussian/review-0929. The main page displays and logs both policy identifiers for subsequent debugging.

## Remaining limits
The floating procedural teeth are disabled, not upgraded into anatomical teeth. Native inner-mouth detail is blurry and the eyelid closure appearance is approximated from neighboring skin. Detailed oral/eyelid geometry would require a better reconstructed asset or a trained multi-view model. The current checks do not prove arbitrary expressions/views artifact-free.
