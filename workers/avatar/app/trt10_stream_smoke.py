"""Exercise the complete TensorRT-10 Ditto online path with no user media output."""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np


class CountingSink:
    def __init__(self) -> None:
        self.frames = 0
        self.first_frame_ms: float | None = None
        self.started = time.perf_counter()
        self.lock = threading.Lock()

    def __call__(self, _frame, fmt="rgb") -> None:
        assert fmt == "rgb"
        with self.lock:
            self.frames += 1
            if self.first_frame_ms is None:
                self.first_frame_ms = (time.perf_counter() - self.started) * 1000

    def close(self) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/data/uploads/default-korean-avatar.png"))
    parser.add_argument("--ditto-root", type=Path, default=Path("/opt/ditto"))
    parser.add_argument("--config", type=Path, default=Path("/models/ditto/ditto_cfg/v0.4_hubert_cfg_trt_online.pkl"))
    parser.add_argument("--model-root", type=Path, default=Path("/data/engines/ditto-trt10"))
    parser.add_argument("--plugin", type=Path, default=Path("/worker/trt_plugins/libditto_gridsample3d_trt10.so"))
    parser.add_argument("--sampling-timesteps", type=int, default=2)
    parser.add_argument("--windows", type=int, default=4)
    args = parser.parse_args()
    for path in (args.source, args.ditto_root, args.config, args.model_root, args.plugin):
        if not path.exists():
            raise FileNotFoundError(path)
    ctypes.CDLL(str(args.plugin), mode=ctypes.RTLD_GLOBAL)
    sys.path.insert(0, str(args.ditto_root))
    from stream_pipeline_online import StreamSDK

    started = time.perf_counter()
    sdk = StreamSDK(str(args.config), str(args.model_root))
    sink = CountingSink()
    # Same 40 ms online window as the production worker.
    chunksize = (3, 5, 2)
    samples = int(sum(chunksize) * 0.04 * 16_000) + 80
    sdk.setup(str(args.source), "", frame_sink=sink, online_mode=True, sampling_timesteps=args.sampling_timesteps, emo=4)
    try:
        sdk.setup_Nd(20)
        silence = np.zeros((samples,), dtype=np.float32)
        for _ in range(args.windows):
            sdk.run_chunk(silence, chunksize)
    finally:
        sdk.close()
    report = {
        "frames": sink.frames,
        "first_frame_ms": round(sink.first_frame_ms, 2) if sink.first_frame_ms else None,
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
        "sampling_timesteps": args.sampling_timesteps,
        "windows": args.windows,
        "passed": sink.frames > 0,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
