"""Compare content-free browser and worker motion telemetry for selected runs."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def pick(record, keys):
    return {key: record[key] for key in keys.split() if key in record}


def rows(path):
    with path.open(encoding="utf-8-sig") as source:
        for line in source:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # A live append or an older partial line.
            if isinstance(row, dict) and isinstance(row.get("turn_id"), str):
                yield row


def timestamp(value):
    try:
        if isinstance(value, (float, int)):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def event_time(row):
    at = timestamp(row.get("at"))
    fields = {"server_at": at.isoformat(timespec="milliseconds") if at else None}
    if "elapsed_ms" in row:
        fields["elapsed_ms"] = row["elapsed_ms"]
    fields.update(pick(row.get("details") or {}, "client_ms"))
    return fields


def control_latency(start, end):
    if start is None or end is None:
        return None
    if all(isinstance(item.get("client_ms"), (float, int)) for item in (start, end)):
        return {"ms": round(end["client_ms"] - start["client_ms"], 1), "clock": "browser_monotonic"}
    began, finished = (timestamp(item.get("server_at")) for item in (start, end))
    if began and finished:
        return {"ms": round((finished - began).total_seconds() * 1000, 1), "clock": "api_receipt"}
    return None


def expression_stats(data):
    fields = pick(data, "policy sobia_reference_commit mode enabled style_seed_source stage frame_seconds "
                        "rise_s hold_s fall_s brow_balance evaluated_frames voiced_frames "
                        "accent_at_least_0_2_frames pause_boundary_frames")
    for key in ("region_lag_s", "peak_target_gain", "peak_smoothed_gain", "peak_abs_residual_component"):
        if isinstance(data.get(key), dict):
            fields[key] = pick(data[key], "brow lid cheek_corner")
    return fields


def summarize(turn_id, records):
    lifecycle, cues, controls, worker = [], {}, {}, {}
    result = {"turn_id": turn_id, "found": bool(records), "lifecycle": lifecycle,
              "cues": [], "control_commands": [], "worker": worker}
    for row in records:
        event = row.get("event")
        info = row.get("details") or {}
        at = event_time(row)
        result.update(pick(row, "avatar_id session_id policy_version"))
        result.update(pick(info, "renderer cache_revision source_sha256"))
        if event == "motion_cue":
            # Legacy rows with no cue ID remain separate, without a guessed join.
            cue_id = info.get("cue_id") or f"unidentified-{len(cues) + 1}"
            cue = cues.setdefault(cue_id, {"cue_id": cue_id, "events": []})
            cue.update(pick(info, "kind trigger variant voiced_ms pause_ms clip_frames cycles requested_peak_deg"))
            cue["events"].append({**at, **pick(info, "phase painted_frames")})
        elif event == "live_control":
            seq = info.get("seq")
            command = controls.setdefault(seq, {"seq": seq, "events": []})
            command["events"].append({**at, **pick(info, "phase channels expression intensity yaw_deg pitch_deg "
                                                        "roll_deg gaze_x gaze_y pts_ms display_pts_ms")})
        elif event in ("listening_started", "listening_ended", "turn_submitted", "turn_response",
                       "render_requested", "playback_started", "playback_ended", "playback_interrupted",
                       "first_frame_presented", "socket_error", "jpeg_decode_failed", "video_pts_gap"):
            lifecycle.append({"event": event, **at, **pick(info, "input submit expression_mode emotion intensity "
                                                                 "pts_ms display_pts_ms jpeg_decode_failures video_pts_gaps")})
        elif event == "visual_transition" and info.get("phase") == "completed":
            lifecycle.append({"event": event, **at, **pick(info, "direction live_tail_completed fallback")})
        elif event == "ditto.affect_applied":
            worker["scheduled"] = {**at, **pick(row, "expression intensity expression_test expression_render_mode temporal_policy")}
            if "companion_expression" in row:
                worker["scheduled"]["companion_expression"] = expression_stats(row["companion_expression"])
        elif event == "ditto.speech_protection":
            worker["after_stitch"] = {**at, **pick(row, "policy mode frames peak_removed_lip_delta "
                                                         "smile_corner_frames peak_corner_delta")}
            if "companion_expression" in row:
                worker["after_stitch"]["companion_expression"] = expression_stats(row["companion_expression"])
            if "live_control" in row:
                live = row["live_control"]
                ownership = pick(live, "enabled last_received_seq last_applied_seq")
                if "channel_owned_frames" in live:
                    ownership["channel_owned_frames"] = pick(live["channel_owned_frames"], "face gaze head")
                worker["after_stitch"]["live_control"] = ownership

    for command in controls.values():
        phases = {e.get("phase"): e for e in command["events"]}
        request = phases.get("requested") or phases.get("reset")
        command["request_to_applied"] = control_latency(request, phases.get("control.applied"))
        command["request_to_displayed"] = control_latency(request, phases.get("displayed"))
    result["cues"] = list(cues.values())
    result["control_commands"] = list(controls.values())
    result["head_busy_gates"] = sum(e.get("phase") == "head_busy" for c in cues.values() for e in c["events"])
    terminal = [item["event"] for item in lifecycle if item["event"] in ("playback_ended", "playback_interrupted")]
    result["playback_outcome"] = terminal[-1] if terminal else "unobserved"
    return result


def compare(directory, turns, avatar, limit):
    browser = directory / "turn-events.jsonl"
    worker = directory / "ditto-affect-applied.jsonl"
    paths = [p for p in (browser, worker) if p.is_file()]
    if not paths:
        raise FileNotFoundError(f"No motion telemetry logs in {directory}")
    if avatar is not None:
        # An old UI row may lack an avatar ID. Select known matching turn IDs
        # before collecting all their records, including those historical rows.
        latest = {}
        matching = set()
        for path in paths:
            for row in rows(path):
                key = row["turn_id"]
                at = timestamp(row.get("at"))
                latest[key] = max(latest.get(key, 0), at.timestamp() if at else 0)
                if row.get("avatar_id") == avatar:
                    matching.add(key)
        turns = sorted(matching, key=lambda key: (latest[key], key), reverse=True)[:limit]
    records = {key: [] for key in turns}
    for path in paths:
        for row in rows(path):
            if row["turn_id"] in records:
                records[row["turn_id"]].append(row)
    return {"logs_present": [p.name for p in paths], "runs": [summarize(k, v) for k, v in records.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telemetry-dir", type=Path, default=Path("/data/telemetry"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--turn", action="append", help="exact turn or preview ID; repeat to compare")
    selection.add_argument("--avatar", help="select the avatar's most recent identified runs")
    parser.add_argument("--limit", type=int, default=5, help="number of recent runs when using --avatar")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        report = compare(args.telemetry_dir, args.turn, args.avatar, args.limit)
    except OSError as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
