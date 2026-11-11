from types import SimpleNamespace

import numpy as np
import pytest

from app.listening_motion import LISTENING_NODS, idle_variant_policy, registered_head_mask
from app.main import DittoLiveRuntime, IDLE_FPS, build_idle_ctrl_info, idle_frame_count


@pytest.mark.parametrize("variant,peaks", [(3, {14: 4.0}), (5, {14: 4.0, 31: 1.8})])
def test_strokes_keep_source_pose_before_between_and_after(variant, peaks):
    controls = build_idle_ctrl_info(variant, 60, frame_offset=13)
    pitch = np.array([controls[13+i]["delta_pitch"] for i in range(60)])
    maxima = np.flatnonzero((pitch[1:-1] > pitch[:-2]) & (pitch[1:-1] > pitch[2:])) + 1
    assert list(maxima) == list(peaks)
    np.testing.assert_allclose(pitch[maxima], list(peaks.values()))
    assert np.all(pitch[:9] == 0) and np.all(pitch[22:26] == 0) and np.all(pitch[39:] == 0)
    assert all(c["delta_roll"] == c["delta_yaw"] == 0 and not c["delta_exp"].any() for c in controls.values())
    policy = idle_variant_policy(variant, idle_frame_count(variant), IDLE_FPS)
    assert policy["cycles"] == len(peaks) and policy["frames"] == 60
    assert [s["start_ms"] + s["down_ms"] for s in policy["nods"]] == [i * 40 for i in maxima]


def test_registered_mask_preserves_face_tapers_upper_neck_and_anchors_shoulders():
    native = np.full((100, 100), .9, np.float32)
    mesh = np.zeros((1, 478, 3), np.float32)
    mesh[0, 10, 1], mesh[0, 152, 1] = .25, .70
    mesh[0, 234, 0], mesh[0, 454, 0] = .30, .70
    image = np.zeros((200, 200, 3), np.uint8)
    image[80, 120] = [20, 30, 40]
    def detect(crop):
        # Verify the mesh sees the registered crop, including affine translation.
        np.testing.assert_array_equal(crop[30, 60], [20, 30, 40])
        return mesh
    mask = registered_head_mask(native, image, np.array([[1., 0, 60], [0, 1., 50]]), detect)
    assert np.array_equal(mask[:63], native[:63])  # Eyes and mouth retain native blending.
    assert mask[70, 50] == native[70, 50]
    assert 0 < mask[77, 50] < native[77, 50]
    assert mask[77, 85] == 0 and np.all(mask[86:] == 0)
    assert np.all(np.diff(mask, axis=0) <= 0) and np.all(native == .9)


def test_nod_driver_is_source_anchored_but_regular_idles_keep_native_motion(monkeypatch, tmp_path):
    import app.main as main
    setup_args = []
    fake_sdk = SimpleNamespace(setup=lambda *a, **kw: setup_args.append(kw),
                               setup_Nd=lambda *a, **kw: None, run_chunk=lambda *a: None,
                               close=lambda: None)
    runtime = DittoLiveRuntime(SimpleNamespace(sampling_timesteps=1))
    runtime.native_putback_mask = np.ones((2, 2), np.float32)
    runtime.putback = SimpleNamespace()
    runtime.head_masks["demo-seoyeon"] = np.zeros((2, 2), np.float32)
    runtime.avatar_sources.update({"demo-seoyeon": {}, "other": {}})
    monkeypatch.setattr(runtime, "_load_sdk", lambda: fake_sdk)
    monkeypatch.setattr(main, "IdleJpegFrameSink", lambda *a, **kw: SimpleNamespace(frame_count=0, close=lambda: None))
    for variant in range(6):
        runtime._generate_idle_blocking("demo-seoyeon", variant, tmp_path)
        assert setup_args[-1]["use_d_keys"] == (() if variant in LISTENING_NODS else None)
        assert setup_args[-1]["drive_eye"]
        assert runtime.putback.mask_ori_float is runtime.head_masks["demo-seoyeon"]
    runtime._source_for_render("other")
    assert runtime.putback.mask_ori_float is runtime.native_putback_mask
