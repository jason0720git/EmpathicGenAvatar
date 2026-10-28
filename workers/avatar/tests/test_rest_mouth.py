import copy

import numpy as np
import pytest

from app.main import BlinkAwareMotionStitch, REST_MOUTH_GAIN, rest_mouth_offset


class Stitch:
    def __init__(self):
        self.idx = 0

    def __call__(self, source, driving, **kwargs):
        self.idx += 1
        return source['kp'].copy(), driving.copy() + kwargs.get('delta_exp', np.zeros((1, 63))).reshape(1, 21, 3)


@pytest.mark.parametrize('boundary', [None, 0, .5, 1])
@pytest.mark.parametrize('protect', [False, True])
def test_rest_contour_survives_boundary_and_speech_protection(boundary, protect):
    source = {'kp': np.zeros((1, 21, 3), np.float32), 'scale': np.array([[1.4]])}
    driving = np.full((1, 21, 3), .02, np.float32)
    original = driving.copy()
    kwargs = dict(preserve_speech_lips=protect, boundary_alpha=boundary,
                  delta_exp=np.full((1, 63), .01, np.float32))
    before = BlinkAwareMotionStitch(Stitch())
    after = BlinkAwareMotionStitch(Stitch(), REST_MOUTH_GAIN)
    s0, d0 = before(source, driving, **copy.deepcopy(kwargs))
    s1, d1 = after(source, driving, **copy.deepcopy(kwargs))
    np.testing.assert_array_equal(s0, s1)
    np.testing.assert_allclose(d1 - d0, rest_mouth_offset(source['scale'], 2), atol=1e-8)
    np.testing.assert_array_equal(driving, original)
    assert after.inner.idx == 1


def test_relaxation_preserves_audio_motion_and_non_mouth_points():
    source = {'kp': np.zeros((1, 21, 3), np.float32), 'scale': np.array([[1.]])}
    closed = source['kp'].copy()
    opened = closed.copy()
    opened[:, 17, 1] = .03
    stitch = BlinkAwareMotionStitch(Stitch(), REST_MOUTH_GAIN)
    _, a = stitch(source, closed)
    _, b = stitch(source, opened)
    np.testing.assert_allclose(b - a, opened - closed, atol=1e-8)
    unchanged = [i for i in range(21) if i not in (17, 19)]
    np.testing.assert_array_equal(a[:, unchanged], closed[:, unchanged])
    np.testing.assert_array_equal(rest_mouth_offset(1, 100), rest_mouth_offset(1, 2))
    assert not np.any(rest_mouth_offset(1, -1))
