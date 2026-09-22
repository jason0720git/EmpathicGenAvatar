# Extracted from SOBIA-Unity Tools/mediapipe_webcam_bridge (2026-09-21).
# Only single-face geometry + EmotionClassifier dependency closure is retained.
# Local differences: neutral score exposed; ONNX thread counts bounded.
from __future__ import annotations
import json, math, sys, time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

LEFT_EYE_INDICES = (362, 385, 387, 263, 373, 380)

RIGHT_EYE_INDICES = (33, 160, 158, 133, 153, 144)

FACE_WIDTH_INDICES = (234, 454)

NOSE_TIP_INDEX = 1

APPARENT_AFFECT_PROVIDER = "mediapipe-face-blendshape-rules-v1"

APPARENT_EKMAN_PROVIDER = "mediapipe-face-blendshape-ekman-rules-v1"

APPARENT_AFFECT_CUE_NAMES = (
    "smile",
    "frown",
    "browRaise",
    "browTension",
    "eyeClosure",
    "eyeSquint",
    "mouthOpen",
    "mouthPress",
    "mouthPucker",
    "noseSneer",
)

APPARENT_EKMAN_NAMES = (
    "happiness",
    "sadness",
    "anger",
    "fear",
    "surprise",
    "disgust",
)

EMOTION_CLASSIFIER_LABELS = (
    "neutral",
    "happiness",
    "sadness",
    "anger",
    "fear",
    "surprise",
    "disgust",
)

EMOTION_CLASSIFIER_PROVIDER_FALLBACK = "emotion-classifier-rafdb-classwise-fusion-v1"

@dataclass(frozen=True)
class Point3:
    x: float
    y: float
    z: float = 0.0

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

def finite_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if math.isfinite(result) else fallback

def average_landmarks(landmarks: Sequence[Any], indices: Iterable[int]) -> Optional[Point3]:
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    for index in indices:
        if index < 0 or index >= len(landmarks):
            continue
        landmark = landmarks[index]
        xs.append(finite_float(getattr(landmark, "x", 0.0)))
        ys.append(finite_float(getattr(landmark, "y", 0.0)))
        zs.append(finite_float(getattr(landmark, "z", 0.0)))

    if not xs:
        return None
    return Point3(sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))

def landmark_point(landmarks: Sequence[Any], index: int) -> Optional[Point3]:
    if index < 0 or index >= len(landmarks):
        return None
    landmark = landmarks[index]
    return Point3(
        finite_float(getattr(landmark, "x", 0.0)),
        finite_float(getattr(landmark, "y", 0.0)),
        finite_float(getattr(landmark, "z", 0.0)),
    )

def face_width_01(landmarks: Sequence[Any]) -> float:
    a = landmark_point(landmarks, FACE_WIDTH_INDICES[0])
    b = landmark_point(landmarks, FACE_WIDTH_INDICES[1])
    if a is None or b is None:
        return 0.0
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)

def matrix_to_euler_degrees(matrix: Any) -> Point3:
    """Extract approximate XYZ Euler angles from a 4x4 MediaPipe face matrix."""

    try:
        import numpy as np  # type: ignore

        m = np.array(matrix, dtype=float).reshape((4, 4))
    except Exception:
        return Point3(0.0, 0.0, 0.0)

    r00, r01, r02 = m[0, 0], m[0, 1], m[0, 2]
    r10, r11, r12 = m[1, 0], m[1, 1], m[1, 2]
    r20, r21, r22 = m[2, 0], m[2, 1], m[2, 2]
    sy = math.sqrt((r00 * r00) + (r10 * r10))
    singular = sy < 1e-6

    if not singular:
        pitch = math.atan2(r21, r22)
        yaw = math.atan2(-r20, sy)
        roll = math.atan2(r10, r00)
    else:
        pitch = math.atan2(-r12, r11)
        yaw = math.atan2(-r20, sy)
        roll = 0.0

    return Point3(math.degrees(pitch), math.degrees(yaw), math.degrees(roll))

def extract_blendshapes(face_blendshapes: Any, face_index: int = 0) -> list[dict[str, float]]:
    if not face_blendshapes:
        return []

    if face_index < 0 or face_index >= len(face_blendshapes):
        return []

    categories = face_blendshapes[face_index]
    payload: list[dict[str, float]] = []
    for category in categories:
        name = getattr(category, "category_name", "")
        if not name:
            continue
        payload.append({"name": str(name), "score": finite_float(getattr(category, "score", 0.0))})
    return payload

def blendshape_score(
    scores: dict[str, float],
    *names: str,
) -> float:
    values = [max(0.0, min(1.0, finite_float(scores.get(name), 0.0))) for name in names]
    return max(values) if values else 0.0

def blendshape_average(
    scores: dict[str, float],
    *names: str,
) -> float:
    values = [max(0.0, min(1.0, finite_float(scores.get(name), 0.0))) for name in names]
    return sum(values) / len(values) if values else 0.0

def apparent_affect_label(
    valence: float,
    arousal: float,
    positive: float,
    negative: float,
    surprise: float,
    uncertainty: float,
) -> str:
    if surprise >= 0.48 and arousal >= 0.45:
        return "apparent_surprise"
    if positive >= 0.45 and valence > 0.18:
        return "apparent_positive"
    if negative >= 0.42 and valence < -0.12:
        return "apparent_negative"
    if uncertainty >= 0.42:
        return "apparent_uncertain"
    if arousal >= 0.55:
        return "apparent_alert"
    return "apparent_neutral"

def apparent_ekman_label(scores: dict[str, float]) -> str:
    best_name = "happiness"
    best_score = -1.0
    for name in APPARENT_EKMAN_NAMES:
        score = max(0.0, min(1.0, finite_float(scores.get(name), 0.0)))
        if score > best_score:
            best_name = name
            best_score = score
    return best_name

def softmax_vector(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    clean = [finite_float(value, 0.0) for value in values]
    peak = max(clean)
    exp_values = [math.exp(max(-80.0, min(80.0, value - peak))) for value in clean]
    total = sum(exp_values)
    if total <= 0.0:
        return [1.0 / len(clean) for _ in clean]
    return [value / total for value in exp_values]

def emotion_label_to_apparent_affect_label(label: str) -> str:
    normalized = (label or "").strip().lower()
    if normalized == "neutral":
        return "apparent_neutral"
    if normalized == "happiness":
        return "apparent_positive"
    if normalized == "surprise":
        return "apparent_surprise"
    if normalized in ("sadness", "anger", "fear", "disgust"):
        return "apparent_negative"
    return "apparent_unknown"

def emotion_probs_to_affect_values(probs: dict[str, float]) -> dict[str, float]:
    happiness = max(0.0, min(1.0, finite_float(probs.get("happiness"), 0.0)))
    sadness = max(0.0, min(1.0, finite_float(probs.get("sadness"), 0.0)))
    anger = max(0.0, min(1.0, finite_float(probs.get("anger"), 0.0)))
    fear = max(0.0, min(1.0, finite_float(probs.get("fear"), 0.0)))
    surprise = max(0.0, min(1.0, finite_float(probs.get("surprise"), 0.0)))
    disgust = max(0.0, min(1.0, finite_float(probs.get("disgust"), 0.0)))
    negative = max(0.0, min(1.0, sadness + anger + fear + disgust))
    arousal = max(0.0, min(1.0, surprise + (0.72 * anger) + (0.70 * fear) + (0.58 * disgust)))
    return {
        "valence": max(-1.0, min(1.0, happiness - negative)),
        "arousal": arousal,
        "positive": happiness,
        "negative": negative,
        "surprise": surprise,
        "uncertainty": fear,
    }

class EmotionClassifierRuntime:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent
        self.enabled = False
        self.last_error = ""
        self.provider = EMOTION_CLASSIFIER_PROVIDER_FALLBACK
        self.labels = list(EMOTION_CLASSIFIER_LABELS)
        self.image_input_name = "input"
        self.image_output_name = "logits"
        self.blendshape_input_name = "blendshape"
        self.blendshape_output_name = "logits"
        self.image_tta_hflip = False
        self.fusion_mode = "classwise_logprob"
        self.gate_input_names = {
            "gate_features": "gate_features",
            "image_log_probs": "image_log_probs",
            "blendshape_log_probs": "blendshape_log_probs",
        }
        self.gate_output_names = {
            "logits": "logits",
            "alpha": "alpha",
            "bias": "bias",
        }
        self.gate_feature_names: list[str] = []
        self.gate_feature_mean: list[float] = []
        self.gate_feature_std: list[float] = []
        self.feature_names: list[str] = []
        self.feature_mean: list[float] = []
        self.feature_std: list[float] = []
        self.alpha_by_class = {label: 0.0 for label in self.labels}
        self.bias_by_class = {label: 0.0 for label in self.labels}
        self._np = None
        self._ort = None
        self.image_session = None
        self.blendshape_session = None
        self.gated_fusion_session = None
        self.image_size = 112
        self.last_latency_ms = 0.0
        self.last_latency_breakdown_ms: dict[str, float] = {}
        self.latency_breakdown_enabled = False
        self.temporal_smoothing_enabled = False
        self.temporal_smoothing_tau_sec = 0.25
        self.temporal_smoothing_switch_margin = 0.08
        self._smoothed_probs: Optional[dict[str, float]] = None
        self._smoothing_timestamp: Optional[float] = None
        self._smoothing_label: Optional[str] = None
        self.neutral_guard_config: dict[str, Any] = {}
        self.per_class_thresholds: dict[str, dict[str, Any]] = {}
        self.hard_negative_logging_config: dict[str, Any] = {}
        self._last_hard_negative_log_at = 0.0
        self._guard_candidate_label: Optional[str] = None
        self._guard_candidate_count = 0
        self._negative_class_candidate_label: Optional[str] = None
        self._negative_class_candidate_count = 0

        self._load()

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.base_dir / path

    def _load_json(self, value: str) -> dict[str, Any]:
        path = self._resolve(value)
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _load(self) -> None:
        try:
            import numpy as np  # type: ignore
            import onnxruntime as ort  # type: ignore

            config = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            self.provider = str(config.get("provider") or self.provider)
            self.labels = [
                str(label)
                for label in config.get("labels", EMOTION_CLASSIFIER_LABELS)
                if str(label) in EMOTION_CLASSIFIER_LABELS
            ]
            if not self.labels:
                self.labels = list(EMOTION_CLASSIFIER_LABELS)

            image_metadata = self._load_json(str(config["image_metadata"]))
            blendshape_metadata = self._load_json(str(config["blendshape_metadata"]))
            self.feature_names = [str(name) for name in blendshape_metadata["feature_names"]]
            self.feature_mean = [finite_float(value, 0.0) for value in blendshape_metadata["feature_mean"]]
            self.feature_std = [max(1e-6, finite_float(value, 1.0)) for value in blendshape_metadata["feature_std"]]
            self.image_input_name = str(image_metadata.get("input_name") or "input")
            self.image_output_name = str(image_metadata.get("output_name") or "logits")
            self.blendshape_input_name = str(blendshape_metadata.get("input_name") or "blendshape")
            self.blendshape_output_name = str(blendshape_metadata.get("output_name") or "logits")
            input_shape = image_metadata.get("input_shape") or [1, 3, 112, 112]
            if isinstance(input_shape, list) and len(input_shape) >= 4:
                self.image_size = max(16, int(input_shape[-1]))
            self.image_tta_hflip = bool(config.get("image_tta_hflip", False))
            self.latency_breakdown_enabled = bool(config.get("latency_breakdown", False))
            temporal_smoothing = config.get("temporal_smoothing") or {}
            self.temporal_smoothing_enabled = bool(temporal_smoothing.get("enabled", False))
            self.temporal_smoothing_tau_sec = max(
                1e-3,
                finite_float(temporal_smoothing.get("tau_sec"), self.temporal_smoothing_tau_sec),
            )
            self.temporal_smoothing_switch_margin = max(
                0.0,
                finite_float(temporal_smoothing.get("switch_margin"), self.temporal_smoothing_switch_margin),
            )
            self.neutral_guard_config = dict(config.get("neutral_guard") or {})
            self.per_class_thresholds = {
                str(label): dict(value)
                for label, value in (config.get("per_class_thresholds") or {}).items()
                if isinstance(value, dict)
            }
            self.hard_negative_logging_config = dict(config.get("hard_negative_logging") or {})

            fusion = config.get("fusion") or {}
            self.fusion_mode = str(fusion.get("mode") or "classwise_logprob")
            self.alpha_by_class = {
                label: finite_float((fusion.get("alpha_by_class") or {}).get(label), 0.0)
                for label in self.labels
            }
            self.bias_by_class = {
                label: finite_float((fusion.get("bias_by_class") or {}).get(label), 0.0)
                for label in self.labels
            }
            gated_model = str(config.get("gated_fusion_model") or "")
            gated_metadata_path = str(config.get("gated_fusion_metadata") or "")
            if gated_model and gated_metadata_path:
                gated_metadata = self._load_json(gated_metadata_path)
                gate_input_names = gated_metadata.get("input_names") or {}
                gate_output_names = gated_metadata.get("output_names") or {}
                self.gate_input_names = {
                    "gate_features": str(gate_input_names.get("gate_features") or "gate_features"),
                    "image_log_probs": str(gate_input_names.get("image_log_probs") or "image_log_probs"),
                    "blendshape_log_probs": str(gate_input_names.get("blendshape_log_probs") or "blendshape_log_probs"),
                }
                self.gate_output_names = {
                    "logits": str(gate_output_names.get("logits") or "logits"),
                    "alpha": str(gate_output_names.get("alpha") or "alpha"),
                    "bias": str(gate_output_names.get("bias") or "bias"),
                }
                self.gate_feature_names = [str(name) for name in gated_metadata.get("feature_names", [])]
                self.gate_feature_mean = [
                    finite_float(value, 0.0)
                    for value in gated_metadata.get("feature_mean", [])
                ]
                self.gate_feature_std = [
                    max(1e-6, finite_float(value, 1.0))
                    for value in gated_metadata.get("feature_std", [])
                ]
            providers = ["CPUExecutionProvider"]
            options = ort.SessionOptions()
            options.log_severity_level = 3
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self.image_session = ort.InferenceSession(
                str(self._resolve(str(config["image_model"]))),
                sess_options=options,
                providers=providers,
            )
            self.blendshape_session = ort.InferenceSession(
                str(self._resolve(str(config["blendshape_model"]))),
                sess_options=options,
                providers=providers,
            )
            if self.fusion_mode == "samplewise_gated_logprob" and gated_model:
                self.gated_fusion_session = ort.InferenceSession(
                    str(self._resolve(gated_model)),
                    sess_options=options,
                    providers=providers,
                )
            self._np = np
            self._ort = ort
            self.enabled = True
            self.last_error = ""
        except Exception as exc:
            self.enabled = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            print(f"Emotion classifier disabled: {self.last_error}", file=sys.stderr)

    def _preprocess_image(
        self,
        frame_rgb: Any,
        face_box: Optional[dict[str, float]],
    ) -> Optional[Any]:
        if self._np is None:
            return None
        np = self._np
        height, width = frame_rgb.shape[:2]
        if width <= 0 or height <= 0:
            return None
        if face_box:
            x = max(0.0, min(1.0, finite_float(face_box.get("x"), 0.0)))
            y = max(0.0, min(1.0, finite_float(face_box.get("y"), 0.0)))
            w = max(0.0, min(1.0, finite_float(face_box.get("w"), 1.0)))
            h = max(0.0, min(1.0, finite_float(face_box.get("h"), 1.0)))
        else:
            x, y, w, h = 0.0, 0.0, 1.0, 1.0
        pad = max(w, h) * 0.18
        x1 = int(max(0.0, (x - pad)) * width)
        y1 = int(max(0.0, (y - pad)) * height)
        x2 = int(min(1.0, (x + w + pad)) * width)
        y2 = int(min(1.0, (y + h + pad)) * height)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame_rgb[y1:y2, x1:x2]
        if crop.size <= 0:
            return None
        import cv2  # type: ignore

        resized = cv2.resize(crop, (self.image_size, self.image_size), interpolation=cv2.INTER_LINEAR)
        array = resized.astype(np.float32) / 255.0
        array = (array - 0.5) / 0.5
        return np.transpose(array, (2, 0, 1))[np.newaxis, :, :, :].astype(np.float32, copy=False)

    def _preprocess_blendshapes(self, blendshapes: Sequence[dict[str, Any]]) -> Optional[Any]:
        if self._np is None or not self.feature_names:
            return None
        np = self._np
        scores = {
            str(item.get("name", "")): max(0.0, min(1.0, finite_float(item.get("score"), 0.0)))
            for item in blendshapes
            if isinstance(item, dict) and item.get("name")
        }
        values = [self._blendshape_feature_value(name, scores) for name in self.feature_names]
        normalized = [
            (value - self.feature_mean[index]) / self.feature_std[index]
            for index, value in enumerate(values)
        ]
        return np.asarray(normalized, dtype=np.float32)[np.newaxis, :]

    def _blendshape_mean_value(self, scores: dict[str, float], *names: str) -> float:
        if not names:
            return 0.0
        return sum(scores.get(name, 0.0) for name in names) / float(len(names))

    def _blendshape_abs_diff_value(self, scores: dict[str, float], left: str, right: str) -> float:
        return abs(scores.get(left, 0.0) - scores.get(right, 0.0))

    def _blendshape_feature_value(self, feature_name: str, scores: dict[str, float]) -> float:
        if feature_name == "brow_down_mean":
            return self._blendshape_mean_value(scores, "browDownLeft", "browDownRight")
        if feature_name == "brow_outer_up_mean":
            return self._blendshape_mean_value(scores, "browOuterUpLeft", "browOuterUpRight")
        if feature_name == "brow_inner_up":
            return scores.get("browInnerUp", 0.0)
        if feature_name == "eye_wide_mean":
            return self._blendshape_mean_value(scores, "eyeWideLeft", "eyeWideRight")
        if feature_name == "eye_squint_mean":
            return self._blendshape_mean_value(scores, "eyeSquintLeft", "eyeSquintRight")
        if feature_name == "eye_blink_mean":
            return self._blendshape_mean_value(scores, "eyeBlinkLeft", "eyeBlinkRight")
        if feature_name == "jaw_open":
            return scores.get("jawOpen", 0.0)
        if feature_name == "mouth_smile_mean":
            return self._blendshape_mean_value(scores, "mouthSmileLeft", "mouthSmileRight")
        if feature_name == "mouth_frown_mean":
            return self._blendshape_mean_value(scores, "mouthFrownLeft", "mouthFrownRight")
        if feature_name == "mouth_stretch_mean":
            return self._blendshape_mean_value(scores, "mouthStretchLeft", "mouthStretchRight")
        if feature_name == "mouth_press_mean":
            return self._blendshape_mean_value(scores, "mouthPressLeft", "mouthPressRight")
        if feature_name == "mouth_pucker":
            return scores.get("mouthPucker", 0.0)
        if feature_name == "mouth_funnel":
            return scores.get("mouthFunnel", 0.0)
        if feature_name == "mouth_upper_up_mean":
            return self._blendshape_mean_value(scores, "mouthUpperUpLeft", "mouthUpperUpRight")
        if feature_name == "mouth_lower_down_mean":
            return self._blendshape_mean_value(scores, "mouthLowerDownLeft", "mouthLowerDownRight")
        if feature_name == "mouth_shrug_mean":
            return self._blendshape_mean_value(scores, "mouthShrugLower", "mouthShrugUpper")
        if feature_name == "nose_sneer_mean":
            return self._blendshape_mean_value(scores, "noseSneerLeft", "noseSneerRight")
        if feature_name == "cheek_squint_mean":
            return self._blendshape_mean_value(scores, "cheekSquintLeft", "cheekSquintRight")
        if feature_name == "mouth_open_proxy":
            return max(
                scores.get("jawOpen", 0.0),
                self._blendshape_mean_value(scores, "mouthLowerDownLeft", "mouthLowerDownRight"),
                scores.get("mouthFunnel", 0.0),
            )
        if feature_name == "mouth_asymmetry":
            return max(
                self._blendshape_abs_diff_value(scores, "mouthSmileLeft", "mouthSmileRight"),
                self._blendshape_abs_diff_value(scores, "mouthFrownLeft", "mouthFrownRight"),
                self._blendshape_abs_diff_value(scores, "mouthStretchLeft", "mouthStretchRight"),
            )
        if feature_name == "brow_asymmetry":
            return max(
                self._blendshape_abs_diff_value(scores, "browDownLeft", "browDownRight"),
                self._blendshape_abs_diff_value(scores, "browOuterUpLeft", "browOuterUpRight"),
            )
        if feature_name == "eye_wide_asymmetry":
            return self._blendshape_abs_diff_value(scores, "eyeWideLeft", "eyeWideRight")
        if feature_name == "nose_sneer_asymmetry":
            return self._blendshape_abs_diff_value(scores, "noseSneerLeft", "noseSneerRight")
        if feature_name == "negative_evidence_proxy":
            return max(
                self._blendshape_mean_value(scores, "browDownLeft", "browDownRight"),
                self._blendshape_mean_value(scores, "mouthFrownLeft", "mouthFrownRight"),
                self._blendshape_mean_value(scores, "noseSneerLeft", "noseSneerRight"),
                self._blendshape_mean_value(scores, "mouthPressLeft", "mouthPressRight"),
            )
        if feature_name == "surprise_evidence_proxy":
            return max(
                self._blendshape_mean_value(scores, "eyeWideLeft", "eyeWideRight"),
                scores.get("jawOpen", 0.0),
                scores.get("mouthFunnel", 0.0),
                scores.get("mouthPucker", 0.0),
            )
        if feature_name == "happiness_evidence_proxy":
            return max(
                self._blendshape_mean_value(scores, "mouthSmileLeft", "mouthSmileRight"),
                self._blendshape_mean_value(scores, "cheekSquintLeft", "cheekSquintRight"),
            )
        if feature_name in scores:
            return scores.get(feature_name, 0.0)
        return 0.0

    def _run_logits(self, session: Any, input_name: str, output_name: str, tensor: Any) -> Optional[list[float]]:
        if session is None or tensor is None:
            return None
        logits = session.run([output_name], {input_name: tensor})[0][0]
        return [float(value) for value in logits]

    def _run_probs(self, session: Any, input_name: str, output_name: str, tensor: Any) -> Optional[dict[str, float]]:
        logits = self._run_logits(session, input_name, output_name, tensor)
        if logits is None:
            return None
        probs = softmax_vector([float(value) for value in logits])
        return {
            label: max(1e-8, min(1.0, finite_float(probs[index], 0.0)))
            for index, label in enumerate(self.labels)
            if index < len(probs)
        }

    def _run_image_probs(self, tensor: Any) -> Optional[dict[str, float]]:
        if self._np is None or tensor is None:
            return None
        logits = self._run_logits(self.image_session, self.image_input_name, self.image_output_name, tensor)
        if logits is None:
            return None
        if self.image_tta_hflip:
            flipped = self._np.flip(tensor, axis=3).copy()
            flipped_logits = self._run_logits(
                self.image_session,
                self.image_input_name,
                self.image_output_name,
                flipped,
            )
            if flipped_logits is not None and len(flipped_logits) == len(logits):
                logits = [(a + b) * 0.5 for a, b in zip(logits, flipped_logits)]
        probs = softmax_vector(logits)
        return {
            label: max(1e-8, min(1.0, finite_float(probs[index], 0.0)))
            for index, label in enumerate(self.labels)
            if index < len(probs)
        }

    def _prob_list(self, probs: dict[str, float]) -> list[float]:
        return [max(1e-8, min(1.0, finite_float(probs.get(label), 0.0))) for label in self.labels]

    def _prob_label(self, probs: dict[str, float]) -> str:
        return max(self.labels, key=lambda label: probs.get(label, 0.0))

    def _prob_entropy(self, probs: dict[str, float]) -> float:
        values = self._prob_list(probs)
        return -sum(value * math.log(max(value, 1e-8)) for value in values) / math.log(max(2, len(values)))

    def _prob_margin(self, probs: dict[str, float]) -> float:
        ordered = sorted(self._prob_list(probs), reverse=True)
        return ordered[0] - ordered[1] if len(ordered) >= 2 else 0.0

    def _normalized_probs(self, probs: dict[str, float]) -> dict[str, float]:
        clean = {
            label: max(1e-8, min(1.0, finite_float(probs.get(label), 0.0)))
            for label in self.labels
        }
        total = sum(clean.values())
        if total <= 0.0:
            uniform = 1.0 / max(1, len(self.labels))
            return {label: uniform for label in self.labels}
        return {label: value / total for label, value in clean.items()}

    def _top_prob_entries(self, probs: dict[str, float], count: int = 2) -> list[dict[str, float | str]]:
        clean = self._normalized_probs(probs)
        labels = sorted(self.labels, key=lambda label: clean.get(label, 0.0), reverse=True)
        return [
            {"label": label, "probability": clean.get(label, 0.0)}
            for label in labels[: max(1, int(count))]
        ]

    def _neutral_guard_target_label(self) -> str:
        label = str(self.neutral_guard_config.get("target_label") or "neutral")
        return label if label in self.labels else "neutral"

    def _negative_guard_labels(self) -> list[str]:
        configured = self.neutral_guard_config.get("negative_labels")
        if isinstance(configured, list):
            labels = [str(label) for label in configured if str(label) in self.labels]
            if labels:
                return labels
        return [label for label in ("sadness", "anger", "fear", "disgust") if label in self.labels]

    def _blendshape_delta_value(self, scores: dict[str, float], name: str) -> float:
        return max(0.0, min(1.0, finite_float(scores.get(name), 0.0)))

    def _blendshape_evidence_component(
        self,
        scores: dict[str, float],
        names: Sequence[str],
        reducer: str = "max",
    ) -> float:
        values = [self._blendshape_delta_value(scores, name) for name in names]
        if not values:
            return 0.0
        if reducer == "mean":
            return sum(values) / len(values)
        return max(values)

    def _negative_blendshape_evidence(self, scores: dict[str, float]) -> tuple[float, dict[str, float]]:
        components = {
            "noseSneer": self._blendshape_evidence_component(scores, ("noseSneerLeft", "noseSneerRight"), "mean"),
            "upperLipRaise": self._blendshape_evidence_component(
                scores,
                ("mouthUpperUpLeft", "mouthUpperUpRight", "upperLipRaiseLeft", "upperLipRaiseRight"),
            ),
            "mouthPress": self._blendshape_evidence_component(
                scores,
                ("mouthPressLeft", "mouthPressRight", "mouthShrugLower", "mouthShrugUpper"),
            ),
            "browTension": self._blendshape_evidence_component(scores, ("browDownLeft", "browDownRight"), "mean"),
            "mouthFrown": self._blendshape_evidence_component(scores, ("mouthFrownLeft", "mouthFrownRight"), "mean"),
            "mouthPucker": self._blendshape_evidence_component(scores, ("mouthPucker", "mouthFunnel")),
        }
        weighted = {
            "noseSneer": components["noseSneer"] * 1.00,
            "upperLipRaise": components["upperLipRaise"] * 0.90,
            "mouthPress": components["mouthPress"] * 0.85,
            "browTension": components["browTension"] * 0.75,
            "mouthFrown": components["mouthFrown"] * 0.65,
            "mouthPucker": components["mouthPucker"] * 0.45,
        }
        evidence = max(weighted.values()) if weighted else 0.0
        return max(0.0, min(1.0, evidence)), components

    def _negative_class_evidence(self, scores: dict[str, float]) -> dict[str, dict[str, Any]]:
        disgust_components = {
            "noseSneer": self._blendshape_evidence_component(scores, ("noseSneerLeft", "noseSneerRight"), "mean"),
            "upperLipRaise": self._blendshape_evidence_component(
                scores,
                ("mouthUpperUpLeft", "mouthUpperUpRight", "upperLipRaiseLeft", "upperLipRaiseRight"),
            ),
            "mouthPucker": self._blendshape_evidence_component(scores, ("mouthPucker", "mouthFunnel")),
            "mouthPress": self._blendshape_evidence_component(
                scores,
                ("mouthPressLeft", "mouthPressRight", "mouthShrugLower", "mouthShrugUpper"),
            ),
        }
        anger_components = {
            "browTension": self._blendshape_evidence_component(scores, ("browDownLeft", "browDownRight"), "mean"),
            "eyeSquint": self._blendshape_evidence_component(scores, ("eyeSquintLeft", "eyeSquintRight"), "mean"),
            "mouthPress": self._blendshape_evidence_component(
                scores,
                ("mouthPressLeft", "mouthPressRight", "mouthShrugLower", "mouthShrugUpper"),
            ),
        }
        sadness_components = {
            "mouthFrown": self._blendshape_evidence_component(scores, ("mouthFrownLeft", "mouthFrownRight"), "mean"),
            "browInnerUp": self._blendshape_evidence_component(scores, ("browInnerUp",)),
            "mouthPress": self._blendshape_evidence_component(
                scores,
                ("mouthPressLeft", "mouthPressRight", "mouthShrugLower", "mouthShrugUpper"),
            ),
        }
        evidence = {
            "disgust": max(
                disgust_components["noseSneer"] * 1.00,
                disgust_components["upperLipRaise"] * 0.95,
                disgust_components["mouthPucker"] * 0.35,
                disgust_components["mouthPress"] * 0.25,
            ),
            "anger": max(
                anger_components["browTension"] * 0.95,
                anger_components["eyeSquint"] * 0.70,
                anger_components["mouthPress"] * 0.55,
            ),
            "sadness": max(
                sadness_components["mouthFrown"] * 0.95,
                sadness_components["browInnerUp"] * 0.55,
                sadness_components["mouthPress"] * 0.30,
            ),
        }
        return {
            label: {
                "evidence": max(0.0, min(1.0, value)),
                "components": {
                    name: max(0.0, min(1.0, component))
                    for name, component in (
                        disgust_components
                        if label == "disgust"
                        else anger_components
                        if label == "anger"
                        else sadness_components
                    ).items()
                },
            }
            for label, value in evidence.items()
        }

    def _surprise_blendshape_evidence(self, scores: dict[str, float]) -> tuple[float, dict[str, float]]:
        components = {
            "eyeWide": self._blendshape_evidence_component(scores, ("eyeWideLeft", "eyeWideRight"), "mean"),
            "browRaise": self._blendshape_evidence_component(
                scores,
                ("browInnerUp", "browOuterUpLeft", "browOuterUpRight"),
            ),
            "jawOpen": self._blendshape_evidence_component(scores, ("jawOpen",)),
            "mouthFunnel": self._blendshape_evidence_component(scores, ("mouthFunnel", "mouthPucker")),
        }
        evidence = max(
            components["eyeWide"] * 1.00,
            components["browRaise"] * 0.95,
            components["jawOpen"] * 0.85,
            components["mouthFunnel"] * 0.35,
        )
        return max(0.0, min(1.0, evidence)), components

    def _force_guard_label(
        self,
        probs: dict[str, float],
        target_label: str,
        source_label: str,
        margin: float,
    ) -> dict[str, float]:
        clean = self._normalized_probs(probs)
        if target_label not in clean:
            return clean
        source_prob = clean.get(source_label, 0.0)
        top_prob = max(clean.values()) if clean else 0.0
        target_raw = max(clean.get(target_label, 0.0), source_prob + margin, top_prob + margin)
        adjusted = dict(clean)
        adjusted[target_label] = min(1.0, target_raw)
        return self._normalized_probs(adjusted)

    def _apply_neutral_guard(
        self,
        probs: dict[str, float],
        scores: dict[str, float],
    ) -> tuple[dict[str, float], dict[str, Any]]:
        clean = self._normalized_probs(probs)
        top_entries = self._top_prob_entries(clean, 2)
        top_label = str(top_entries[0]["label"])
        top_prob = finite_float(top_entries[0]["probability"], 0.0)
        second_prob = finite_float(top_entries[1]["probability"], 0.0) if len(top_entries) > 1 else 0.0
        top2_margin = max(0.0, top_prob - second_prob)
        neutral_label = self._neutral_guard_target_label()
        neutral_prob = finite_float(clean.get(neutral_label), 0.0)
        negative_labels = self._negative_guard_labels()
        negative_sum = sum(finite_float(clean.get(label), 0.0) for label in negative_labels)
        negative_evidence, evidence_components = self._negative_blendshape_evidence(scores)
        negative_class_evidence = self._negative_class_evidence(scores)
        surprise_evidence, surprise_evidence_components = self._surprise_blendshape_evidence(scores)
        diagnostics: dict[str, Any] = {
            "enabled": bool(self.neutral_guard_config.get("enabled", False)),
            "guardApplied": False,
            "guardReason": "",
            "guardTarget": "",
            "preGuardLabel": top_label,
            "preGuardTop2": top_entries,
            "preGuardTop2Margin": top2_margin,
            "neutralProbability": neutral_prob,
            "negativeProbabilitySum": negative_sum,
            "negativeBlendshapeEvidence": negative_evidence,
            "negativeBlendshapeEvidenceComponents": evidence_components,
            "negativeClassEvidence": negative_class_evidence,
            "surpriseBlendshapeEvidence": surprise_evidence,
            "surpriseBlendshapeEvidenceComponents": surprise_evidence_components,
            "guardCandidateLabel": self._guard_candidate_label or "",
            "guardCandidateCount": self._guard_candidate_count,
            "negativeClassCandidateLabel": self._negative_class_candidate_label or "",
            "negativeClassCandidateCount": self._negative_class_candidate_count,
        }
        if not bool(self.neutral_guard_config.get("enabled", False)):
            return clean, diagnostics

        boost_margin = max(0.0, finite_float(self.neutral_guard_config.get("neutral_boost_margin"), 0.03))
        reason = ""
        neutral_sticky = self.neutral_guard_config.get("neutral_sticky") or {}
        negative_class_guard = self.neutral_guard_config.get("negative_class_guard") or {}
        negative_source_label = str(negative_class_guard.get("source_label") or "disgust")
        if bool(negative_class_guard.get("enabled", False)) and top_label == negative_source_label:
            fallback_candidates = [
                str(label)
                for label in negative_class_guard.get("fallback_candidates", ["anger", "sadness"])
                if str(label) in self.labels and str(label) != top_label
            ]
            candidate_label = ""
            candidate_prob = 0.0
            for label in fallback_candidates:
                prob = finite_float(clean.get(label), 0.0)
                if prob > candidate_prob:
                    candidate_label = label
                    candidate_prob = prob
            second_label = str(top_entries[1]["label"]) if len(top_entries) > 1 else ""
            top2_candidate = second_label if second_label in fallback_candidates else candidate_label
            rival_label = top2_candidate or candidate_label
            rival_prob = finite_float(clean.get(rival_label), 0.0) if rival_label else 0.0
            source_evidence = finite_float(
                (negative_class_evidence.get(negative_source_label) or {}).get("evidence"),
                0.0,
            )
            rival_evidence = finite_float((negative_class_evidence.get(rival_label) or {}).get("evidence"), 0.0)
            min_specific_evidence = max(
                0.0,
                finite_float(negative_class_guard.get("disgust_min_specific_evidence"), 0.16),
            )
            min_prob_margin = max(
                0.0,
                finite_float(negative_class_guard.get("disgust_min_margin_over_negative_rival"), 0.16),
            )
            min_evidence_margin = finite_float(
                negative_class_guard.get("disgust_min_specific_evidence_margin"), 0.04
            )
            close_rival_margin = max(
                0.0,
                finite_float(negative_class_guard.get("negative_rival_close_margin"), 0.18),
            )
            required_frames = max(
                1,
                int(finite_float(negative_class_guard.get("disgust_required_consecutive_frames"), 2)),
            )
            bypass_confidence = max(
                0.0,
                finite_float(negative_class_guard.get("disgust_bypass_confidence"), 0.80),
            )
            bypass_specific_evidence = max(
                0.0,
                finite_float(negative_class_guard.get("disgust_bypass_specific_evidence"), 0.24),
            )
            bypass_margin = max(
                0.0,
                finite_float(negative_class_guard.get("disgust_bypass_margin"), 0.24),
            )
            rival_close = bool(rival_label) and (top_prob - rival_prob) <= close_rival_margin
            weak_reasons = []
            if source_evidence < min_specific_evidence:
                weak_reasons.append("weak_disgust_specific_evidence")
            if rival_label and source_evidence - rival_evidence < min_evidence_margin:
                weak_reasons.append("weak_disgust_evidence_margin")
            if rival_label and top_prob - rival_prob < min_prob_margin:
                weak_reasons.append("small_negative_rival_margin")
            if self._negative_class_candidate_label == top_label:
                self._negative_class_candidate_count += 1
            else:
                self._negative_class_candidate_label = top_label
                self._negative_class_candidate_count = 1
            strong_enough = (
                top_prob >= bypass_confidence
                and top_prob - rival_prob >= bypass_margin
                and source_evidence >= bypass_specific_evidence
            )
            diagnostics["negativeClassCandidateLabel"] = self._negative_class_candidate_label or ""
            diagnostics["negativeClassCandidateCount"] = self._negative_class_candidate_count
            diagnostics["negativeClassGuard"] = {
                "enabled": True,
                "sourceLabel": negative_source_label,
                "rivalLabel": rival_label,
                "rivalProbability": rival_prob,
                "rivalClose": rival_close,
                "disgustSpecificEvidence": source_evidence,
                "rivalSpecificEvidence": rival_evidence,
                "requiredConsecutiveFrames": required_frames,
                "strongEnoughBypass": strong_enough,
                "weakReasons": weak_reasons,
            }
            if rival_label and rival_close and weak_reasons:
                neutral_label = rival_label
                reason = f"{negative_source_label}_to_{rival_label}:" + ",".join(weak_reasons)
            elif rival_label and rival_close and not strong_enough and self._negative_class_candidate_count < required_frames:
                neutral_label = rival_label
                reason = (
                    f"{negative_source_label}_to_{rival_label}:negative_class_sticky_"
                    f"{self._negative_class_candidate_count}_of_{required_frames}"
                )

        surprise_guard = self.neutral_guard_config.get("surprise_guard") or {}
        if not reason and bool(surprise_guard.get("enabled", False)) and top_label == "surprise":
            margin_over_neutral = top_prob - neutral_prob
            min_confidence = max(
                0.0,
                finite_float(surprise_guard.get("surprise_min_confidence"), 0.58),
            )
            min_neutral_margin = max(
                0.0,
                finite_float(surprise_guard.get("surprise_min_margin_over_neutral"), 0.20),
            )
            min_top2_margin = max(
                0.0,
                finite_float(surprise_guard.get("surprise_min_top2_margin"), 0.12),
            )
            min_evidence = max(
                0.0,
                finite_float(surprise_guard.get("surprise_min_evidence"), 0.16),
            )
            neutral_min = max(
                0.0,
                finite_float(surprise_guard.get("neutral_min_probability"), 0.06),
            )
            bypass_confidence = max(
                0.0,
                finite_float(surprise_guard.get("surprise_bypass_confidence"), 0.82),
            )
            bypass_margin = max(
                0.0,
                finite_float(surprise_guard.get("surprise_bypass_margin_over_neutral"), 0.30),
            )
            bypass_evidence = max(
                0.0,
                finite_float(surprise_guard.get("surprise_bypass_evidence"), 0.26),
            )
            weak_reasons = []
            if top_prob < min_confidence:
                weak_reasons.append("low_confidence")
            if margin_over_neutral < min_neutral_margin:
                weak_reasons.append("small_neutral_margin")
            if top2_margin < min_top2_margin:
                weak_reasons.append("small_top2_margin")
            if surprise_evidence < min_evidence:
                weak_reasons.append("weak_surprise_evidence")
            strong_enough = (
                top_prob >= bypass_confidence
                and margin_over_neutral >= bypass_margin
                and surprise_evidence >= bypass_evidence
            )
            diagnostics["surpriseGuard"] = {
                "enabled": True,
                "marginOverNeutral": margin_over_neutral,
                "surpriseEvidence": surprise_evidence,
                "strongEnoughBypass": strong_enough,
                "weakReasons": weak_reasons,
            }
            if weak_reasons and not strong_enough and neutral_prob >= neutral_min:
                reason = "surprise_to_neutral:" + ",".join(weak_reasons)

        if not reason and top_label == "disgust":
            margin_over_neutral = top_prob - neutral_prob
            min_confidence = max(0.0, finite_float(self.neutral_guard_config.get("disgust_min_confidence"), 0.48))
            min_neutral_margin = max(
                0.0,
                finite_float(self.neutral_guard_config.get("disgust_min_margin_over_neutral"), 0.18),
            )
            min_top2_margin = max(
                0.0,
                finite_float(self.neutral_guard_config.get("disgust_min_top2_margin"), 0.10),
            )
            min_evidence = max(
                0.0,
                finite_float(self.neutral_guard_config.get("negative_evidence_min"), 0.08),
            )
            negative_sum_max = max(
                0.0,
                finite_float(self.neutral_guard_config.get("negative_sum_max_when_low_evidence"), 0.75),
            )
            neutral_min = max(0.0, finite_float(self.neutral_guard_config.get("neutral_min_probability"), 0.08))
            weak_reasons = []
            if top_prob < min_confidence:
                weak_reasons.append("low_confidence")
            if margin_over_neutral < min_neutral_margin:
                weak_reasons.append("small_neutral_margin")
            if top2_margin < min_top2_margin:
                weak_reasons.append("small_top2_margin")
            if negative_evidence < min_evidence:
                weak_reasons.append("weak_blendshape_evidence")
            if weak_reasons and (
                neutral_prob >= neutral_min
                or negative_sum <= negative_sum_max
                or negative_evidence < min_evidence
            ):
                reason = "disgust_to_neutral:" + ",".join(weak_reasons)

        if not reason and top_label in negative_labels and top_label != neutral_label:
            min_evidence = max(
                0.0,
                finite_float(self.neutral_guard_config.get("negative_evidence_min"), 0.08),
            )
            low_evidence_max_confidence = max(
                0.0,
                finite_float(self.neutral_guard_config.get("negative_low_evidence_max_confidence"), 0.45),
            )
            neutral_min = max(0.0, finite_float(self.neutral_guard_config.get("neutral_min_probability"), 0.08))
            if negative_evidence < min_evidence and top_prob < low_evidence_max_confidence and neutral_prob >= neutral_min:
                reason = f"{top_label}_to_neutral:weak_blendshape_evidence"

        if (
            not reason
            and bool(neutral_sticky.get("enabled", False))
            and top_label in [str(label) for label in neutral_sticky.get("labels", negative_labels)]
            and top_label != neutral_label
            and (
                self._smoothing_label in {None, neutral_label}
                or (self._smoothed_probs or {}).get(neutral_label, 0.0)
                >= max(0.0, finite_float(neutral_sticky.get("neutral_state_min_probability"), 0.30))
            )
        ):
            if self._guard_candidate_label == top_label:
                self._guard_candidate_count += 1
            else:
                self._guard_candidate_label = top_label
                self._guard_candidate_count = 1

            required_frames = max(1, int(finite_float(neutral_sticky.get("required_consecutive_frames"), 3)))
            bypass_confidence = max(0.0, finite_float(neutral_sticky.get("bypass_confidence"), 0.80))
            bypass_margin = max(0.0, finite_float(neutral_sticky.get("bypass_margin_over_neutral"), 0.32))
            bypass_evidence = max(0.0, finite_float(neutral_sticky.get("bypass_negative_evidence"), 0.22))
            strong_enough = (
                top_prob >= bypass_confidence
                and top_prob - neutral_prob >= bypass_margin
                and negative_evidence >= bypass_evidence
            )
            diagnostics["guardCandidateLabel"] = self._guard_candidate_label or ""
            diagnostics["guardCandidateCount"] = self._guard_candidate_count
            diagnostics["neutralSticky"] = {
                "enabled": True,
                "requiredConsecutiveFrames": required_frames,
                "strongEnoughBypass": strong_enough,
            }
            if not strong_enough and self._guard_candidate_count < required_frames:
                reason = f"{top_label}_to_neutral:neutral_sticky_{self._guard_candidate_count}_of_{required_frames}"

        if not reason and top_label in self.per_class_thresholds:
            threshold = self.per_class_thresholds.get(top_label) or {}
            fallback_label = str(threshold.get("fallback") or neutral_label)
            if fallback_label in self.labels and fallback_label != top_label:
                min_confidence = max(0.0, finite_float(threshold.get("min_confidence"), 0.0))
                min_margin = max(0.0, finite_float(threshold.get("min_margin"), 0.0))
                min_margin_over_fallback = max(
                    0.0,
                    finite_float(threshold.get("min_margin_over_fallback"), min_margin),
                )
                fallback_prob = finite_float(clean.get(fallback_label), 0.0)
                failed = []
                if top_prob < min_confidence:
                    failed.append("class_low_confidence")
                if top2_margin < min_margin:
                    failed.append("class_small_top2_margin")
                if top_prob - fallback_prob < min_margin_over_fallback:
                    failed.append("class_small_fallback_margin")
                if failed:
                    neutral_label = fallback_label
                    reason = f"{top_label}_to_{fallback_label}:" + ",".join(failed)

        if reason:
            adjusted = self._force_guard_label(clean, neutral_label, top_label, boost_margin)
            if top_label == neutral_label:
                self._guard_candidate_label = None
                self._guard_candidate_count = 0
                self._negative_class_candidate_label = None
                self._negative_class_candidate_count = 0
            diagnostics["guardApplied"] = True
            diagnostics["guardReason"] = reason
            diagnostics["guardTarget"] = neutral_label
            diagnostics["postGuardTop2"] = self._top_prob_entries(adjusted, 2)
            return adjusted, diagnostics

        if top_label == neutral_label:
            self._guard_candidate_label = None
            self._guard_candidate_count = 0
        if top_label != "disgust":
            self._negative_class_candidate_label = None
            self._negative_class_candidate_count = 0
        diagnostics["postGuardTop2"] = top_entries
        return clean, diagnostics

    def _maybe_log_hard_negative(
        self,
        pre_guard_probs: dict[str, float],
        final_probs: dict[str, float],
        diagnostics: dict[str, Any],
        scores: dict[str, float],
        image_probs: Optional[dict[str, float]],
        blendshape_probs: Optional[dict[str, float]],
    ) -> None:
        config = self.hard_negative_logging_config
        if not bool(config.get("enabled", False)):
            return

        pre_label = str(diagnostics.get("preGuardLabel") or self._prob_label(pre_guard_probs))
        final_label = self._prob_label(final_probs)
        negative_labels = set(self._negative_guard_labels())
        guard_applied = bool(diagnostics.get("guardApplied", False))
        should_log = guard_applied or pre_label in negative_labels or final_label in negative_labels
        if not should_log:
            return

        now = time.time()
        min_interval = max(0.0, finite_float(config.get("min_interval_sec"), 0.25))
        if now - self._last_hard_negative_log_at < min_interval:
            return
        self._last_hard_negative_log_at = now

        path_value = str(config.get("path") or "logs/neutral_hard_negatives.jsonl")
        output_path = self._resolve(path_value)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if bool(config.get("log_full_blendshapes", False)):
            logged_scores = dict(scores)
        else:
            keys = (
                "noseSneerLeft",
                "noseSneerRight",
                "mouthPressLeft",
                "mouthPressRight",
                "mouthShrugLower",
                "mouthShrugUpper",
                "mouthPucker",
                "mouthFunnel",
                "mouthFrownLeft",
                "mouthFrownRight",
                "browDownLeft",
                "browDownRight",
                "jawOpen",
            )
            logged_scores = {key: scores.get(key, 0.0) for key in keys}
        record = {
            "timestamp": now,
            "assumedLabel": str(config.get("assumed_label") or "neutral"),
            "preGuardLabel": pre_label,
            "finalLabel": final_label,
            "preGuardProbabilities": self._normalized_probs(pre_guard_probs),
            "finalProbabilities": self._normalized_probs(final_probs),
            "imageProbabilities": self._normalized_probs(image_probs or {}) if image_probs else {},
            "blendshapeProbabilities": self._normalized_probs(blendshape_probs or {}) if blendshape_probs else {},
            "diagnostics": diagnostics,
            "blendshapeScores": logged_scores,
        }
        with output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _blendshape_scores(self, blendshapes: Sequence[dict[str, Any]]) -> dict[str, float]:
        return {
            str(item.get("name", "")): max(0.0, min(1.0, finite_float(item.get("score"), 0.0)))
            for item in blendshapes
            if isinstance(item, dict) and item.get("name")
        }

    def _blendshape_group_values(self, group: str, scores: dict[str, float]) -> list[float]:
        if group == "brow":
            names = [name for name in self.feature_names if name.startswith("brow")]
        elif group == "eye":
            names = [name for name in self.feature_names if name.startswith("eye")]
        elif group == "mouth":
            names = [name for name in self.feature_names if name.startswith("mouth")]
        elif group == "jaw":
            names = [name for name in self.feature_names if name.startswith("jaw")]
        elif group == "cheek_nose":
            names = [name for name in self.feature_names if name.startswith("cheek") or name.startswith("nose")]
        else:
            names = []
        return [scores.get(name, 0.0) for name in names]

    def _group_stat_value(self, feature_name: str, scores: dict[str, float]) -> float:
        for suffix in ("_mean", "_max", "_sum", "_std"):
            if feature_name.endswith(suffix):
                group = feature_name[: -len(suffix)]
                values = self._blendshape_group_values(group, scores)
                if not values:
                    return 0.0
                if suffix == "_mean":
                    return sum(values) / len(values)
                if suffix == "_max":
                    return max(values)
                if suffix == "_sum":
                    return sum(values)
                mean = sum(values) / len(values)
                return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        return 0.0

    def _gate_feature_value(
        self,
        feature_name: str,
        image_probs: dict[str, float],
        blendshape_probs: dict[str, float],
        scores: dict[str, float],
        heuristic_label: str,
        heuristic_confidence: float,
        face_quality: float,
    ) -> float:
        if feature_name.startswith("image_prob_"):
            return finite_float(image_probs.get(feature_name.removeprefix("image_prob_")), 0.0)
        if feature_name.startswith("blendshape_prob_"):
            return finite_float(blendshape_probs.get(feature_name.removeprefix("blendshape_prob_")), 0.0)
        if feature_name.startswith("prob_delta_"):
            label = feature_name.removeprefix("prob_delta_")
            return finite_float(image_probs.get(label), 0.0) - finite_float(blendshape_probs.get(label), 0.0)
        if feature_name == "image_confidence":
            return max(self._prob_list(image_probs))
        if feature_name == "blendshape_confidence":
            return max(self._prob_list(blendshape_probs))
        if feature_name == "image_margin":
            return self._prob_margin(image_probs)
        if feature_name == "blendshape_margin":
            return self._prob_margin(blendshape_probs)
        if feature_name == "image_entropy":
            return self._prob_entropy(image_probs)
        if feature_name == "blendshape_entropy":
            return self._prob_entropy(blendshape_probs)
        if feature_name == "image_blendshape_agreement":
            return 1.0 if self._prob_label(image_probs) == self._prob_label(blendshape_probs) else 0.0
        if feature_name == "face_quality":
            return face_quality
        if feature_name == "heuristic_confidence":
            return heuristic_confidence
        if feature_name == "heuristic_image_agreement":
            return 1.0 if heuristic_label == self._prob_label(image_probs) else 0.0
        if feature_name == "heuristic_blendshape_agreement":
            return 1.0 if heuristic_label == self._prob_label(blendshape_probs) else 0.0
        if feature_name.startswith("raw_blendshape_"):
            return scores.get(feature_name.removeprefix("raw_blendshape_"), 0.0)
        return self._group_stat_value(feature_name, scores)

    def _gate_features(
        self,
        image_probs: dict[str, float],
        blendshape_probs: dict[str, float],
        blendshapes: Sequence[dict[str, Any]],
    ) -> Optional[Any]:
        if (
            self._np is None
            or not self.gate_feature_names
            or len(self.gate_feature_names) != len(self.gate_feature_mean)
            or len(self.gate_feature_names) != len(self.gate_feature_std)
        ):
            return None
        scores = self._blendshape_scores(blendshapes)
        heuristic = classify_apparent_affect(blendshapes)
        ekman = heuristic.get("apparentEkman") or {}
        heuristic_label = str(ekman.get("label") or "")
        heuristic_confidence = finite_float(ekman.get("confidence"), 0.0)
        face_quality = finite_float(heuristic.get("confidence"), 0.0)
        values = [
            self._gate_feature_value(
                name,
                image_probs,
                blendshape_probs,
                scores,
                heuristic_label,
                heuristic_confidence,
                face_quality,
            )
            for name in self.gate_feature_names
        ]
        normalized = [
            (value - self.gate_feature_mean[index]) / self.gate_feature_std[index]
            for index, value in enumerate(values)
        ]
        return self._np.asarray(normalized, dtype=self._np.float32)[self._np.newaxis, :]

    def _gated_fusion_logits(
        self,
        image_probs: dict[str, float],
        blendshape_probs: dict[str, float],
        blendshapes: Sequence[dict[str, Any]],
    ) -> Optional[list[float]]:
        if self._np is None or self.gated_fusion_session is None:
            return None
        features = self._gate_features(image_probs, blendshape_probs, blendshapes)
        if features is None:
            return None
        image_log_probs = self._np.asarray(
            [[math.log(max(1e-8, image_probs.get(label, 1e-8))) for label in self.labels]],
            dtype=self._np.float32,
        )
        blendshape_log_probs = self._np.asarray(
            [[math.log(max(1e-8, blendshape_probs.get(label, 1e-8))) for label in self.labels]],
            dtype=self._np.float32,
        )
        outputs = self.gated_fusion_session.run(
            [self.gate_output_names["logits"]],
            {
                self.gate_input_names["gate_features"]: features,
                self.gate_input_names["image_log_probs"]: image_log_probs,
                self.gate_input_names["blendshape_log_probs"]: blendshape_log_probs,
            },
        )
        return [float(value) for value in outputs[0][0]]

    def _apply_temporal_smoothing(self, probs: dict[str, float]) -> tuple[dict[str, float], str]:
        if not self.temporal_smoothing_enabled:
            label = max(self.labels, key=lambda name: probs.get(name, 0.0))
            return dict(probs), label

        now = time.perf_counter()
        clean_probs = {
            label: max(1e-8, min(1.0, finite_float(probs.get(label), 0.0)))
            for label in self.labels
        }
        total = sum(clean_probs.values())
        if total > 0:
            clean_probs = {label: value / total for label, value in clean_probs.items()}

        if self._smoothed_probs is None or self._smoothing_timestamp is None:
            smoothed = dict(clean_probs)
        else:
            dt = max(0.0, now - self._smoothing_timestamp)
            alpha = 1.0 - math.exp(-dt / max(1e-3, self.temporal_smoothing_tau_sec))
            smoothed = {
                label: ((1.0 - alpha) * self._smoothed_probs.get(label, 0.0)) + (alpha * clean_probs.get(label, 0.0))
                for label in self.labels
            }
            smoothed_total = sum(smoothed.values())
            if smoothed_total > 0:
                smoothed = {label: value / smoothed_total for label, value in smoothed.items()}

        candidate = max(self.labels, key=lambda name: smoothed.get(name, 0.0))
        if (
            self._smoothing_label
            and candidate != self._smoothing_label
            and smoothed.get(candidate, 0.0)
            < smoothed.get(self._smoothing_label, 0.0) + self.temporal_smoothing_switch_margin
        ):
            label = self._smoothing_label
        else:
            label = candidate

        self._smoothed_probs = dict(smoothed)
        self._smoothing_timestamp = now
        self._smoothing_label = label
        return smoothed, label

    def predict(
        self,
        frame_rgb: Any,
        face_box: Optional[dict[str, float]],
        blendshapes: Sequence[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        started_at = time.perf_counter()
        step_started = started_at
        image_tensor = self._preprocess_image(frame_rgb, face_box)
        after_image_preprocess = time.perf_counter()
        image_probs = self._run_image_probs(image_tensor)
        after_image_infer = time.perf_counter()
        blendshape_tensor = self._preprocess_blendshapes(blendshapes)
        after_blendshape_preprocess = time.perf_counter()
        blendshape_probs = self._run_probs(
            self.blendshape_session,
            self.blendshape_input_name,
            self.blendshape_output_name,
            blendshape_tensor,
        )
        after_blendshape_infer = time.perf_counter()
        if not image_probs and not blendshape_probs:
            return None
        scores = self._blendshape_scores(blendshapes)

        if image_probs and blendshape_probs:
            gated_logits = (
                self._gated_fusion_logits(image_probs, blendshape_probs, blendshapes)
                if self.fusion_mode == "samplewise_gated_logprob"
                else None
            )
            if gated_logits is not None:
                logits = {label: gated_logits[index] for index, label in enumerate(self.labels)}
                mode = "image_plus_blendshape_gated"
            else:
                logits = {}
                for label in self.labels:
                    logits[label] = (
                        math.log(max(1e-8, image_probs.get(label, 1e-8)))
                        + self.alpha_by_class.get(label, 0.0)
                        * math.log(max(1e-8, blendshape_probs.get(label, 1e-8)))
                        + self.bias_by_class.get(label, 0.0)
                    )
                mode = "image_plus_blendshape"
        elif image_probs:
            logits = {label: math.log(max(1e-8, image_probs.get(label, 1e-8))) for label in self.labels}
            mode = "image_only"
        else:
            logits = {label: math.log(max(1e-8, blendshape_probs.get(label, 1e-8))) for label in self.labels}
            mode = "blendshape_only"

        probs_list = softmax_vector([logits[label] for label in self.labels])
        probs = {label: probs_list[index] for index, label in enumerate(self.labels)}
        after_fusion = time.perf_counter()
        guarded_probs, diagnostics = self._apply_neutral_guard(probs, scores)
        after_neutral_guard = time.perf_counter()
        if (
            bool(diagnostics.get("guardApplied", False))
            and str(diagnostics.get("guardTarget") or "") == self._neutral_guard_target_label()
            and self.temporal_smoothing_enabled
        ):
            self._smoothed_probs = dict(guarded_probs)
            self._smoothing_timestamp = time.perf_counter()
            self._smoothing_label = self._neutral_guard_target_label()
        output_probs, label = self._apply_temporal_smoothing(guarded_probs)
        after_smoothing = time.perf_counter()
        diagnostics["finalLabel"] = label
        diagnostics["finalTop2"] = self._top_prob_entries(output_probs, 2)
        self._maybe_log_hard_negative(
            probs,
            output_probs,
            diagnostics,
            scores,
            image_probs,
            blendshape_probs,
        )
        after_hard_negative_log = time.perf_counter()
        self.last_latency_ms = (after_hard_negative_log - started_at) * 1000.0
        self.last_latency_breakdown_ms = {
            "imagePreprocess": (after_image_preprocess - step_started) * 1000.0,
            "imageInference": (after_image_infer - after_image_preprocess) * 1000.0,
            "blendshapePreprocess": (after_blendshape_preprocess - after_image_infer) * 1000.0,
            "blendshapeInference": (after_blendshape_infer - after_blendshape_preprocess) * 1000.0,
            "fusion": (after_fusion - after_blendshape_infer) * 1000.0,
            "neutralGuard": (after_neutral_guard - after_fusion) * 1000.0,
            "temporalSmoothing": (after_smoothing - after_neutral_guard) * 1000.0,
            "hardNegativeLogging": (after_hard_negative_log - after_smoothing) * 1000.0,
            "total": self.last_latency_ms,
        }
        return {
            "provider": self.provider,
            "label": label,
            "confidence": output_probs.get(label, 0.0),
            "probabilities": output_probs,
            "rawProbabilities": probs,
            "guardedProbabilities": guarded_probs,
            "diagnostics": diagnostics,
            "mode": mode,
            "latencyMs": self.last_latency_ms,
            "latencyBreakdownMs": dict(self.last_latency_breakdown_ms) if self.latency_breakdown_enabled else {},
            "temporalSmoothing": {
                "enabled": self.temporal_smoothing_enabled,
                "tauSec": self.temporal_smoothing_tau_sec,
                "switchMargin": self.temporal_smoothing_switch_margin,
            },
        }

def apply_emotion_classifier_result(
    apparent_affect: dict[str, Any],
    prediction: Optional[dict[str, Any]],
) -> dict[str, Any]:
    if not prediction:
        return apparent_affect
    probs = {
        label: max(0.0, min(1.0, finite_float((prediction.get("probabilities") or {}).get(label), 0.0)))
        for label in EMOTION_CLASSIFIER_LABELS
    }
    label = str(prediction.get("label") or "neutral")
    confidence = max(0.0, min(1.0, finite_float(prediction.get("confidence"), 0.0)))
    affect_values = emotion_probs_to_affect_values(probs)
    apparent_affect = dict(apparent_affect)
    apparent_affect.update(
        {
            "provider": str(prediction.get("provider") or EMOTION_CLASSIFIER_PROVIDER_FALLBACK),
            "label": emotion_label_to_apparent_affect_label(label),
            "confidence": confidence,
            "valence": affect_values["valence"],
            "arousal": affect_values["arousal"],
            "positive": affect_values["positive"],
            "negative": affect_values["negative"],
            "surprise": affect_values["surprise"],
            "uncertainty": affect_values["uncertainty"],
            "classifierLabel": label,
            "classifierMode": str(prediction.get("mode") or ""),
            "classifierLatencyMs": finite_float(prediction.get("latencyMs"), 0.0),
            "classifierLatencyBreakdownMs": prediction.get("latencyBreakdownMs") or {},
            "classifierRawProbabilities": prediction.get("rawProbabilities") or probs,
            "classifierGuardedProbabilities": prediction.get("guardedProbabilities") or probs,
            "classifierDiagnostics": prediction.get("diagnostics") or {},
            "classifierTemporalSmoothing": prediction.get("temporalSmoothing") or {},
            "apparentEkman": {
                "provider": str(prediction.get("provider") or EMOTION_CLASSIFIER_PROVIDER_FALLBACK),
                "label": label,
                "confidence": confidence,
                "neutral": probs["neutral"],
                "happiness": probs["happiness"],
                "sadness": probs["sadness"],
                "anger": probs["anger"],
                "fear": probs["fear"],
                "surprise": probs["surprise"],
                "disgust": probs["disgust"],
                "note": "ML classifier output from RAF-DB-trained image+blendshape fusion; apparent facial signal only",
            },
            "note": "ML classifier output from camera face crop and MediaPipe blendshapes; apparent facial signal only",
        }
    )
    return apparent_affect

def classify_apparent_affect(
    blendshapes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    scores = {
        str(item.get("name", "")): max(0.0, min(1.0, finite_float(item.get("score"), 0.0)))
        for item in blendshapes
        if isinstance(item, dict) and item.get("name")
    }

    smile = blendshape_average(scores, "mouthSmileLeft", "mouthSmileRight")
    frown = blendshape_average(scores, "mouthFrownLeft", "mouthFrownRight")
    brow_raise = blendshape_score(scores, "browInnerUp", "browOuterUpLeft", "browOuterUpRight")
    brow_tension = blendshape_score(scores, "browDownLeft", "browDownRight")
    eye_closure = blendshape_average(scores, "eyeBlinkLeft", "eyeBlinkRight")
    eye_squint = blendshape_average(scores, "eyeSquintLeft", "eyeSquintRight")
    mouth_open = blendshape_score(scores, "jawOpen", "mouthFunnel")
    mouth_press = blendshape_score(scores, "mouthPressLeft", "mouthPressRight", "mouthShrugLower", "mouthShrugUpper")
    mouth_pucker = blendshape_score(scores, "mouthPucker", "mouthFunnel")
    nose_sneer = blendshape_average(scores, "noseSneerLeft", "noseSneerRight")
    eye_wide = blendshape_average(scores, "eyeWideLeft", "eyeWideRight")
    mouth_stretch = blendshape_average(scores, "mouthStretchLeft", "mouthStretchRight")

    positive = max(0.0, min(1.0, (smile * 0.92) + (eye_squint * 0.16) - (frown * 0.22)))
    negative = max(
        0.0,
        min(
            1.0,
            (frown * 0.42)
            + (brow_tension * 0.28)
            + (mouth_press * 0.20)
            + (nose_sneer * 0.18)
            - (smile * 0.18),
        ),
    )
    surprise = max(
        0.0,
        min(1.0, (brow_raise * 0.46) + (mouth_open * 0.46) - (eye_closure * 0.22)),
    )
    uncertainty = max(
        0.0,
        min(1.0, (mouth_pucker * 0.34) + (mouth_press * 0.34) + (brow_tension * 0.22)),
    )
    valence = max(-1.0, min(1.0, positive - negative))
    arousal = max(
        0.0,
        min(
            1.0,
            (surprise * 0.36)
            + (mouth_open * 0.22)
            + (brow_raise * 0.18)
            + (brow_tension * 0.16)
            + (eye_squint * 0.08),
        ),
    )
    evidence = max(positive, negative, surprise, uncertainty, mouth_open, brow_raise, eye_closure, eye_squint)
    confidence = max(0.05, min(1.0, 0.20 + (evidence * 0.80)))
    label = apparent_affect_label(valence, arousal, positive, negative, surprise, uncertainty)
    ekman_scores = {
        "happiness": max(0.0, min(1.0, (smile * 0.86) + (eye_squint * 0.14) - (frown * 0.20))),
        "sadness": max(
            0.0,
            min(1.0, (frown * 0.34) + (brow_raise * 0.16) + (mouth_press * 0.18) - (smile * 0.16)),
        ),
        "anger": max(
            0.0,
            min(1.0, (brow_tension * 0.46) + (eye_squint * 0.22) + (mouth_press * 0.18) - (brow_raise * 0.10)),
        ),
        "fear": max(
            0.0,
            min(
                1.0,
                (brow_raise * 0.28)
                + (eye_wide * 0.22)
                + (mouth_open * 0.22)
                + (mouth_stretch * 0.16)
                + (brow_tension * 0.10)
                - (smile * 0.12),
            ),
        ),
        "surprise": surprise,
        "disgust": max(
            0.0,
            min(1.0, (nose_sneer * 0.44) + (mouth_press * 0.20) + (mouth_pucker * 0.16) + (brow_tension * 0.14)),
        ),
    }
    ekman_confidence = max(0.05, min(1.0, 0.18 + (max(ekman_scores.values()) * 0.82)))
    ekman_label = apparent_ekman_label(ekman_scores)
    cue_scores = {
        "smile": smile,
        "frown": frown,
        "browRaise": brow_raise,
        "browTension": brow_tension,
        "eyeClosure": eye_closure,
        "eyeSquint": eye_squint,
        "mouthOpen": mouth_open,
        "mouthPress": mouth_press,
        "mouthPucker": mouth_pucker,
        "noseSneer": nose_sneer,
    }

    return {
        "provider": APPARENT_AFFECT_PROVIDER,
        "label": label,
        "confidence": confidence,
        "valence": valence,
        "arousal": arousal,
        "positive": positive,
        "negative": negative,
        "surprise": surprise,
        "uncertainty": uncertainty,
        "smile": smile,
        "browRaise": brow_raise,
        "browTension": brow_tension,
        "eyeClosure": eye_closure,
        "mouthOpen": mouth_open,
        "cues": [
            {"name": name, "score": cue_scores[name]}
            for name in APPARENT_AFFECT_CUE_NAMES
        ],
        "apparentEkman": {
            "provider": APPARENT_EKMAN_PROVIDER,
            "label": ekman_label,
            "confidence": ekman_confidence,
            "happiness": ekman_scores["happiness"],
            "sadness": ekman_scores["sadness"],
            "anger": ekman_scores["anger"],
            "fear": ekman_scores["fear"],
            "surprise": ekman_scores["surprise"],
            "disgust": ekman_scores["disgust"],
            "note": "apparent Ekman-style facial pattern cues only; not a ground-truth emotion label",
        },
        "note": "apparent facial signal only; not a ground-truth emotion label",
    }

def build_face_candidate_payload(
    result: Any,
    face_index: int,
    frame_rgb: Any = None,
    emotion_classifier: Optional[EmotionClassifierRuntime] = None,
) -> Optional[dict[str, Any]]:
    if not getattr(result, "face_landmarks", None):
        return None

    if face_index < 0 or face_index >= len(result.face_landmarks):
        return None

    landmarks = result.face_landmarks[face_index]
    left_eye = average_landmarks(landmarks, LEFT_EYE_INDICES)
    right_eye = average_landmarks(landmarks, RIGHT_EYE_INDICES)
    nose_tip = landmark_point(landmarks, NOSE_TIP_INDEX)

    if left_eye is not None and right_eye is not None:
        face_center = Point3(
            (left_eye.x + right_eye.x) * 0.5,
            ((left_eye.y + right_eye.y) * 0.5 + (nose_tip.y if nose_tip else (left_eye.y + right_eye.y) * 0.5))
            * 0.5,
            ((left_eye.z + right_eye.z) * 0.5 + (nose_tip.z if nose_tip else 0.0)) * 0.5,
        )
    else:
        face_center = nose_tip or Point3(0.5, 0.5, 0.0)

    matrices = getattr(result, "facial_transformation_matrixes", None) or []
    head_euler = (
        matrix_to_euler_degrees(matrices[face_index])
        if face_index < len(matrices)
        else Point3(0.0, 0.0, 0.0)
    )
    interocular_width = 0.0
    if left_eye is not None and right_eye is not None:
        interocular_width = math.sqrt(
            (left_eye.x - right_eye.x) ** 2 + (left_eye.y - right_eye.y) ** 2
        )

    face_box = landmark_bbox01(landmarks)
    blendshapes = extract_blendshapes(getattr(result, "face_blendshapes", None), face_index)
    apparent_affect = classify_apparent_affect(blendshapes)
    if emotion_classifier is not None and frame_rgb is not None:
        apparent_affect = apply_emotion_classifier_result(
            apparent_affect,
            emotion_classifier.predict(frame_rgb, face_box, blendshapes),
        )

    return {
        "candidateId": int(face_index),
        "confidence": 1.0,
        "faceCenter": face_center.as_payload(),
        "leftEye": left_eye.as_payload() if left_eye else None,
        "rightEye": right_eye.as_payload() if right_eye else None,
        "faceWidth": face_width_01(landmarks),
        "interocularWidth": interocular_width,
        "headEulerDeg": head_euler.as_payload(),
        "blendshapes": blendshapes,
        "apparentAffect": apparent_affect,
        "faceLandmarkCount": len(landmarks),
        "faceBox": face_box,
        "overlayLandmarks": extract_face_overlay_landmarks(landmarks),
    }

def landmark_bbox01(landmarks: Sequence[Any]) -> Optional[dict[str, float]]:
    if not landmarks:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for landmark in landmarks:
        xs.append(max(0.0, min(1.0, finite_float(getattr(landmark, "x", 0.0)))))
        ys.append(max(0.0, min(1.0, finite_float(getattr(landmark, "y", 0.0)))))
    if not xs or not ys:
        return None
    return {
        "x": min(xs),
        "y": min(ys),
        "w": max(0.0, max(xs) - min(xs)),
        "h": max(0.0, max(ys) - min(ys)),
    }

def extract_face_overlay_landmarks(landmarks: Sequence[Any]) -> list[dict[str, float | int]]:
    payload: list[dict[str, float | int]] = []
    for index, landmark in enumerate(landmarks):
        payload.append(
            {
                "index": int(index),
                "x": max(0.0, min(1.0, finite_float(getattr(landmark, "x", 0.0)))),
                "y": max(0.0, min(1.0, finite_float(getattr(landmark, "y", 0.0)))),
                "z": finite_float(getattr(landmark, "z", 0.0)),
            }
        )
    return payload
