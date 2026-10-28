"""Download the official LAM research assets, checking the published SHA-256.

Run explicitly; startup never downloads model files or sends portraits off-device.
Upstream model weights are CC-BY-NC 4.0. FLAME and bundled third-party assets
retain their own terms (see docs/gaussian-generation-research.md).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

FILES = [
    ("3DAIGC/LAM-assets", "LAM_assets.tar", "f8853a6678df2e08f4c27b3ed8ae625d29bc64500330b0bfebf45e64ff5af78f"),
    ("3DAIGC/LAM-assets", "thirdparty_models.tar", "2ac5eba7c1abca0ab6c682ad900ddb8819b713506043b04874599c82572931c8"),
    ("3DAIGC/LAM-20K", "model.safetensors", "f527e6e78fd9743aad95cb15b221b864d8b6d356c1d174c0ffad5d74b9a95925"),
]
TEMPLATE_URL = "https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/LAM/sample_oac.tar"
TEMPLATE_SHA256 = "5b69908f159ad9c8b966c2d4b24f9c5a0f84f3535dbf6100ed269f708886a19d"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(item: tuple[str, str, str], cache: Path) -> Path:
    repo, name, digest = item
    target = cache / name
    if target.exists() and sha256(target) == digest:
        print(json.dumps({"event": "asset_cached", "file": name}), flush=True)
        return target
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(f"https://huggingface.co/{repo}/resolve/main/{name}")
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
        while block := response.read(8 * 1024 * 1024):
            output.write(block)
    if sha256(partial) != digest:
        raise RuntimeError(f"Checksum mismatch: {name}")
    partial.replace(target)
    print(json.dumps({"event": "asset_downloaded", "file": name, "sha256": digest}), flush=True)
    return target


def download_template(cache: Path) -> Path:
    path = cache / "sample_oac.tar"
    if not path.exists() or sha256(path) != TEMPLATE_SHA256:
        partial = path.with_suffix(".part")
        with urllib.request.urlopen(TEMPLATE_URL, timeout=120) as response, partial.open("wb") as stream:
            while block := response.read(8 * 1024 * 1024):
                stream.write(block)
        if sha256(partial) != TEMPLATE_SHA256:
            raise RuntimeError("Template checksum mismatch")
        partial.replace(path)
    return path


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or member.issym() or member.islnk():
                raise ValueError(f"Unsafe archive member: {member.name}")
        bundle.extractall(destination, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lam-root", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        paths = list(pool.map(lambda item: download(item, args.cache), FILES))
    for path in paths:
        if path.suffix == ".tar":
            safe_extract(path, args.lam_root)
        else:
            target = args.lam_root / "model_zoo/lam_models/releases/lam/lam-20k/step_045500" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            expected = next(item[2] for item in FILES if item[1] == path.name)
            if not target.exists() or sha256(target) != expected:
                import shutil
                partial = target.with_suffix(target.suffix + ".part")
                shutil.copy2(path, partial)
                partial.replace(target)
    safe_extract(download_template(args.cache), args.lam_root / "assets")
    print(json.dumps({"event": "assets_ready", "lam_root": str(args.lam_root)}), flush=True)


if __name__ == "__main__":
    main()
