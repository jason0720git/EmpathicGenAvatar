# v5: bounded Happy corners and exclusive SDK ownership

2026-09-17. Supersedes v4's full lip restoration for Happy only.

## Happy

The v4 default restored points 14 and 20 along with the lip centers, removing
most of the smile. In `speech_safe`, Happy now uses y residuals -0.014 / -0.008
on those two points and -0.005 on cheek controls 3 / 7. Center points
6 / 12 / 17 / 19 still exactly match the same-frame baseline after stitching.
The final corner displacement is limited to norm 0.010 per point. Legacy
point-17 aperture/depth offsets remain disabled. Pupil controls are unchanged.
Intensity scales the residual; saturation can occur at the final safety cap.
Other emotions and comparison modes retain their previous behavior.

These are implicit keypoints, not isolated anatomical controls: preserving
center coordinates cannot guarantee every lip pixel or perfect speech closure.
The default is a moderate smile, not the legacy held-open broad grin.
Worker logs expose actual applied components, center protection, corner cap,
smile frame count and peak final corner displacement.

## Connection investigation and fix

The user's TRT10 container was exited with code 139, not OOM-killed. No native
crash stack was available for that original exit. During initial validation,
idle generation and live rendering overlapped and CUDA illegal-address errors
appeared in decoder/Hubert buffer handling. The realtime path did not acquire
the same lock used by prepare/idle. Cancellation also cancelled the asyncio
wrapper without stopping its native thread.

Realtime turns now hold that shared lock. Native render tasks are shielded;
on cancellation or producer failure they receive an input sentinel and are
awaited before the lock releases. This prevents another turn or idle setup
from resetting the SDK while the previous thread still owns it. TRT10 now has
bounded restart-on-failure (3) and Python fault-handler stacks enabled. This
does not prove all possible native crash causes are removed; a process that
is alive but unhealthy is not restarted by this restart policy.

## Verification

- 18 worker tests passed, including final corner bounds, lip-center invariance,
  intensity, exclusive turn scheduling and cancellation draining a real thread.
- Eight same-audio GPU renders completed after the locking fix, each with
  110 audio packets and 134 video frames.
- Web nginx → TRT10 single and concurrent Happy/Angry probes completed with
  media plus end markers, without restarting the worker.
- Speech/silence contact sheets in `artifacts/speech-ab-v5` were inspected:
  Happy has more smile than the off baseline, less than legacy amplification.
- No subjective claim that blur or Korean phoneme alignment is fully solved.

Reproduce: `python3 -m app.benchmark_affect --speech-ab` and
`python3 -m app.check_media_proxy --concurrent` inside the TRT10 worker.
Reload the site after deployment; choose Happy, 75–100%, 발음 보호. Use the
existing response-linked feedback panel for mouth blur, articulation mismatch,
weak expression or connection failure. No additional LLM/tool requests added.
