"""Local, single-job LAM generation service. Heavy CUDA work is subprocess isolated."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("GAUSSIAN_DATA_ROOT", "/gaussian-data")).resolve()
LAM_ROOT = Path(os.environ.get("LAM_ROOT", "/opt/lam")).resolve()
SAMPLE_ZIP = Path(os.environ.get("LAM_TEMPLATE_ZIP", "/opt/lam-web/asset/arkit/p2-1.zip"))
REQUIRED = ["model_zoo/lam_models/releases/lam/lam-20k/step_045500/model.safetensors",
            "model_zoo/flame_tracking_models/68_keypoints_model.pkl",
            "model_zoo/flame_tracking_models/vgghead/vgg_heads_l.trcd",
            "model_zoo/flame_tracking_models/matting/stylematte_synth.pt",
            "model_zoo/flame_tracking_models/FaceBoxesV2.pth",
            "assets/sample_oac/template_file.fbx"]
app = FastAPI(title="Local LAM 3DGS avatar generator")
lock = threading.Lock()
state = {"phase": "idle", "active_job": None, "last_error": None}
try:
    import torch
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    CUDA_AVAILABLE = False
try:
    from compatibility import validate_joint_attention
    RUNTIME_COMPATIBILITY = validate_joint_attention()
except Exception as exc:
    RUNTIME_COMPATIBILITY = {"compatible": False, "error": str(exc)}


class GenerateRequest(BaseModel):
    job_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    image_path: str
    output_dir: str


def safe_path(raw: str) -> Path:
    path = Path(raw).resolve()
    if not path.is_relative_to(ROOT):
        raise HTTPException(400, "Path must remain under GAUSSIAN_DATA_ROOT")
    return path


def job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
        raise HTTPException(400, "Invalid job ID")
    return ROOT / "jobs" / job_id


@app.get("/health")
def health():
    missing = [name for name in REQUIRED if not (LAM_ROOT / name).is_file()]
    if not SAMPLE_ZIP.is_file():
        missing.append(str(SAMPLE_ZIP))
    payload = {"ready": not missing and CUDA_AVAILABLE and RUNTIME_COMPATIBILITY["compatible"], "assets_ready": not missing,
               "cuda_available": CUDA_AVAILABLE, "engine": "LAM-20K", "missing_assets": missing,
               "readiness_scope": "assets_cuda_and_attention_math",
               "runtime_compatibility": RUNTIME_COMPATIBILITY,
               "verified_generation": (ROOT / "generator-verification.json").is_file(),
               "model_license": "CC-BY-NC-4.0; FLAME and dependency terms apply", **state}
    if state["active_job"]:
        path = job_path(state["active_job"]) / "status.json"
        if path.exists():
            try:
                payload["progress"] = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                pass
    return payload


@app.get("/jobs/{job_id}")
def job(job_id: str):
    path = job_path(job_id) / "status.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    return json.loads(path.read_text())


@app.post("/generate")
def generate(request: GenerateRequest):
    source = safe_path(request.image_path)
    output = safe_path(request.output_dir)
    if not source.is_file():
        raise HTTPException(404, "Source image does not exist")
    if not health()["ready"]:
        raise HTTPException(503, health())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Another avatar generation job is running")
    work = job_path(request.job_id)
    state.update(phase="generating", active_job=request.job_id, last_error=None)
    started = time.monotonic()
    try:
        work.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(Path(__file__).with_name("generate.py")),
                   "--image", str(source), "--output", str(output), "--job-dir", str(work)]
        with (work / "worker.log").open("w", encoding="utf8") as log:
            proc = subprocess.Popen(command, cwd=LAM_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                code = proc.wait(timeout=int(os.environ.get("LAM_JOB_TIMEOUT_SECONDS", "1200")))
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise RuntimeError("LAM job exceeded the configured timeout; see worker.log")
        if code:
            status_path = work / "status.json"
            detail = json.loads(status_path.read_text()) if status_path.exists() else {}
            raise RuntimeError(detail.get("error", f"LAM generation exited with code {code}; see worker.log"))
        manifest_path = output / "generation.json"
        manifest = json.loads(manifest_path.read_text())
        (ROOT / "generator-verification.json").write_text(json.dumps({
            "last_successful_job": request.job_id,
            "asset_sha256": manifest["asset_sha256"],
            "duration_ms": manifest["duration_ms"],
        }), encoding="utf8")
        return {"asset_path": str(output / "avatar.zip"), "manifest_path": str(manifest_path),
                "preview_path": str(output / "preview.png"), "duration_ms": round((time.monotonic() - started) * 1000),
                "manifest": manifest}
    except Exception as exc:
        state["last_error"] = str(exc)
        raise HTTPException(500, str(exc)) from exc
    finally:
        state.update(phase="idle", active_job=None)
        lock.release()
