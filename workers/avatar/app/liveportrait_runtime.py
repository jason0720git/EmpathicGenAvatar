"""Cached LivePortrait head-motion base frames for the MuseTalk product path."""
from __future__ import annotations

import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class MotionAvatar:
    frames: list[np.ndarray]


class LivePortraitMotionRuntime:
    """Generates an avatar-specific, low-amplitude motion loop once.

    MuseTalk consumes the resulting frames afterwards and remains the final
    mouth renderer.  LivePortrait therefore never overwrites generated lips.
    """

    def __init__(self, root: Path, model_root: Path, frames: int = 50, template_name: str = "talking.pkl"):
        self.root = root
        self.model_root = model_root
        self.frames = frames
        self.template_name = template_name
        self.wrapper = None
        self.avatars: dict[str, MotionAvatar] = {}

    def _load(self) -> None:
        if self.wrapper is not None:
            return
        required = [
            self.model_root / "liveportrait" / "base_models" / name
            for name in ("appearance_feature_extractor.pth", "motion_extractor.pth", "warping_module.pth", "spade_generator.pth")
        ] + [self.model_root / "liveportrait" / "retargeting_models" / "stitching_retargeting_module.pth"]
        required.append(self.root / "assets" / "examples" / "driving" / self.template_name)
        missing = [str(item) for item in required if not item.is_file()]
        if missing:
            raise RuntimeError("LivePortrait assets are incomplete: " + ", ".join(missing))
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        import torch
        from src.config.inference_config import InferenceConfig
        from src.live_portrait_wrapper import LivePortraitWrapper

        cfg = InferenceConfig(
            checkpoint_F=str(self.model_root / "liveportrait" / "base_models" / "appearance_feature_extractor.pth"),
            checkpoint_M=str(self.model_root / "liveportrait" / "base_models" / "motion_extractor.pth"),
            checkpoint_W=str(self.model_root / "liveportrait" / "base_models" / "warping_module.pth"),
            checkpoint_G=str(self.model_root / "liveportrait" / "base_models" / "spade_generator.pth"),
            checkpoint_S=str(self.model_root / "liveportrait" / "retargeting_models" / "stitching_retargeting_module.pth"),
            flag_use_half_precision=True,
            flag_do_torch_compile=False,
            flag_do_crop=False,
            flag_pasteback=False,
            flag_relative_motion=True,
        )
        # Official weights predate PyTorch's weights_only=True default.
        original_load = torch.load
        def load_legacy(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_load(*args, **kwargs)
        torch.load = load_legacy
        try:
            self.wrapper = LivePortraitWrapper(cfg)
        finally:
            torch.load = original_load
        self.torch = torch
        from src.utils.camera import get_rotation_matrix
        self.get_rotation_matrix = get_rotation_matrix

    def _motion_template(self) -> list[dict]:
        """Load an upstream compact motion template, never a user video.

        `talking.pkl` contains learned head pose, blink, cheek, and expression
        keypoints.  Its lip movement is intentionally replaced by MuseTalk in
        the next stage, avoiding two competing lip drivers.
        """
        template_path = self.root / "assets" / "examples" / "driving" / self.template_name
        with template_path.open("rb") as handle:
            template = pickle.load(handle)
        motion = template.get("motion")
        if not isinstance(motion, list) or len(motion) < 2:
            raise RuntimeError(f"LivePortrait motion template is invalid: {template_path}")
        return motion

    @staticmethod
    def _face_box(frame: np.ndarray) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        cascade = Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml")
        found = []
        if cascade.is_file():
            detector = cv2.CascadeClassifier(str(cascade))
            found = detector.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.08, 5, minSize=(80, 80))
        if len(found) == 1:
            x, y, w, h = [int(value) for value in found[0]]
            return x, y, x + w, min(height, y + h + 10)
        return int(width * .27), int(height * .27), int(width * .73), int(height * .70)

    def prepare(self, avatar_id: str, source: Path) -> list[np.ndarray]:
        cached = self.avatars.get(avatar_id)
        if cached:
            return cached.frames
        self._load()
        frame = cv2.imread(str(source))
        if frame is None:
            raise RuntimeError("LivePortrait could not read source image")
        x1, y1, x2, y2 = self._face_box(frame)
        face = frame[y1:y2, x1:x2]
        if face.size == 0:
            raise RuntimeError("LivePortrait source face crop is empty")
        source_rgb = cv2.cvtColor(cv2.resize(face, (256, 256), interpolation=cv2.INTER_LANCZOS4), cv2.COLOR_BGR2RGB)
        wrapper = self.wrapper
        assert wrapper is not None
        source_tensor = wrapper.prepare_source(source_rgb)
        with self.torch.inference_mode():
            info = wrapper.get_kp_info(source_tensor)
            feature = wrapper.extract_feature_3d(source_tensor)
            source_kp = wrapper.transform_keypoint(info)
            canonical = info["kp"]
            source_rotation = self.get_rotation_matrix(info["pitch"], info["yaw"], info["roll"])
            motion = self._motion_template()
            motion_zero = motion[0]
            result: list[np.ndarray] = []
            for index in range(self.frames):
                # Evenly sample a learned, expression-rich talking template.
                # Relative motion preserves the identity and neutral pose of
                # the supplied portrait rather than copying the template face.
                template_index = round(index * (len(motion) - 1) / max(1, self.frames - 1))
                driving_info = motion[template_index]
                rotation_key = "R" if "R" in driving_info else "R_d"
                rotation_zero = motion_zero[rotation_key]
                motion_rotation = self.torch.as_tensor(driving_info[rotation_key], dtype=self.torch.float32, device=source_tensor.device)
                motion_rotation_zero = self.torch.as_tensor(rotation_zero, dtype=self.torch.float32, device=source_tensor.device)
                expression = self.torch.as_tensor(driving_info["exp"], dtype=self.torch.float32, device=source_tensor.device)
                expression_zero = self.torch.as_tensor(motion_zero["exp"], dtype=self.torch.float32, device=source_tensor.device)
                translation = self.torch.as_tensor(driving_info["t"], dtype=self.torch.float32, device=source_tensor.device)
                translation_zero = self.torch.as_tensor(motion_zero["t"], dtype=self.torch.float32, device=source_tensor.device)
                rotation = (motion_rotation @ motion_rotation_zero.transpose(1, 2)) @ source_rotation
                driving = canonical @ rotation + (info["exp"] + (expression - expression_zero) * 0.72)
                driving *= info["scale"][..., None]
                driving[:, :, 0:2] += (info["t"] + (translation - translation_zero) * 0.72)[:, None, 0:2]
                driving = wrapper.stitching(source_kp, driving)
                output_rgb = wrapper.parse_output(wrapper.warp_decode(feature, source_kp, driving)["out"])[0]
                output_bgr = cv2.cvtColor(output_rgb, cv2.COLOR_RGB2BGR)
                output_bgr = cv2.resize(output_bgr, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LANCZOS4)
                composed = frame.copy()
                # Feathered full-face blend retains the original hair/background
                # while LivePortrait supplies pose/expression base motion.
                alpha = np.zeros(frame.shape[:2], dtype=np.uint8)
                cv2.ellipse(alpha, ((x1+x2)//2, (y1+y2)//2), (max(4, (x2-x1)//2), max(4, (y2-y1)//2)), 0, 0, 360, 255, -1)
                alpha = cv2.GaussianBlur(alpha, (0, 0), max(2, (x2-x1) * .025))
                patch = frame.copy()
                patch[y1:y2, x1:x2] = output_bgr
                a = (alpha.astype(np.float32) / 255.)[..., None]
                result.append((patch * a + frame * (1 - a)).astype(np.uint8))
        self.avatars[avatar_id] = MotionAvatar(result)
        return result
