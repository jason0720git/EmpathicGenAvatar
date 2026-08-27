# The upstream release was tested on TensorRT 8.6.1/A100. This newer image is
# needed to load or rebuild engines on an RTX 50-series host.
ARG BASE_IMAGE=nvcr.io/nvidia/tensorrt:25.02-py3
FROM ${BASE_IMAGE}

WORKDIR /worker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends espeak-ng ffmpeg libgl1 libegl1 libgles2 libglib2.0-0 opencv-data && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu128
# Ditto imports the pre-13 `from cuda import cuda, cudart, nvrtc` API. Keep it
# aligned with Torch's supported CUDA bindings instead of installing v13.
RUN python3 -m pip install --no-cache-dir "cuda-python==12.9.4"
# TensorRT 25.02 provides CUDA 12.8. ORT >= 1.27 defaults to CUDA 13 and
# silently falls back to CPU here, which breaks real-time pacing.
RUN python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" "pydantic>=2.9,<3.0" librosa tqdm filetype imageio opencv-python-headless scikit-image cython imageio-ffmpeg colored polygraphy numpy "onnxruntime-gpu==1.26.0" mediapipe einops "diffusers==0.30.2" "accelerate==0.28.0" "transformers==4.39.2" "huggingface_hub==0.30.2" omegaconf "soundfile==0.12.1" pyyaml rich gdown
COPY app ./app
EXPOSE 8010
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
