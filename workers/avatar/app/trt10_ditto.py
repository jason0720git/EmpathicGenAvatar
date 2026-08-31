"""Build and audit Ditto TensorRT 10 engines on the deployment GPU.

This tool deliberately writes only under ``/data``.  Ditto's supplied engines
were built for TensorRT 8/Ampere and are neither portable to RTX 5090 nor safe
to load on TensorRT 10.  The source ONNX files remain read-only in ``/models``.

Examples (run inside an avatar-worker container)::

    python -m app.trt10_ditto audit
    python -m app.trt10_ditto build --models appearance_extractor,decoder
    python -m app.trt10_ditto build --all

The JSON manifests are intentionally a release gate: a failed parser/build is
reported as failed rather than silently falling back to an unrelated engine.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_ONNX_ROOT = Path("/models/ditto/ditto_onnx")
DEFAULT_OUTPUT_ROOT = Path("/data/engines/ditto-trt10")
DEFAULT_PLUGIN_PATH = Path("/worker/trt_plugins/libditto_gridsample3d_trt10.so")
# These names exactly match v0.4_hubert_cfg_trt_online.pkl.  The model is
# called in a Python diffusion loop, so engineizing it removes per-step PyTorch
# dispatch but does not remove the configured number of diffusion steps.
ENGINE_NAMES = {
    "appearance_extractor": ("appearance_extractor_fp16.engine", True),
    "blaze_face": ("blaze_face_fp16.engine", True),
    "decoder": ("decoder_fp16.engine", True),
    "face_mesh": ("face_mesh_fp16.engine", True),
    "hubert": ("hubert_fp32.engine", False),
    "insightface_det": ("insightface_det_fp16.engine", True),
    "landmark106": ("landmark106_fp16.engine", True),
    "landmark203": ("landmark203_fp16.engine", True),
    "lmdm_v0.4_hubert": ("lmdm_v0.4_hubert_fp32.engine", False),
    "motion_extractor": ("motion_extractor_fp32.engine", False),
    "stitch_network": ("stitch_network_fp16.engine", True),
    "warp_network": ("warp_network_fp16.engine", True),
    # This export uses standard ONNX GridSample instead of the upstream
    # GridSample3D TensorRT-8 plugin.  It is audited separately and is never
    # substituted into the renderer until numerical/video parity passes.
    "warp_network_ori": ("warp_network_ori_fp16.engine", True),
}
SUPPORTED_MODELS = tuple(name for name in ENGINE_NAMES if name != "warp_network_ori")

# Fixed profiles actually used by the online Ditto pipeline.  The upstream
# models mark some batch/time axes dynamic even though StreamSDK supplies one
# face and exactly one 40 ms HuBERT chunk at a time.  Keeping these explicit
# makes the generated engine a documented online artifact, not a guess.
ONLINE_SHAPES: dict[str, dict[str, tuple[int, ...]]] = {
    "face_mesh": {"input": (1, 256, 256, 3)},
    "hubert": {"input_values": (1, 6480)},
    "landmark106": {"data": (1, 3, 192, 192)},
}


@dataclass
class Result:
    model: str
    onnx: str
    engine: str
    fp16: bool
    status: str
    elapsed_ms: float
    inputs: list[dict]
    outputs: list[dict]
    error: str | None = None
    engine_bytes: int | None = None


def _trt():
    import tensorrt as trt  # Imported here so --help works outside the image.

    return trt


def _load_ditto_plugin(model: str) -> None:
    """Register the legacy ONNX parser plugin before parsing/deserialize.

    TensorRT 10's ``dynamicPlugins`` CLI option is for V3 libraries exposing
    ``getCreators``. Ditto's ONNX parser uses the compatible V2 creator path,
    so loading the .so into the process is intentional here.
    """
    if model != "warp_network":
        return
    if not DEFAULT_PLUGIN_PATH.is_file():
        raise FileNotFoundError(f"GridSample3D TensorRT 10 plugin missing: {DEFAULT_PLUGIN_PATH}")
    ctypes.CDLL(str(DEFAULT_PLUGIN_PATH), mode=ctypes.RTLD_GLOBAL)


def _shape(dims) -> list[int]:
    return [int(dim) for dim in dims]


def _tensor_info(network, tensor) -> dict:
    return {"name": tensor.name, "shape": _shape(tensor.shape), "dtype": str(tensor.dtype)}


def _dynamic_shape(model: str, name: str, shape: list[int]) -> tuple[int, ...]:
    """Safe static profile for Ditto's exported batch-1 online networks.

    Dynamic time dimensions are intentionally not guessed.  A model with one
    is reported as ``needs_profile`` so an operator must supply a documented
    runtime profile instead of receiving an engine that fails on the first
    spoken chunk.
    """
    if any(dim < 0 for dim in shape):
        profile = ONLINE_SHAPES.get(model, {}).get(name)
        if profile is None:
            raise ValueError(f"dynamic shape {shape}; add an explicit online profile before build")
        if len(profile) != len(shape) or any(dim >= 0 and dim != profile[i] for i, dim in enumerate(shape)):
            raise ValueError(f"profile {profile} is incompatible with dynamic shape {shape}")
        return profile
    return tuple(shape)


def audit_one(model: str, onnx_path: Path) -> Result:
    trt = _trt()
    _load_ditto_plugin(model)
    started = time.perf_counter()
    logger = trt.Logger(trt.Logger.ERROR)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    ok = parser.parse_from_file(str(onnx_path))
    errors = "\n".join(str(parser.get_error(i)) for i in range(parser.num_errors))
    inputs = [_tensor_info(network, network.get_input(i)) for i in range(network.num_inputs)]
    outputs = [_tensor_info(network, network.get_output(i)) for i in range(network.num_outputs)]
    name, fp16 = ENGINE_NAMES.get(model, (f"{model}.engine", False))
    status = "parse_ok" if ok else "parse_failed"
    if ok:
        try:
            for item in inputs:
                _dynamic_shape(model, item["name"], item["shape"])
        except ValueError as exc:
            status = "needs_profile"
            errors = str(exc)
    return Result(
        model=model,
        onnx=str(onnx_path),
        engine=name,
        fp16=fp16,
        status=status,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        inputs=inputs,
        outputs=outputs,
        error=errors or None,
    )


def build_one(model: str, onnx_path: Path, output_root: Path) -> Result:
    result = audit_one(model, onnx_path)
    if result.status != "parse_ok":
        return result
    trt = _trt()
    _load_ditto_plugin(model)
    started = time.perf_counter()
    logger = trt.Logger(trt.Logger.ERROR)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(onnx_path)):
        result.status = "parse_failed"
        result.error = "\n".join(str(parser.get_error(i)) for i in range(parser.num_errors))
        return result
    config = builder.create_builder_config()
    config.builder_optimization_level = 5
    if result.fp16:
        if not builder.platform_has_fast_fp16:
            result.status, result.error = "build_failed", "GPU does not report fast FP16 support"
            return result
        config.set_flag(trt.BuilderFlag.FP16)
    # Every currently supported model has a fixed online shape.  Keeping the
    # check here prevents an accidental dynamic export from becoming a subtly
    # wrong static engine.
    if any(-1 in _shape(network.get_input(i).shape) for i in range(network.num_inputs)):
        profile = builder.create_optimization_profile()
        for i in range(network.num_inputs):
            tensor = network.get_input(i)
            shape = _dynamic_shape(model, tensor.name, _shape(tensor.shape))
            profile.set_shape(tensor.name, shape, shape, shape)
        config.add_optimization_profile(profile)
    try:
        serialized = builder.build_serialized_network(network, config)
        if serialized is None:
            raise RuntimeError("TensorRT returned no serialized engine")
        output_root.mkdir(parents=True, exist_ok=True)
        target = output_root / result.engine
        target.write_bytes(bytes(serialized))
        result.status = "built"
        result.engine_bytes = target.stat().st_size
    except Exception as exc:  # TensorRT errors are version-dependent.
        result.status, result.error = "build_failed", f"{type(exc).__name__}: {exc}"
    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return result


def verify_one(model: str, onnx_path: Path, output_root: Path) -> Result:
    """Deserialize and execute a generated engine with TensorRT's test inputs."""
    result = audit_one(model, onnx_path)
    target = output_root / result.engine
    if result.status != "parse_ok" or not target.is_file():
        result.status = "missing_engine" if result.status == "parse_ok" else result.status
        result.error = result.error or f"engine not found: {target}"
        return result
    started = time.perf_counter()
    _load_ditto_plugin(model)
    # trtexec exercises bindings and execution, whereas deserialization alone
    # can miss a profile/binding incompatibility.  No media is supplied here.
    command = [
        "/opt/tensorrt/bin/trtexec", f"--loadEngine={target}",
        "--warmUp=200", "--duration=1", "--useSpinWait", "--noDataTransfers",
    ]
    if model == "warp_network":
        command.append(f"--plugins={DEFAULT_PLUGIN_PATH}")
    run = subprocess.run(command, capture_output=True, text=True, timeout=120)
    text = (run.stdout + "\n" + run.stderr)[-6_000:]
    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    result.engine_bytes = target.stat().st_size
    if run.returncode == 0:
        result.status = "verified"
    else:
        result.status, result.error = "verify_failed", text
    # Keep benchmark detail in the manifest without making the format depend
    # on a particular trtexec minor-version table layout.
    if result.status == "verified":
        result.error = next((line.strip() for line in text.splitlines() if "GPU Compute Time" in line), None)
    return result


def selected_models(args: argparse.Namespace) -> Iterable[str]:
    if args.all:
        return ENGINE_NAMES.keys()
    if args.supported:
        return SUPPORTED_MODELS
    return [item.strip() for item in args.models.split(",") if item.strip()]


def metadata() -> dict:
    trt = _trt()
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], capture_output=True, text=True)
    return {
        "created_at_epoch_ms": round(time.time() * 1000),
        "tensorrt_version": trt.__version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "gpu": gpu.stdout.strip() if gpu.returncode == 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "build", "verify"))
    parser.add_argument("--onnx-root", type=Path, default=DEFAULT_ONNX_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--models", default="appearance_extractor,decoder,hubert,lmdm_v0.4_hubert,motion_extractor,stitch_network,warp_network")
    parser.add_argument("--all", action="store_true", help="include auxiliary detector models")
    parser.add_argument("--supported", action="store_true", help="all currently TensorRT-10-buildable models; excludes the known warp GridSample3D blocker")
    args = parser.parse_args()
    results: list[Result] = []
    for model in selected_models(args):
        onnx = args.onnx_root / f"{model}.onnx"
        if not onnx.is_file():
            results.append(Result(model, str(onnx), "", False, "missing_onnx", 0, [], [], "file not found"))
            continue
        if args.command == "audit":
            results.append(audit_one(model, onnx))
        elif args.command == "build":
            results.append(build_one(model, onnx, args.output_root))
        else:
            results.append(verify_one(model, onnx, args.output_root))
    report = {"metadata": metadata(), "command": args.command, "results": [asdict(item) for item in results]}
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = args.output_root / f"{args.command}-manifest.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"manifest={output}")
    success = {"parse_ok", "built", "verified"}
    return 0 if all(item.status in success for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
