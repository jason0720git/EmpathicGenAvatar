ARG BASE_IMAGE=empathic-avatar-avatar-worker:latest
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TORCH_CUDA_ARCH_LIST="12.0" MAX_JOBS=4 TORCHDYNAMO_DISABLE=1 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
RUN apt-get update && apt-get install -y --no-install-recommends git libxi6 libxrender1 libxfixes3 libxkbcommon0 libsm6 libgl1-mesa-dev libegl1-mesa-dev && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir "numpy<2" "transformers==4.41.2" "diffusers==0.30.2" "huggingface_hub==0.30.2" "trimesh==4.4.9" "moviepy==1.0.3" pandas plyfile jaxtyping typeguard tyro loguru ninja matplotlib tensorboard timm fvcore iopath chumpy
RUN FORCE_CUDA=1 python -m pip install --no-build-isolation --no-cache-dir git+https://github.com/facebookresearch/pytorch3d.git@978cd99221b9e0a6a568f1d427854d73363265cf
RUN python -m pip install --no-build-isolation --no-cache-dir git+https://github.com/ashawkey/diff-gaussian-rasterization/@8829d14f814fccdaf840b7b0f3021a616583c0a1 nvdiffrast@git+https://github.com/ShenhanQian/nvdiffrast@22718580f24a313c429ba2c304794c264351f108
RUN python -m pip install --no-cache-dir "scipy==1.13.1" "tyro==0.8.14" "opencv-python-headless==4.11.0.86" "librosa==0.10.2.post1" "diffusers==0.32.2"
WORKDIR /gaussian-worker
COPY . /gaussian-worker
EXPOSE 8020
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
