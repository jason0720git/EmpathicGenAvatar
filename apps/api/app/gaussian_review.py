"""Summarize a saved recording without changing the original trace."""
import json
import math
from collections import Counter
from pathlib import Path


def mapping(value):
    return value if isinstance(value, dict) else {}


def summary(directory: Path) -> dict:
    config = json.loads((directory / "session.json").read_text(encoding="utf8"))
    result = {k: config.get(k) for k in ("id", "created_at", "mode", "avatar_id", "avatar_sha256",
                                          "avatar_engine", "render_driver", "controller")}
    counts, stages, policies, drivers = Counter(), Counter(), Counter(), Counter()
    turns, ranges, errors, control_settings = {}, {}, [], []
    invalid = 0

    def measure(key, value):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            return
        stats = ranges.setdefault(key, {"min": value, "max": value, "n": 0, "sum": 0.})
        stats["min"] = min(stats["min"], value)
        stats["max"] = max(stats["max"], value)
        stats["sum"] += value
        stats["n"] += 1

    with (directory / "events.jsonl").open(encoding="utf8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1  # snapshot during append or interrupted write
                continue
            event = mapping(row).get("event")
            if not isinstance(event, str):
                invalid += 1
                continue
            counts[event] += 1
            d = mapping(row.get("details"))
            tid = row.get("turn_id")
            if event in ("turn.error", "command.error") and len(errors) < 20:
                errors.append({k: d.get(k) for k in ("class", "message")})
            if tid and event in ("wav_test.input", "behavior.plan", "turn.done", "turn.cancelled"):
                turn = turns.setdefault(tid, {})
                if event == "wav_test.input":
                    turn.update({k: d.get(k) for k in ("filename", "pcm_sha256", "control")})
                elif event == "behavior.plan":
                    turn["plan"] = d
                elif event == "turn.done":
                    turn.update({k: d.get(k) for k in ("first_audio_ms", "first_motion_ms", "duration_ms", "animation_frames")})
                else:
                    turn["cancelled"] = True
            if event not in ("playback.telemetry", "preview.telemetry"):
                continue
            tag = d.get("event")
            if isinstance(tag, str) and tag.startswith("policy."):
                policies[tag] += 1
            if tag != "motion.sample":
                continue
            stage = d.get("tracking_stage")
            stage = stage if stage in ("displayed", "requested") else "unspecified"
            stages[stage] += 1
            settings = mapping(d.get("settings"))
            if settings and (not control_settings or settings != control_settings[-1]):
                control_settings.append(settings)
            frame = mapping(d.get("rendered_frame"))
            head = mapping(frame.get("head"))
            motion = mapping(d.get("headMotion"))
            if isinstance(motion.get("driver"), str):
                drivers[motion["driver"]] += 1
            for axis in ("pitch", "yaw", "roll"):
                measure(f"{stage}_command_{axis}_deg", head.get(axis))
                measure("renderer_" + axis + "_deg", mapping(motion.get("applied")).get(axis))
            measure("renderer_torso_drift_mm", motion.get("torsoDriftMm"))
            for name in ("browInnerUp", "eyeBlinkLeft", "cheekSquintLeft", "mouthSmileLeft", "mouthFrownLeft", "jawOpen"):
                measure(f"{stage}_{name}", mapping(frame.get("weights")).get(name))
            measure("renderer_compute_ms", d.get("renderMs"))
            measure("renderer_round_trip_ms", d.get("roundTripMs"))
            measure("sync_timeouts", d.get("sync_timeouts"))
    for stats in ranges.values():
        stats["mean"] = stats.pop("sum") / stats["n"]
    return {**result, "schema": 1, "motion_samples": sum(stages.values()), "sample_stages": dict(stages),
            "head_drivers": dict(drivers), "sampled_ranges": ranges, "events": dict(counts),
            "policy_events": dict(policies), "settings_history": control_settings,
            "turns": turns, "errors": errors, "incomplete_lines": invalid}
