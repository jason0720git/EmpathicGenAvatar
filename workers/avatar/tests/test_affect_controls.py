from __future__ import annotations

import numpy as np

from app.main import MotionPlan, build_ditto_ctrl_info, build_ditto_emotion_condition, DITTO_EMOTION_INDEX, DITTO_AFFECT_DELTA_EXP, PROTECTED_EYE_POINTS


def test_affect_intensity_blends_ditto_emotion_from_neutral() -> None:
    neutral = build_ditto_emotion_condition(MotionPlan(expression="happy", intensity=0), 4)
    joy = build_ditto_emotion_condition(MotionPlan(expression="happy", intensity=1, expression_render_mode="native"), 4)

    assert neutral.shape == (4, 8)
    assert np.allclose(neutral[:, 4], neutral[0, 4])
    assert joy[0, 3] > joy[0, 4]
    assert neutral[0, 4] > neutral[0, 3]


def test_concern_preset_adds_a_ramped_delta_exp_residual() -> None:
    controls = build_ditto_ctrl_info(MotionPlan(expression="sad", intensity=0.5), frame_count=30, frame_offset=13)

    assert "delta_exp" not in controls[0]
    assert "delta_exp" in controls[13]
    assert controls[13]["delta_exp"].shape == (1, 63)
    assert np.linalg.norm(controls[17]["delta_exp"]) > np.linalg.norm(controls[13]["delta_exp"])
    assert np.linalg.norm(controls[42]["delta_exp"]) < np.linalg.norm(controls[17]["delta_exp"])


def test_each_non_neutral_affect_has_a_distinct_delta_exp_template() -> None:
    norms = {
        affect: np.linalg.norm(build_ditto_ctrl_info(MotionPlan(expression=affect, intensity=1), frame_count=30)[10]["delta_exp"])
        for affect in DITTO_EMOTION_INDEX if affect != "neutral"
    }

    assert all(value > 0 for value in norms.values())
    assert len({v.tobytes() for v in DITTO_AFFECT_DELTA_EXP.values()}) == 8
    for name, template in DITTO_AFFECT_DELTA_EXP.items():
        assert np.isfinite(template).all()
        assert np.max(np.abs(template)) <= 0.025
        assert not np.any(template.reshape(21, 3)[list(PROTECTED_EYE_POINTS)])
        condition = build_ditto_emotion_condition(MotionPlan(expression=name, intensity=1, expression_render_mode="legacy"), 1)
        assert condition.argmax() == DITTO_EMOTION_INDEX["neutral" if name in {"fear", "surprise"} else name]


def test_expression_test_sharpens_conditioning_without_uncalibrated_residual() -> None:
    automatic = MotionPlan(expression="surprise", intensity=0.5)
    manual = MotionPlan(expression="surprise", intensity=0.5, expression_test=True)

    automatic_condition = build_ditto_emotion_condition(automatic, 4)
    manual_condition = build_ditto_emotion_condition(manual, 4)
    automatic_delta = build_ditto_ctrl_info(automatic, frame_count=30)[10]["delta_exp"]
    manual_controls = build_ditto_ctrl_info(manual, frame_count=30)

    assert np.allclose(manual_condition, automatic_condition)
    assert manual_condition[0].argmax() == DITTO_EMOTION_INDEX["neutral"]
    assert automatic_delta.shape == (1, 63)
    assert np.linalg.norm(manual_controls[10]["delta_exp"]) > np.linalg.norm(automatic_delta)


def test_zero_intensity_and_neutral_do_not_inject_expression():
    for name in DITTO_EMOTION_INDEX:
        controls = build_ditto_ctrl_info(MotionPlan(expression=name, intensity=0, expression_test=True), 30)
        assert all("delta_exp" not in c for c in controls.values())


def test_retuned_states_never_add_jaw_center_offsets():
    for name in ("surprise", "fear", "sad", "contempt"):
        for intensity in (0.25, 0.5, 1.0):
            for manual in (False, True):
                controls = build_ditto_ctrl_info(MotionPlan(expression=name, intensity=intensity, expression_test=manual), 150, frame_offset=13)
                for control in controls.values():
                    if "delta_exp" in control:
                        d = control["delta_exp"].reshape(21, 3)
                        assert not np.any(d[[6, 12, 17, 19]])
                        if name == "surprise":
                            assert not np.any(d[[14, 20]])


def test_surprise_reaction_settles_but_retains_brow_expression():
    c = build_ditto_ctrl_info(MotionPlan(expression="surprise", intensity=1, expression_test=True), 150)
    assert 0 < np.linalg.norm(c[100]["delta_exp"]) < np.linalg.norm(c[12]["delta_exp"])


def test_fear_surprise_use_neutral_audio_motion_but_distinct_brows():
    baseline = build_ditto_emotion_condition(MotionPlan(expression="neutral"), 4)
    for name in ("fear", "surprise"):
        for intensity in (0, .25, .5, 1):
            for manual in (False, True):
                condition = build_ditto_emotion_condition(MotionPlan(expression=name, intensity=intensity, expression_test=manual), 4)
                assert np.allclose(condition, baseline)
    assert not np.array_equal(DITTO_AFFECT_DELTA_EXP["fear"], DITTO_AFFECT_DELTA_EXP["surprise"])


def test_only_positive_calibrated_lid_axes_can_change():
    for template in DITTO_AFFECT_DELTA_EXP.values():
        eyes = template.reshape(21, 3)[[13, 16]]
        assert not np.any(eyes[:, [0, 2]])
        assert np.all(eyes[:, 1] >= 0)
        assert np.all(eyes[:, 1] <= .0101)


def test_blink_adapter_preserves_blink_and_never_mutates_cached_controls():
    from app.main import BlinkAwareMotionStitch
    class FakeStitch:
        delta_eye_arr = np.array([np.zeros(63), np.ones(63)*.5, np.ones(63)], np.float32)
        delta_eye_idx_list = [0, 1, 2]
        drive_eye = True
        idx = 0
        def __call__(self, source, driving, **kwargs):
            return kwargs["delta_exp"]
    inner = FakeStitch()
    adapter = BlinkAwareMotionStitch(inner)
    original = DITTO_AFFECT_DELTA_EXP['surprise'].copy()
    for index, expected in ((0, 1), (1, .5), (2, 0)):
        inner.idx = index
        adjusted = adapter(None, None, delta_exp=original).reshape(21, 3)
        assert np.allclose(adjusted[[13, 16], 1], original.reshape(21, 3)[[13, 16], 1] * expected)
        assert np.array_equal(adjusted[[1, 2]], original.reshape(21, 3)[[1, 2]])
        assert np.array_equal(original, DITTO_AFFECT_DELTA_EXP['surprise'])
    inner.delta_eye_arr = None
    assert np.array_equal(adapter(None, None, delta_exp=original), original)


def test_distinguishing_components_are_not_just_brow_gain():
    fear, sad, surprise, contempt = [DITTO_AFFECT_DELTA_EXP[n].reshape(21,3) for n in ('fear','sad','surprise','contempt')]
    assert fear[1,0] > 0 and surprise[1,0] == 0
    assert surprise[13,1] > fear[13,1] > sad[13,1] == 0
    assert sad[14,1] > fear[14,1] > 0
    assert contempt[3,1] > 0 > contempt[7,1]
    assert contempt[20,0] != 0 and contempt[20,1] == 0


def test_calibrated_auto_gain_keeps_intensity_linear_and_below_manual():
    from app.main import affect_residual_gain
    for name in ('fear', 'sad', 'surprise', 'contempt'):
        auto = MotionPlan(expression=name, intensity=1)
        half = MotionPlan(expression=name, intensity=.5)
        manual = MotionPlan(expression=name, intensity=1, expression_test=True)
        assert affect_residual_gain(auto) == .65
        a = build_ditto_ctrl_info(auto, 60)[10]['delta_exp']
        h = build_ditto_ctrl_info(half, 60)[10]['delta_exp']
        m = build_ditto_ctrl_info(manual, 60)[10]['delta_exp']
        assert np.allclose(h, a*.5)
        assert np.allclose(a, m*.65)
    assert affect_residual_gain(MotionPlan(expression='happy')) == .35
    assert all('delta_exp' not in c for c in build_ditto_ctrl_info(MotionPlan(expression='neutral', intensity=1), 30).values())


def test_speech_safe_keeps_post_stitch_lips_and_advances_state_once():
    from app.main import BlinkAwareMotionStitch, SPEECH_LIP_POINTS
    class Stitch:
        idx = 0
        d0 = None
        def __call__(self, source, driving, **kwargs):
            self.idx += 1
            if self.d0 is None:
                self.d0 = driving.copy()
            output = driving.copy()
            if 'delta_exp' in kwargs:
                # Mimic a stitch network coupling upper expression into lips.
                output += kwargs['delta_exp'].reshape(1,21,3) + .01
            return source, output
    inner = Stitch()
    wrapper = BlinkAwareMotionStitch(inner)
    source = np.zeros((1,21,3), np.float32)
    audio = np.arange(63,dtype=np.float32).reshape(1,21,3)/100
    delta = DITTO_AFFECT_DELTA_EXP['happy'].copy()
    _, result = wrapper(source, audio.copy(), delta_exp=delta, preserve_speech_lips=True)
    assert np.array_equal(result[:, SPEECH_LIP_POINTS], audio[:, SPEECH_LIP_POINTS])
    assert not np.array_equal(result[:,3], audio[:,3])
    assert inner.idx == 1
    assert np.array_equal(inner.d0, audio)
    assert np.array_equal(delta, DITTO_AFFECT_DELTA_EXP['happy'])
    assert wrapper.protection_stats['frames'] == 1


def test_four_comparison_modes_have_distinct_contracts():
    from app.main import SPEECH_LIP_POINTS
    for mode in ('off','native','legacy','speech_safe'):
        plan = MotionPlan(expression='happy', intensity=1, expression_test=True, expression_render_mode=mode)
        controls = build_ditto_ctrl_info(plan,60)
        condition = build_ditto_emotion_condition(plan,60)
        assert condition.argmax(axis=1)[0] == (4 if mode in ('off','speech_safe') else 3)
        assert ('delta_exp' in controls[10]) == (mode in ('legacy','speech_safe'))
        assert controls[10].get('preserve_speech_lips',False) == (mode == 'speech_safe')
        if mode == 'speech_safe':
            from app.main import SPEECH_CENTER_POINTS
            assert not np.any(controls[10]['delta_exp'].reshape(21,3)[list(SPEECH_CENTER_POINTS)])
            assert controls[10]['allow_smile_corners']


def test_happy_preserves_centers_but_bounds_visible_corner_motion():
    from app.main import BlinkAwareMotionStitch, SPEECH_CENTER_POINTS, SMILE_CORNER_POINTS, SMILE_CORNER_MAX_DELTA
    class Stitch:
        idx = 0
        def __call__(self, source, driving, **kwargs):
            assert 'allow_smile_corners' not in kwargs
            self.idx += 1
            result = driving.copy()
            if 'delta_exp' in kwargs:
                result += kwargs['delta_exp'].reshape(1,21,3) + .02
            return source, result
    inner = Stitch()
    wrapper = BlinkAwareMotionStitch(inner)
    audio = np.arange(63, dtype=np.float32).reshape(1,21,3)/100
    control = build_ditto_ctrl_info(MotionPlan(expression='happy', intensity=1, expression_test=True),60)[10]
    _, result = wrapper(audio.copy(), audio.copy(), **control)
    assert inner.idx == 1
    assert np.array_equal(result[:, SPEECH_CENTER_POINTS], audio[:, SPEECH_CENTER_POINTS])
    distances = np.linalg.norm(result[:,SMILE_CORNER_POINTS]-audio[:,SMILE_CORNER_POINTS],axis=-1)
    assert np.all(distances > 0)
    assert np.all(distances <= SMILE_CORNER_MAX_DELTA + 1e-7)
    for name in ('neutral', 'angry', 'sad', 'surprise'):
        assert not build_ditto_ctrl_info(MotionPlan(expression=name),60)[10].get('allow_smile_corners',False)


def test_happy_zero_and_half_intensity_are_bounded():
    zero = build_ditto_ctrl_info(MotionPlan(expression='happy', intensity=0),60)[10]
    assert 'delta_exp' not in zero and not zero.get('allow_smile_corners',False)
    half = build_ditto_ctrl_info(MotionPlan(expression='happy', intensity=.5, expression_test=True),60)[10]['delta_exp']
    full = build_ditto_ctrl_info(MotionPlan(expression='happy', intensity=1, expression_test=True),60)[10]['delta_exp']
    assert np.allclose(half, full*.5)


def test_realtime_turns_share_exclusive_sdk_lock():
    import asyncio
    from app.main import DittoRealtimeRuntime
    async def check():
        runtime = object.__new__(DittoRealtimeRuntime)
        runtime.lock = asyncio.Lock()
        active = 0
        peak = 0
        async def run(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
        runtime._run_realtime_exclusive = run
        await asyncio.gather(*(runtime._run_realtime(None,None,None,None,None) for _ in range(3)))
        assert peak == 1 and active == 0
    asyncio.run(check())


def test_cancel_waits_for_native_thread_before_releasing_sdk():
    import asyncio
    import tempfile
    import threading
    import wave
    from pathlib import Path
    from types import SimpleNamespace
    from app.main import DittoRealtimeRuntime, RenderIn, RealtimePcmTimeline, RealtimeTurnMetrics
    async def check(root):
        runtime = object.__new__(DittoRealtimeRuntime)
        runtime.lock = asyncio.Lock()
        runtime.config = SimpleNamespace(data_root=root)
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def native(*args):
            entered.set()
            release.wait(2)
            finished.set()
        runtime._run_realtime_sdk = native
        connected = asyncio.Event()
        connected.set()
        turn = SimpleNamespace(websocket_connected=connected, packets=asyncio.Queue())
        body = RenderIn(avatar_id='test', turn_id='test', audio_path=str(root/'speech.wav'))
        task = asyncio.create_task(runtime._run_realtime(body, turn, RealtimePcmTimeline(), RealtimeTurnMetrics(), root))
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(.005)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(.01)
        assert runtime.lock.locked() and not task.done() and not finished.is_set()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert finished.is_set() and not runtime.lock.locked()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        with wave.open(str(root/'speech.wav'), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(bytes(3200))
        asyncio.run(check(root))
