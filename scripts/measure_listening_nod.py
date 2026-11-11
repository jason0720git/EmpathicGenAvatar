"""Compare Seoyeon's finite listening cue from the served MJPEG or cached JPEGs.

Use an environment with MediaPipe Tasks, NumPy, and OpenCV. Coordinates and
displacements refer to an image scaled to 512 px wide. Regions are specific
to the Seoyeon portrait. Example:

  python scripts/measure_listening_nod.py --before artifacts/nod/before \
      --after artifacts/nod/after --capture-after http://localhost:4173/api/avatars/demo-seoyeon/idle/3/mjpeg \
      --output artifacts/nod --model models/perception/face_landmarker.task
"""

import argparse
import json
import math
from itertools import groupby
from pathlib import Path
from urllib.request import urlopen

import cv2
import mediapipe as mp
import numpy as np


FPS = 25
WIDTH = 512
# Keep shoulder texture and clothing seams clear of cheeks, neck and hair.
REGIONS = {
    "face": [(0.35, 0.28, 0.65, 0.53)],
    "shoulder_left": [(0.01, 0.71, 0.26, 0.99)],
    "shoulder_right": [(0.74, 0.71, 0.99, 0.99)],
    "collar": [(0.32, 0.70, 0.68, 0.78)],
    "background": [(0.01, 0.03, 0.17, 0.66), (0.83, 0.03, 0.99, 0.66)],
}
COLORS = ((40, 235, 60), (0, 194, 255), (255, 190, 20), (225, 95, 72), (215, 90, 230))


def capture(url, directory):
    directory.mkdir(parents=True, exist_ok=True)
    if list(directory.glob("*.jpg")):
        raise ValueError(f"Use a fresh capture directory: {directory}")
    with urlopen(url, timeout=30) as stream:
        for index in range(60):
            line = stream.readline().strip()
            if not line:
                line = stream.readline().strip()
            if line != b"--frame":
                raise ValueError(f"Unexpected MJPEG boundary at frame {index}: {line!r}")
            headers = {}
            while line := stream.readline().strip():
                key, value = line.split(b":", 1)
                headers[key.lower()] = value.strip()
            length = int(headers[b"content-length"])
            data = stream.read(length)
            if len(data) != length or not data.startswith(b"\xff\xd8"):
                raise ValueError(f"Incomplete frame {index}")
            (directory / f"{index:04}.jpg").write_bytes(data)


def image_at(directory, index):
    path = directory / f"{index:04}.jpg"
    full = cv2.imread(str(path))
    if full is None:
        raise ValueError(f"Missing frame: {path}")
    height = round(full.shape[0] * WIDTH / full.shape[1])
    return cv2.resize(full, (WIDTH, height), interpolation=cv2.INTER_AREA)


def rectangles(shape, name):
    height, width = shape[:2]
    return [
        (round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height))
        for x1, y1, x2, y2 in REGIONS[name]
    ]


def region_mask(shape, name):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for x1, y1, x2, y2 in rectangles(shape, name):
        mask[y1:y2, x1:x2] = 255
    return mask


def tracked_motion(ref, frame, points):
    if points is None:
        return {"tracked": 0}
    options = dict(winSize=(21, 21), maxLevel=3)
    forward, valid, _ = cv2.calcOpticalFlowPyrLK(ref, frame, points, None, **options)
    backward, returned, _ = cv2.calcOpticalFlowPyrLK(frame, ref, forward, None, **options)
    error = np.linalg.norm(backward - points, axis=2).ravel()
    keep = (valid.ravel() == 1) & (returned.ravel() == 1) & (error < 0.7)
    delta = (forward - points)[keep, 0, :]
    stats = {"tracked": int(len(delta))}
    if len(delta) >= 4:
        stats.update(
            median_xy=np.median(delta, axis=0).tolist(),
            p90_displacement=float(np.percentile(np.linalg.norm(delta, axis=1), 90)),
        )
    return stats


def landmarks(image, detector):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.face_landmarks:
        raise ValueError("Face tracking failed for an input frame")
    points = np.array([[v.x * image.shape[1], v.y * image.shape[0]] for v in result.face_landmarks[0]])
    nose = points[1]
    eye = (points[33] + points[263]) / 2
    rotation = result.facial_transformation_matrixes[0][:3, :3]
    return {
        "pitch_deg": math.degrees(math.atan2(rotation[2, 1], rotation[2, 2])),
        "yaw_deg": math.degrees(math.asin(np.clip(-rotation[2, 0], -1, 1))),
        "nose_minus_eyes_x": float(nose[0] - eye[0]),
        "nose_y": float(nose[1]),
        "nose_minus_eyes_y": float(nose[1] - eye[1]),
        "eyes_y": float(eye[1]),
        "inner_lip_gap_px": float(np.linalg.norm(points[13] - points[14])),
    }


def median_at(rows, keys, indices):
    values = []
    for index in indices:
        value = rows[index]
        for key in keys:
            if isinstance(value, dict) and key not in value:
                break
            value = value[key]
        else:
            values.append(value)
    return float(np.median(values)) if values else None


def window(seconds):
    center = round(seconds * FPS)
    return range(center - 1, center + 2)


def measure(directory, detector, pulses, output, label):
    if len(list(directory.glob("*.jpg"))) != 60:
        raise ValueError(f"Expected exactly 60 frames in {directory}")
    first = image_at(directory, 0)
    ref = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    masks = {name: region_mask(ref.shape, name) for name in REGIONS}
    features = {
        name: cv2.goodFeaturesToTrack(ref, 100, 0.008, 4, mask=mask, blockSize=5)
        for name, mask in masks.items()
    }
    overlay = first.copy()
    for (name, points), color in zip(features.items(), COLORS):
        for x1, y1, x2, y2 in rectangles(ref.shape, name):
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 1)
        if points is not None:
            for x, y in points.reshape(-1, 2).round().astype(int):
                cv2.circle(overlay, (x, y), 2, color, -1)
    cv2.imwrite(str(output / f"{label}-regions.jpg"), overlay)
    rows = []
    for index in range(60):
        frame = image_at(directory, index)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, ref)
        row = {"t": index / FPS, **landmarks(frame, detector)}
        for name, mask in masks.items():
            pixels = diff[mask != 0]
            row[name] = {
                "mae_levels": float(pixels.mean()),
                "p99_levels": float(np.percentile(pixels, 99)),
                **tracked_motion(ref, gray, features[name]),
            }
        rows.append(row)
    windows = []
    for onset, apex, recovery in pulses:
        # Measure relative to the cue onset. The first eight frames crossfade
        # from the portrait into the generated neutral pose and can move more
        # than the nod itself.
        base, peak, returned = window(onset), window(apex), window(recovery)
        metrics = {}
        for key in ("pitch_deg", "yaw_deg", "nose_y", "eyes_y", "nose_minus_eyes_y"):
            metrics[key] = median_at(rows, [key], peak) - median_at(rows, [key], base)
        for name in REGIONS:
            pre_y = median_at(rows, [name, "median_xy", 1], base)
            apex_y = median_at(rows, [name, "median_xy", 1], peak)
            metrics[name] = {
                "dy": apex_y - pre_y if pre_y is not None and apex_y is not None else None,
                "peak_window_p90_displacement": median_at(rows, [name, "p90_displacement"], peak),
                "peak_window_mae_levels": median_at(rows, [name, "mae_levels"], peak),
                "min_tracked": min(r[name]["tracked"] for r in rows),
            }
        windows.append({
            "onset_s": onset, "apex_s": apex, "recovery_s": recovery,
            "difference_from_onset": metrics,
            "return_pitch_minus_onset_deg": median_at(rows, ["pitch_deg"], returned) - median_at(rows, ["pitch_deg"], base),
            "return_nose_minus_onset_px": median_at(rows, ["nose_y"], returned) - median_at(rows, ["nose_y"], base),
        })
    start = window(pulses[0][0])
    pitch = np.array([r["pitch_deg"] for r in rows])
    summary = {
        "frames": len(rows), "fps": FPS, "width_px": WIDTH,
        "windows": windows,
        "startup_pitch_change_deg": median_at(rows, ["pitch_deg"], start) - rows[0]["pitch_deg"],
        "startup_nose_dy_px": median_at(rows, ["nose_y"], start) - rows[0]["nose_y"],
        "end_to_first_face_mae_levels": rows[-1]["face"]["mae_levels"],
        "max_frame_to_frame_pitch_deg": float(np.abs(np.diff(pitch)).max()),
        "inner_lip_gap_range_px": float(np.ptp([r["inner_lip_gap_px"] for r in rows])),
        "max_background_mae_levels": max(r["background"]["mae_levels"] for r in rows),
        "max_background_p99_levels": max(r["background"]["p99_levels"] for r in rows),
        "max_clothing_p90_px": {
            name: max((r[name]["p90_displacement"] for r in rows if "p90_displacement" in r[name]), default=None)
            for name in ("shoulder_left", "shoulder_right", "collar")
        },
    }
    (output / f"{label}-metrics.json").write_text(json.dumps({"summary": summary, "trajectory": rows}, indent=2), encoding="utf-8")
    return summary


def write_replay(cases, output):
    panels = []
    for label, directory, pulses in cases:
        for stroke, times in enumerate(pulses, start=1):
            tiles = []
            for t in times:
                tile = cv2.resize(image_at(directory, round(t * FPS)), (256, 320))
                title = f"{label} #{stroke}  {t:.2f}s"
                cv2.putText(tile, title, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                tiles.append(tile)
            panels.append(np.hstack(tiles))
    cv2.imwrite(str(output / "keyframes.jpg"), np.vstack(panels))
    writer = cv2.VideoWriter(str(output / "comparison.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (320 * len(cases), 400))
    if not writer.isOpened():
        raise RuntimeError("Could not open MP4 encoder")
    for index in range(60):
        tiles = []
        for label, directory, _ in cases:
            tile = cv2.resize(image_at(directory, index), (320, 400), interpolation=cv2.INTER_AREA)
            cv2.putText(tile, f"{label} {index / FPS:.2f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            tiles.append(tile)
        writer.write(np.hstack(tiles))
    writer.release()


def evaluate(reports):
    """Project-specific comparison criteria for this one portrait and cue."""
    old = reports["before"]["windows"][0]["difference_from_onset"]
    checks = {}
    for name, report in reports.items():
        if name == "before":
            continue
        first = report["windows"][0]["difference_from_onset"]
        checks[name] = {
            "primary_downward_pitch_and_nose_exceed_125pct_baseline": (
                first["pitch_deg"] > max(0, 1.25 * old["pitch_deg"])
                and first["nose_y"] > max(0, 1.25 * old["nose_y"])
            ),
            "every_stroke_pitch_returns_within_one_degree": all(
                abs(w["return_pitch_minus_onset_deg"]) < 1 for w in report["windows"]
            ),
            "clothing_p90_below_half_pixel_at_512_width": all(
                value is not None and value < 0.5 for value in report["max_clothing_p90_px"].values()
            ),
            "background_mae_below_one_gray_level": report["max_background_mae_levels"] < 1,
            "first_and_last_face_pixels_match": report["end_to_first_face_mae_levels"] == 0,
        }
        if len(report["windows"]) == 2:
            second = report["windows"][1]["difference_from_onset"]
            checks[name]["second_stroke_down_and_smaller"] = (
                0 < second["pitch_deg"] < first["pitch_deg"] and 0 < second["nose_y"] < first["nose_y"]
            )
    return checks


def match_browser_frames(ui_dir, rendered, variant, pulses):
    # During the initial browser crossfade, pixels intentionally do not equal
    # an unblended worker frame. For each physical apex we require a close
    # image match at the corresponding wall-clock time, allowing 4 frames
    # for network startup and capture cadence.
    directory = ui_dir / f"variant-{variant}"
    samples = json.loads((directory / "samples.json").read_text(encoding="utf-8"))

    def face_patch(image):
        image = cv2.resize(image, (256, 320), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(image[60:198, 67:191], cv2.COLOR_BGR2GRAY).astype(np.float32)

    cue = [(i, s) for i, s in enumerate(samples) if f"/idle/{variant}/mjpeg" in s["source"]]
    if not cue:
        raise ValueError(f"No browser samples from variant {variant}")
    first_ms = cue[0][1]["at"]
    matches = []
    for _, apex, _ in pulses:
        target = face_patch(image_at(rendered, round(apex * FPS)))
        candidates = [
            (s["at"] - first_ms, float(np.abs(face_patch(image_at(directory, i)) - target).mean()))
            for i, s in cue if abs(s["at"] - first_ms - apex * 1000) <= 160
        ]
        if not candidates:
            raise ValueError(f"No displayed samples near apex at {apex}s")
        best_ms, mae = min(candidates, key=lambda item: item[1])
        matches.append({"target_apex_s": apex, "display_time_ms": best_ms,
                        "face_patch_mae_levels": mae, "within_3_levels": mae < 3})
    return matches


def measure_live(directory, detector, output):
    """Measure clothing motion and lip articulation on displayed speech frames.

    Speech can independently move the lips and head. These descriptors cannot
    establish that a command preserved phoneme accuracy.
    """
    meta = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    samples = [(i, frame) for i, frame in enumerate(meta["frames"]) if frame["live"]]
    if not samples:
        raise ValueError("No displayed live frames in the supplied recording")
    def displayed_gray(index):
        image = cv2.imread(str(directory / f"{index:05}.jpg"))
        if image is None:
            raise ValueError(f"Missing displayed live frame {index}")
        image = cv2.resize(image, (WIDTH, round(image.shape[0] * WIDTH / image.shape[1])))
        return image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    _, ref = displayed_gray(samples[0][0])
    points = {
        name: cv2.goodFeaturesToTrack(ref, 100, 0.008, 4, mask=region_mask(ref.shape, name), blockSize=5)
        for name in ("shoulder_left", "shoulder_right", "collar")
    }
    composite = []
    for index, frame in enumerate(meta["frames"]):
        image, gray = displayed_gray(index)
        row = {"index": index, "pts_ms": frame.get("displayedPts"),
               "wall_ms": frame.get("at", frame.get("t")), "live": frame["live"]}
        if frame["live"]:
            row.update(landmarks(image, detector))
        for name, features in points.items():
            row[name] = tracked_motion(ref, gray, features)
        composite.append(row)
    rows = [row for row in composite if row["live"]]
    pitch = [r["pitch_deg"] for r in rows]
    lips = [r["inner_lip_gap_px"] for r in rows]
    summary = {
        "live_samples": len(rows), "composite_samples": len(composite), "width_px": WIDTH,
        "pitch_p10_p90_deg": np.percentile(pitch, [10, 90]).tolist(),
        "inner_lip_gap_p10_p90_px": np.percentile(lips, [10, 90]).tolist(),
        "max_clothing_p90_px_from_first_live_frame": {
            name: max((r[name]["p90_displacement"] for r in rows if "p90_displacement" in r[name]), default=None)
            for name in points
        },
        "whole_composite_max_clothing_p90_px": {
            name: max((r[name]["p90_displacement"] for r in composite if "p90_displacement" in r[name]), default=None)
            for name in points
        },
        "commands": [
            {"label": c["label"], "generated_pts_ms": c["applied"]["pts_ms"], "first_display_latency_ms": c.get("firstAffectedFrameDisplayedMs")}
            for c in meta.get("commands", []) if c.get("applied")
        ],
    }
    # A barge-in recording contains two distinct spoken segments.
    steady = []
    for _, group in groupby(enumerate(rows), key=lambda pair: pair[1]["index"] - pair[0]):
        segment = [row for _, row in group]
        start, end = segment[0]["wall_ms"], segment[-1]["wall_ms"]
        steady.extend(r for r in segment if start + 1000 <= r["wall_ms"] <= end - 1200)
    if steady:
        summary["steady_max_clothing_p90_px"] = {
            name: max((r[name]["p90_displacement"] for r in steady if "p90_displacement" in r[name]), default=None)
            for name in points
        }
    commands = summary["commands"]
    if commands:
        final_pts = max(r["pts_ms"] for r in rows if r["pts_ms"] is not None)
        for i, command in enumerate(commands):
            begin = command["generated_pts_ms"]
            end = commands[i+1]["generated_pts_ms"] if i+1 < len(commands) else min(begin + 3200, final_pts)
            # Last 720ms of each command, excluding transition onset and tail.
            selection = [r for r in rows if r["pts_ms"] is not None and max(begin + 700, end - 760) <= r["pts_ms"] < end - 40]
            if selection:
                command["observed_pts_range_ms"] = [selection[0]["pts_ms"], selection[-1]["pts_ms"]]
                command["median_yaw_deg"] = float(np.median([r["yaw_deg"] for r in selection]))
                command["median_nose_minus_eyes_x_px"] = float(np.median([r["nose_minus_eyes_x"] for r in selection]))
    (output / "live-locality.json").write_text(json.dumps({"summary": summary, "trajectory": composite}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--double", type=Path)
    parser.add_argument("--capture-after", metavar="URL")
    parser.add_argument("--capture-double", metavar="URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ui-dir", type=Path, help="Output of check_listening_preview.cjs")
    parser.add_argument("--live-dir", type=Path, help="Analyze one mic_e2e or live_control_e2e recording instead")
    parser.add_argument("--model", default="models/perception/face_landmarker.task")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=args.model),
        output_facial_transformation_matrixes=True,
    )
    if args.live_dir:
        with mp.tasks.vision.FaceLandmarker.create_from_options(options) as detector:
            measure_live(args.live_dir, detector, args.output)
        return
    if not args.before:
        parser.error("--before is required for nod comparison")
    for url, directory in ((args.capture_after, args.after), (args.capture_double, args.double)):
        if url:
            if not directory:
                parser.error("Each capture URL requires the corresponding destination directory")
            capture(url, directory)
    cases = [("before", args.before, [(0.40, 0.76, 1.12)])]
    if args.after:
        cases.append(("after", args.after, [(0.32, 0.56, 0.88)]))
    if args.double:
        cases.append(("double", args.double, [(0.32, 0.56, 0.88), (1.00, 1.24, 1.56)]))
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as detector:
        summaries = {name: measure(directory, detector, apices, args.output, name) for name, directory, apices in cases}
    write_replay(cases, args.output)
    checks = evaluate(summaries)
    if args.ui_dir:
        matches = {
            name: match_browser_frames(args.ui_dir, directory, {"after": 3, "double": 5}[name], pulses)
            for name, directory, pulses in cases[1:]
        }
        (args.output / "displayed-apices.json").write_text(json.dumps(matches, indent=2), encoding="utf-8")
        for name, observations in matches.items():
            checks[name]["all_apices_visible_in_browser"] = all(r["within_3_levels"] for r in observations)
    (args.output / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    (args.output / "comparison.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))
    failed = [f"{name}.{criterion}" for name, group in checks.items() for criterion, passed in group.items() if not passed]
    if failed:
        raise SystemExit("Visual comparison failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
