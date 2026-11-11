"""Source-relative listening strokes and Seoyeon's registered portrait matte."""
from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class NodStroke:
    start_ms: int
    peak_pitch_delta_deg: float
    down_ms: int = 240
    up_ms: int = 320

    def pitch(self, time_ms: float) -> float:
        elapsed = time_ms - self.start_ms
        if elapsed <= 0 or elapsed >= self.down_ms + self.up_ms:
            return 0.
        phase = elapsed / self.down_ms if elapsed <= self.down_ms else 1 - (elapsed - self.down_ms) / self.up_ms
        # Zero velocity and acceleration on entry, at the apex and on exit.
        return self.peak_pitch_delta_deg * phase**3 * (10 + phase * (-15 + 6 * phase))


LISTENING_NODS = {
    2: (NodStroke(2400, 4.0), NodStroke(10200, 4.0), NodStroke(10880, 1.8)),
    3: (NodStroke(320, 4.0),),
    5: (NodStroke(320, 4.0), NodStroke(1000, 1.8)),
}


def idle_variant_policy(variant: int, frames: int, fps: int) -> dict:
    strokes = LISTENING_NODS.get(variant, ())
    return {"variant": variant, "frames": frames, "fps": fps, "cycles": len(strokes),
            "nods": [asdict(stroke) for stroke in strokes]}


def registered_head_mask(native_mask: np.ndarray, image: np.ndarray,
                         crop_to_source: np.ndarray, landmark478) -> np.ndarray:
    """Keep the native face/hair blend and fade to the photo across the upper neck.

    Ditto's original and generated crops share this registration. Only the paste
    alpha changes; the source, face geometry and decoded pixels are never moved.
    The face mesh is evaluated once per source using Ditto's existing detector.
    """
    height, width = native_mask.shape[:2]
    crop = cv2.warpAffine(image, crop_to_source[:2], (width, height),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    mesh = np.asarray(landmark478(crop)).reshape(478, 3)
    brow_y, chin_y = mesh[10, 1], mesh[152, 1]
    cheek_left, cheek_right = sorted((mesh[234, 0], mesh[454, 0]))
    face_height = chin_y - brow_y
    face_width = cheek_right - cheek_left
    if not (.12 < face_height < .95 and .12 < face_width < .95):
        raise ValueError("Unexpected face mesh geometry for Seoyeon's head mask")
    y, x = np.ogrid[:height, :width]
    center_x = (cheek_left + cheek_right) / 2
    # Below the central jaw there is a little free neck. At the sides the
    # upper shoulders/collar meet the hair sooner, so taper earlier there.
    side = np.clip(np.abs(x / width - center_x) / (.5 * face_width), 0, 1)
    side = side * side * (3 - 2 * side)
    fade_from = chin_y + (.08 - .18 * side) * face_height
    weight = np.clip((fade_from + .24 * face_height - y / height) / (.24 * face_height), 0, 1)
    weight = weight * weight * (3 - 2 * weight)
    if native_mask.ndim == 3:
        weight = weight[..., None]
    return np.ascontiguousarray(native_mask * weight, dtype=np.float32)
