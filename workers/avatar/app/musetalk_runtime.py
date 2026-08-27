"""Persistent MuseTalk 1.5 renderer for the one-photo prototype.

The upstream real-time script is CLI-oriented and saves a full MP4.  This
adapter keeps its model objects and avatar preparation in memory, then emits
each composited BGR frame to the worker's existing live frame sink.  It is
intentionally single-render-at-a-time: the GPU model globals are shared and a
new turn must never interleave frame clocks with an active turn.
"""
from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


@dataclass
class PreparedAvatar:
    frame: np.ndarray
    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    mask_crop_box: list[int]
    latent: object


class MuseTalkRuntime:
    """One-image, 25fps MuseTalk 1.5 runtime with avatar-level caching."""

    def __init__(self, root: Path, model_root: Path, batch_size: int = 8):
        self.root = root
        self.model_root = model_root
        self.batch_size = batch_size
        self.loaded = False
        # Each avatar may have a small LivePortrait-generated base-motion
        # loop.  MuseTalk remains the final (mouth-last) stage for every
        # member of that loop, keeping audio articulation independent from
        # head pose / eye / expression animation.
        self.avatars: dict[str, list[PreparedAvatar]] = {}

    def _load(self) -> None:
        if self.loaded:
            return
        required = [
            self.root / "musetalk" / "utils" / "utils.py",
            self.model_root / "musetalkV15" / "unet.pth",
            self.model_root / "musetalkV15" / "musetalk.json",
            self.model_root / "sd-vae" / "diffusion_pytorch_model.bin",
            self.model_root / "whisper" / "pytorch_model.bin",
            self.model_root / "face-parse-bisent" / "79999_iter.pth",
            self.model_root / "face-parse-bisent" / "resnet18-5c106cde.pth",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("MuseTalk 1.5 assets are incomplete: " + ", ".join(missing))
        # Several upstream modules contain relative checkpoint paths.  The
        # worker process has one renderer lock, so making this cwd stable is
        # safe and prevents a duplicate copy of source/checkpoints.
        os.chdir(self.root)
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        import torch
        from transformers import WhisperModel
        from musetalk.utils.audio_processor import AudioProcessor
        # BiSeNet's actual lower-face segmentation is essential here; a
        # generic ellipse mask causes the visibly blurred moving patch.
        from musetalk.utils.blending import get_image_blending, get_image_prepare_material
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.models.unet import PositionalEncoding, UNet
        from musetalk.models.vae import VAE
        from musetalk.utils.utils import datagen

        self.torch = torch
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        if self.device.type != "cuda":
            raise RuntimeError("MuseTalk live mode requires CUDA; CPU inference is not an interactive renderer")
        self.vae = VAE(model_path=str(self.model_root / "sd-vae"))
        self.unet = UNet(
            unet_config=str(self.model_root / "musetalkV15" / "musetalk.json"),
            model_path=str(self.model_root / "musetalkV15" / "unet.pth"),
            device=self.device,
        )
        self.pe = PositionalEncoding(d_model=384)
        self.pe = self.pe.half().to(self.device)
        self.vae.vae = self.vae.vae.half().to(self.device)
        self.unet.model = self.unet.model.half().to(self.device)
        self.unet.model.eval()
        self.audio_processor = AudioProcessor(feature_extractor_path=str(self.model_root / "whisper"))
        self.whisper = WhisperModel.from_pretrained(str(self.model_root / "whisper")).to(
            device=self.device, dtype=self.unet.model.dtype
        ).eval()
        self.whisper.requires_grad_(False)
        model_root = self.model_root

        class ConfiguredFaceParsing(FaceParsing):
            def model_init(self, resnet_path=None, model_pth=None):
                return super().model_init(
                    resnet_path=str(model_root / "face-parse-bisent" / "resnet18-5c106cde.pth"),
                    model_pth=str(model_root / "face-parse-bisent" / "79999_iter.pth"),
                )

        # MuseTalk's published BiSeNet checkpoints use PyTorch's legacy tar
        # serialization.  PyTorch 2.6+ defaults to `weights_only=True`; load
        # these locally audited upstream checkpoints only while constructing
        # the parser, then restore the safe default immediately.
        original_torch_load = torch.load

        def load_legacy_checkpoint(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_torch_load(*args, **kwargs)

        torch.load = load_legacy_checkpoint
        try:
            self.face_parser = ConfiguredFaceParsing(left_cheek_width=90, right_cheek_width=90)
        finally:
            torch.load = original_torch_load
        self.get_image_prepare_material = get_image_prepare_material
        self.get_image_blending = get_image_blending
        self.datagen = datagen
        self.timesteps = torch.tensor([0], device=self.device)
        self.loaded = True

    def prepare(self, avatar_id: str, source: Path) -> None:
        frame = cv2.imread(str(source))
        if frame is None:
            raise RuntimeError("MuseTalk could not read the source image")
        self.prepare_frames(avatar_id, [frame])

    def prepare_frames(self, avatar_id: str, frames: list[np.ndarray]) -> None:
        if avatar_id in self.avatars:
            return
        self._load()
        if not frames:
            raise RuntimeError("MuseTalk requires at least one base frame")
        prepared: list[PreparedAvatar] = []
        for frame in frames:
            prepared.append(self._prepare_frame(frame))
        self.avatars[avatar_id] = prepared

    def _prepare_frame(self, frame: np.ndarray) -> PreparedAvatar:
        cascade_candidates = [
            Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml",
            Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"),
        ]
        cascade_path = next((path for path in cascade_candidates if path.is_file()), None)
        detector = cv2.CascadeClassifier(str(cascade_path)) if cascade_path else None
        faces = [] if detector is None else detector.detectMultiScale(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), scaleFactor=1.08, minNeighbors=5, minSize=(80, 80)
        )
        if len(faces) == 1:
            x, y, width, height = [int(value) for value in faces[0]]
            x1, y1, x2, y2 = x, y, x + width, min(y + height + 10, frame.shape[0])
        else:
            # Generated illustrations can fail a photographic detector.  This
            # crop is intentionally face-sized (not a portrait-sized central
            # crop): MuseTalk was trained on an aligned facial region, and a
            # crop including hair, shoulders, and background becomes a blurry
            # moving texture instead of a mouth.
            image_height, image_width = frame.shape[:2]
            x1, x2 = int(image_width * 0.27), int(image_width * 0.73)
            y1, y2 = int(image_height * 0.27), int(image_height * 0.70)
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError("MuseTalk produced an invalid face crop")
        crop = frame[y1:y2, x1:x2]
        resized = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latent = self.vae.get_latents_for_unet(resized)
        mask, mask_crop_box = self.get_image_prepare_material(
            frame, [x1, y1, x2, y2], fp=self.face_parser, mode="jaw"
        )
        return PreparedAvatar(
            frame=frame, bbox=(x1, y1, x2, y2), mask=mask, mask_crop_box=mask_crop_box, latent=latent
        )

    def render(self, avatar_id: str, audio: Path, emit: Callable[[np.ndarray, str], None]) -> int:
        avatars = self.avatars.get(avatar_id)
        if not avatars:
            raise RuntimeError("MuseTalk avatar was not prepared")
        inputs, sample_count = self.audio_processor.get_audio_feature(str(audio), weight_dtype=self.unet.model.dtype)
        chunks = self.audio_processor.get_whisper_chunk(
            inputs, self.device, self.unet.model.dtype, self.whisper, sample_count,
            fps=25, audio_padding_length_left=2, audio_padding_length_right=2,
        )
        emitted = 0
        with self.torch.inference_mode():
            # Upstream datagen cycles the latent list.  The identical modulo
            # index below selects the matching full-frame/mask for compositing.
            for whisper_batch, latent_batch in self.datagen(chunks, [item.latent for item in avatars], self.batch_size):
                audio_features = self.pe(whisper_batch.to(self.device))
                latent_batch = latent_batch.to(device=self.device, dtype=self.unet.model.dtype)
                predicted = self.unet.model(latent_batch, self.timesteps, encoder_hidden_states=audio_features).sample
                reconstructed = self.vae.decode_latents(predicted.to(device=self.device, dtype=self.vae.vae.dtype))
                for face in reconstructed:
                    avatar = avatars[emitted % len(avatars)]
                    x1, y1, x2, y2 = avatar.bbox
                    face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
                    composed = self.get_image_blending(
                        copy.deepcopy(avatar.frame), face, [x1, y1, x2, y2], avatar.mask, avatar.mask_crop_box
                    )
                    emit(composed, "bgr")
                    emitted += 1
        return emitted
