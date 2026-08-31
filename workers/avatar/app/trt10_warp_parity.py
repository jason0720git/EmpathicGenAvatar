"""Numerical release gate for the Ditto TensorRT-10 warp plugin.

Runs the same deterministic tensors through the published PyTorch warp model
and the TensorRT-10 engine.  This is deliberately a component gate before a
full video test: a wrong coordinate convention here causes visible face-edge
and mouth artefacts even when an engine successfully deserializes.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ditto-root", type=Path, default=Path("/opt/ditto"))
    parser.add_argument("--pytorch-model", type=Path, default=Path("/models/ditto/ditto_pytorch/models/warp_network.pth"))
    parser.add_argument("--engine", type=Path, default=Path("/data/engines/ditto-trt10/warp_network_fp16.engine"))
    parser.add_argument("--plugin", type=Path, default=Path("/worker/trt_plugins/libditto_gridsample3d_trt10.so"))
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--max-abs-limit", type=float, default=0.03)
    parser.add_argument("--mean-abs-limit", type=float, default=0.003)
    args = parser.parse_args()
    for path in (args.ditto_root, args.pytorch_model, args.engine, args.plugin):
        if not path.exists():
            raise FileNotFoundError(path)
    sys.path.insert(0, str(args.ditto_root))
    # Load before TensorRT Runtime creation so deserialize can find the V2
    # creator registered by the legacy-compatible plugin.
    ctypes.CDLL(str(args.plugin), mode=ctypes.RTLD_GLOBAL)
    from core.models.warp_network import WarpNetwork
    from core.utils.tensorrt_utils import TRTWrapper

    rng = np.random.default_rng(args.seed)
    feature = rng.standard_normal((1, 32, 16, 64, 64), dtype=np.float32)
    source = rng.uniform(-0.75, 0.75, (1, 21, 3)).astype(np.float32)
    driving = rng.uniform(-0.75, 0.75, (1, 21, 3)).astype(np.float32)

    torch_model = WarpNetwork(str(args.pytorch_model))
    started = time.perf_counter()
    reference = torch_model(feature, source, driving)
    pytorch_ms = (time.perf_counter() - started) * 1000
    engine = TRTWrapper(str(args.engine))
    started = time.perf_counter()
    engine.setup({"feature_3d": feature, "kp_source": source, "kp_driving": driving})
    engine.infer()
    actual = engine.buffer["out"][0].copy()
    trt_ms = (time.perf_counter() - started) * 1000
    delta = np.abs(reference - actual)
    report = {
        "seed": args.seed,
        "shape": list(actual.shape),
        "pytorch_wall_ms": round(pytorch_ms, 3),
        "trt_wall_ms_including_copies": round(trt_ms, 3),
        "max_abs": float(delta.max()),
        "mean_abs": float(delta.mean()),
        "p99_abs": float(np.quantile(delta, 0.99)),
        "limits": {"max_abs": args.max_abs_limit, "mean_abs": args.mean_abs_limit},
    }
    report["passed"] = report["max_abs"] <= args.max_abs_limit and report["mean_abs"] <= args.mean_abs_limit
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
