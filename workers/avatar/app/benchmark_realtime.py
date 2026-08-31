"""Repeatable external timing probe for the Ditto Realtime worker.

Run inside the worker container after it is warm. The script measures the
observable contract (first WebSocket packet, A/V PTS, and completion), stores
per-run JSON plus representative JPEG frames under /data/benchmarks, and does
not alter the serving API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import struct
import time
import urllib.request
import uuid
from pathlib import Path

import websockets


def post_json(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:8010{path}",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


async def run_turn(avatar_id: str, text: str, label: str, index: int, output_dir: Path, render_profile: str) -> dict:
    turn_id = f"benchmark-{label}-{index:02d}-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    render = post_json("/v1/turns/render", {
        "avatar_id": avatar_id,
        "session_id": f"benchmark-{label}",
        "turn_id": turn_id,
        "text": text,
        "render_profile": render_profile,
    })
    render_response_ms = round((time.monotonic() - started) * 1000, 1)
    path = render["stream_url"].removeprefix("/avatar-stream")
    first_packet_ms: float | None = None
    first_video_ms: float | None = None
    completed_ms: float | None = None
    counts = {"audio": 0, "video": 0}
    last_pts = {"audio": -1, "video": -1}
    capture_points = (0, 1000, 3000, 6000)
    captured_points: set[int] = set()

    async with websockets.connect(f"ws://127.0.0.1:8010{path}", max_size=4_000_000) as socket:
        async for message in socket:
            kind = message[0]
            if kind == 3:
                completed_ms = round((time.monotonic() - started) * 1000, 1)
                break
            pts_ms = struct.unpack(">I", message[1:5])[0]
            if first_packet_ms is None:
                first_packet_ms = round((time.monotonic() - started) * 1000, 1)
            if kind == 1:
                counts["audio"] += 1
                last_pts["audio"] = pts_ms
            elif kind == 2:
                counts["video"] += 1
                last_pts["video"] = pts_ms
                if first_video_ms is None:
                    first_video_ms = round((time.monotonic() - started) * 1000, 1)
                for capture_point in capture_points:
                    if capture_point not in captured_points and pts_ms >= capture_point:
                        (output_dir / f"{label}-run-{index:02d}-{capture_point:04d}ms.jpg").write_bytes(message[5:])
                        captured_points.add(capture_point)

    return {
        "turn_id": turn_id,
        "render_response_ms": render_response_ms,
        "first_packet_ms": first_packet_ms,
        "first_video_ms": first_video_ms or first_packet_ms,
        "completed_ms": completed_ms,
        "counts": counts,
        "last_pts": last_pts,
        "av_end_skew_ms": abs(last_pts["audio"] - last_pts["video"]),
        "av_packet_count_delta": abs(counts["audio"] - counts["video"]),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--avatar-id", default="demo-seoyeon")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--label", required=True)
    parser.add_argument("--render-profile", choices=("quality", "fast", "fast_preroll9", "fast_preroll5"), default="quality")
    parser.add_argument(
        "--text",
        default="안녕하세요. 실시간 아바타 첫 반응과 립싱크의 안정성을 측정하는 동일한 테스트 문장입니다.",
    )
    parser.add_argument("--output-dir", default="/data/benchmarks")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runs = [await run_turn(args.avatar_id, args.text, args.label, index + 1, output_dir, args.render_profile) for index in range(args.runs)]
    first_packets = [run["first_packet_ms"] for run in runs if run["first_packet_ms"] is not None]
    summary = {
        "label": args.label,
        "render_profile": args.render_profile,
        "runs": runs,
        "summary": {
            "runs": len(runs),
            "first_packet_p50_ms": round(statistics.median(first_packets), 1),
            # Nearest-rank p95: for a 10-run smoke suite this deliberately
            # includes the slowest first spoken turn instead of hiding it.
            "first_packet_p95_ms": round(sorted(first_packets)[max(0, math.ceil(len(first_packets) * .95) - 1)], 1),
            "completion_p50_ms": round(statistics.median(run["completed_ms"] for run in runs if run["completed_ms"] is not None), 1),
            "max_av_end_skew_ms": max(run["av_end_skew_ms"] for run in runs),
            "max_av_packet_count_delta": max(run["av_packet_count_delta"] for run in runs),
        },
    }
    target = output_dir / f"{args.label}-results.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
