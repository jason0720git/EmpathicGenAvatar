"""Read durable session events, including old or interrupted runs, without mutating them."""
import json
import math
from collections import Counter
from pathlib import Path


def summary(path: Path):
    cfg = json.loads((path / "session.json").read_text(encoding="utf8"))
    result = {k: cfg.get(k) for k in ("id", "created_at", "mode", "avatar_id", "avatar_sha256",
                                      "avatar_engine", "render_driver", "controller")}
    counts, stages, policies, drivers = Counter(), Counter(), Counter(), Counter()
    turns, ranges, errors = {}, {}, []
    samples = invalid = 0

    def measure(key, value):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            return
        stats = ranges.setdefault(key, {"min": value, "max": value, "n": 0, "sum": 0.})
        stats.update(min=min(stats["min"], value), max=max(stats["max"], value),
                     n=stats["n"]+1, sum=stats["sum"]+value)

    log = path / "events.jsonl"
    with log.open(encoding="utf8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1  # snapshot during append or truncated final row
                continue
            event = row.get("event")
            counts[event] += 1
            d = row.get("details") or {}
            tid = row.get("turn_id")
            if event in ("turn.error", "command.error"):
                if len(errors) < 20:
                    errors.append({k: d.get(k) for k in ("class", "message")})
            if tid and event in ("wav_test.input", "behavior.plan", "turn.done", "turn.cancelled"):
                turn = turns.setdefault(tid, {})
                if event == "wav_test.input":
                    turn.update({k:d.get(k) for k in ("filename","pcm_sha256","control")})
                elif event == "behavior.plan":
                    turn["plan"] = d
                elif event == "turn.done":
                    turn.update({k:d.get(k) for k in ("first_audio_ms","first_motion_ms","duration_ms","animation_frames")})
                else:
                    turn["cancelled"] = True
            if event not in ("playback.telemetry", "preview.telemetry"):
                continue
            tag = d.get("event")
            if isinstance(tag,str) and tag.startswith("policy."):
                policies[tag] += 1
            if tag != "motion.sample":
                continue
            samples += 1
            stage = str(d.get("tracking_stage") or "unspecified")
            stages[stage] += 1
            f = d.get("rendered_frame")
            f = f if isinstance(f,dict) else {}
            for axis, value in (f.get("head") or {}).items():
                if axis in ("pitch","yaw","roll"):
                    measure(f"{stage}_command_{axis}_deg", value)
            hm = d.get("headMotion")
            if isinstance(hm,dict) and hm.get("driver"):
                drivers[str(hm["driver"])] += 1
                for axis, value in (hm.get("applied") or {}).items():
                    if axis in ("pitch","yaw","roll"):
                        measure(f"renderer_{axis}_deg", value)
                measure("renderer_torso_drift_mm", hm.get("torsoDriftMm"))
            measure("renderer_compute_ms", d.get("renderMs"))
            measure("renderer_round_trip_ms", d.get("roundTripMs"))
    for stats in ranges.values():
        stats["mean"] = stats.pop("sum")/stats["n"]
    return {**result, "schema": 1, "motion_samples": samples, "sample_stages": dict(stages),
            "head_drivers": dict(drivers), "sampled_ranges": ranges, "events": dict(counts),
            "policy_events": dict(policies), "turns": turns, "errors": errors, "incomplete_lines": invalid}
