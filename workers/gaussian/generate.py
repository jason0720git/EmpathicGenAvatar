"""Run official LAM portrait reconstruction and export a controllable 3DGS rig."""
from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
os.environ.setdefault("XFORMERS_DISABLED", "1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--upstream-baseline", action="store_true",
                        help="Keep the uncalibrated upstream geometry/rig and render native validation frames.")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]  # Upstream tracking parses its own CLI.
    root = Path(os.environ.get("LAM_ROOT", "/opt/lam")).resolve()
    sample = Path(os.environ.get("LAM_TEMPLATE_ZIP", "/opt/lam-web/asset/arkit/p2-1.zip"))
    args.output.mkdir(parents=True, exist_ok=True)
    args.job_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    sys.path.insert(0, str(root))
    started = time.monotonic()
    timings = {}
    previous_time, previous_stage = started, "initializing"

    def stage(name: str, **fields):
        nonlocal previous_time, previous_stage
        now = time.monotonic()
        timings[previous_stage] = round((now - previous_time) * 1000)
        payload = {"phase": name, "elapsed_ms": round((now - started) * 1000), "timings_ms": timings.copy(), **fields}
        temp = args.job_dir / "status.tmp"
        temp.write_text(json.dumps(payload, indent=2), encoding="utf8")
        temp.replace(args.job_dir / "status.json")
        with (args.job_dir / "events.jsonl").open("a", encoding="utf8") as stream:
            stream.write(json.dumps(payload) + "\n")
        print(json.dumps(payload), flush=True)
        previous_time, previous_stage = now, name

    try:
        stage("loading_dependencies")
        from compatibility import validate_joint_attention
        compatibility = validate_joint_attention()
        diffusers_version = compatibility["diffusers_version"]
        import numpy as np
        # Upstream FLAME pickle uses chumpy; these aliases were removed from
        # NumPy 1.24 and Python 3.11. This does not alter numeric calculations.
        for name, value in {"bool": bool, "int": int, "float": float,
                            "complex": complex, "object": object,
                            "unicode": str, "str": str}.items():
            if name not in np.__dict__:
                setattr(np, name, value)
        if not hasattr(inspect, "getargspec"):
            inspect.getargspec = inspect.getfullargspec
        import torch
        from torch.utils.cpp_extension import _get_build_directory
        # nvdiffrast 0.3.3 imports its extension by module name after load();
        # current Torch no longer adds the JIT directory to Python's path.
        sys.path.insert(0, _get_build_directory("nvdiffrast_plugin", False))
        from PIL import Image, ImageOps
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for LAM image reconstruction")
        torch.cuda.set_device(0)
        torch.set_float32_matmul_precision("high")
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        stage("preparing_input", cuda_free_gb=round(free_bytes / 2**30, 2),
              cuda_total_gb=round(total_bytes / 2**30, 2), torch_version=torch.__version__)
        image_path = args.job_dir / "input.png"
        with Image.open(args.image) as source:
            ImageOps.exif_transpose(source).convert("RGB").save(image_path)
        # CPU NMS is the only upstream extension kept alongside its source.
        nms_root = root / "external/landmark_detection/FaceBoxesV2/utils"
        if not list((nms_root / "nms").glob("cpu_nms*.so")):
            subprocess.run([sys.executable, "build.py", "build_ext", "--inplace"], cwd=nms_root, check=True)

        from tools.flame_tracking_single_image import FlameTrackingSingleImage
        stage("loading_face_tracker")
        tracker = FlameTrackingSingleImage(output_dir=str(args.job_dir / "tracking"), detect_iris_landmarks=False)
        stage("segmenting_and_landmarks")
        if tracker.preprocess(str(image_path)) != 0:
            raise RuntimeError("No usable face detected. Use a clear frontal portrait with visible eyes and mouth.")
        stage("fitting_flame_geometry")
        if tracker.optimize() != 0:
            raise RuntimeError("FLAME geometry fitting failed")
        stage("exporting_tracked_geometry")
        code, tracked = tracker.export()
        if code != 0:
            raise RuntimeError("Tracked face export failed")
        del tracker
        gc.collect()
        torch.cuda.empty_cache()

        # This utility is self-contained. Importing the runner package would
        # also load training/video code and unrelated marching-cubes packages.
        import importlib.util
        helper_spec = importlib.util.spec_from_file_location("lam_head_preprocess", root / "lam/runners/infer/head_utils.py")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        preprocess_image = helper.preprocess_image
        image, _, _, shape = preprocess_image(
            str(Path(tracked) / "images/00000_00.png"),
            mask_path=str(Path(tracked) / "fg_masks/00000_00.png"), intr=None,
            pad_ratio=0, bg_color=1., max_tgt_size=None, aspect_standard=1.,
            enlarge_ratio=[1., 1.], render_tgt_size=512, multiply=14,
            need_mask=True, get_shape_param=True)
        Image.fromarray((image[0].permute(1, 2, 0).numpy() * 255).clip(0, 255).astype("uint8")).save(args.output / "preview.png")

        stage("loading_lam_model")
        from omegaconf import OmegaConf
        from safetensors.torch import load_file
        from lam.models import ModelLAM
        from lam.models.encoders.dinov2_fusion_wrapper import Dinov2FusionWrapper
        from lam.models.encoders.dinov2.hub import backbones
        # Full LAM checkpoint already includes DINOv2 weights. Loading another
        # pretrained copy would download 1.2GB and then overwrite every tensor.
        def build_dino(model_name, modulation_dim=None, pretrained=True):
            return getattr(backbones, model_name)(modulation_dim=modulation_dim, pretrained=False)
        Dinov2FusionWrapper._build_dinov2 = staticmethod(build_dino)
        config = OmegaConf.load(root / "configs/inference/lam-20k-8gpu.yaml")
        model = ModelLAM(**config.model)
        checkpoint = load_file(str(root / "model_zoo/lam_models/releases/lam/lam-20k/step_045500/model.safetensors"))
        # This derived, nonlearned subdivision buffer was added after the
        # public weight release. Keep the constructor's exact FLAME result;
        # require every learned weight and every other buffer to match.
        derived_buffer = "renderer.flame_model.J_regressor_up"
        if derived_buffer not in checkpoint:
            checkpoint[derived_buffer] = model.state_dict()[derived_buffer]
        model.load_state_dict(checkpoint, strict=True)
        del checkpoint
        model.eval().to("cuda")

        stage("reconstructing_gaussians")
        with torch.no_grad():
            flame_data = {"betas": shape.unsqueeze(0).to("cuda")}
            points, flame_data = model.renderer.get_query_points(flame_data, device=torch.device("cuda"))
            latent, image_features = model.forward_latent_points(image.to("cuda"), camera=None, query_points=points)
            gaussians, _, _, _ = model.renderer.forward_gs(latent, points, flame_data)
            vertices = points[0].cpu().numpy()
            faces = model.renderer.flame_model.faces_up.cpu().numpy()
            offset_path = args.job_dir / "offset.ply"
            gaussians[0].save_ply(str(offset_path), rgb2sh=False, offset2xyz=True)

        if args.upstream_baseline:
            stage("rendering_native_baseline")
            from native_baseline import render_baseline
            render_baseline(model, gaussians, points, shape, Path(tracked), args.output)

        stage("exporting_arkit_avatar")
        from export_asset import export_avatar
        exported = export_avatar(vertices, faces, offset_path, args.output / "avatar.zip",
                                 root / "assets/sample_oac/template_file.fbx", sample)
        # Only rebind eye motion generically. Facial proportions are identity-
        # specific art direction and must never be changed on every portrait.
        if not args.upstream_baseline:
            from calibrate_asset import calibrate
            calibrated = args.output / "avatar-calibrated.zip"
            exported["rig_calibration"] = calibrate(args.output / "avatar.zip", calibrated)
            calibrated.replace(args.output / "avatar.zip")
        else:
            exported["rig_calibration"] = {"applied": False, "scope": "upstream_baseline"}
        from source_camera import source_camera
        flame = model.renderer.flame_model
        with torch.no_grad():
            shaped = flame.v_template + torch.einsum('vcs,s->vc', flame.shapedirs[:,:,:300], shape.to('cuda'))
            root_joint = (flame.J_regressor @ shaped)[0].cpu().numpy()
        exported["source_camera"] = source_camera(Path(tracked), exported["template_translation"], root_joint)
        timings[previous_stage] = round((time.monotonic() - previous_time) * 1000)
        manifest = {
            "engine": "LAM-20K", "lam_commit": "339573649dd93df4cba8093a964e85a80d1b61f3",
            "diffusers_version": diffusers_version,
            "joint_attention_normalization": "sample_and_context_qk",
            "web_render_commit": "12174e944957fc6445f235c5e0ff7e3e16ba209a",
            "model_sha256": "f527e6e78fd9743aad95cb15b221b864d8b6d356c1d174c0ffad5d74b9a95925",
            "input_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
            "asset_sha256": hashlib.sha256((args.output / "avatar.zip").read_bytes()).hexdigest(),
            "license": "LAM weights CC-BY-NC-4.0; FLAME and third-party terms apply",
            "preview_type": "segmented_source_image",
            "timings_ms": timings, "duration_ms": round((time.monotonic() - started) * 1000), **exported,
        }
        (args.output / "generation.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
        stage("complete", asset_path=str(args.output / "avatar.zip"), **exported)
    except BaseException as exc:
        stage("failed", error=str(exc), error_type=type(exc).__name__)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
