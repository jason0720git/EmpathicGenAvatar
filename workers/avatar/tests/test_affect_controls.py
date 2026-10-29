from __future__ import annotations

import numpy as np

from app.main import MotionPlan, build_ditto_ctrl_info, build_ditto_emotion_condition, DITTO_EMOTION_INDEX, DITTO_AFFECT_DELTA_EXP, PROTECTED_EYE_POINTS


def test_pupil_gaze_is_independent_of_pose_and_emotion():
    from app.main import GazeIntent, HeadPose
    for mode in ('off', 'native', 'legacy', 'speech_safe'):
        plan = MotionPlan(intensity=0, expression_render_mode=mode,
                          head=HeadPose(yaw_deg=2, pitch_deg=-1),
                          gaze=GazeIntent(mode='pupil', x=1, y=-1))
        controls = build_ditto_ctrl_info(plan, 40, frame_offset=13)
        assert all(c['delta_yaw'] == 2 and c['delta_pitch'] == -1 for c in controls.values())
        assert all('delta_exp' not in controls[i] for i in range(13))
        assert not np.any(controls[13]['delta_exp'])
        assert not np.any(controls[52]['delta_exp'])
        delta = controls[25]['delta_exp'].reshape(21, 3)
        assert np.all(delta[[11, 15], :2] > 0)
        assert np.max(np.abs(delta)) <= .00401
        assert not np.any(np.delete(delta, [11, 15], axis=0))


def test_pupil_gaze_composes_with_affect_without_changing_lips_or_brows():
    from app.main import GazeIntent
    for name in DITTO_EMOTION_INDEX:
        baseline = build_ditto_ctrl_info(MotionPlan(expression=name), 60)[20]
        with_gaze = build_ditto_ctrl_info(MotionPlan(expression=name, gaze=GazeIntent(mode='pupil', x=-.5, y=.5)), 60)[20]
        difference = (with_gaze['delta_exp'] - baseline.get('delta_exp', 0)).reshape(21, 3)
        assert not np.any(np.delete(difference, [11, 15], axis=0))
        assert np.all(difference[[11, 15], :2] < 0)


def test_blink_suppresses_pupil_residual_and_preserves_control_cache():
    from app.main import BlinkAwareMotionStitch, GazeIntent, pupil_gaze_delta
    class Stitch:
        delta_eye_arr = np.array([np.zeros(63), np.ones(63)], np.float32)
        delta_eye_idx_list = [0, 1]
        drive_eye = True
        idx = 1
        def __call__(self, source, driving, **kwargs):
            return kwargs['delta_exp']
    inner = Stitch()
    delta = pupil_gaze_delta(GazeIntent(mode='pupil', x=1, y=1))
    original = delta.copy()
    adapter = BlinkAwareMotionStitch(inner)
    assert not np.any(adapter(None, None, delta_exp=delta))
    assert np.array_equal(delta, original)
    inner.idx = 0
    assert np.array_equal(adapter(None, None, delta_exp=delta), original)


def test_combined_head_cues_and_nods_stay_within_offset_limits():
    from app.main import HeadPose, GazeIntent, NodIntent
    plan = MotionPlan(head=HeadPose(yaw_deg=12, pitch_deg=10),
                      gaze=GazeIntent(x=1, y=-1), nod=NodIntent(start_ms=0, amplitude_deg=8))
    controls = build_ditto_ctrl_info(plan, 60)
    assert all(abs(c['delta_yaw']) <= 12 and abs(c['delta_pitch']) <= 10 for c in controls.values())


def test_short_turn_does_not_compress_or_reschedule_nod():
    from app.main import NodIntent
    plan = MotionPlan(nod=NodIntent(start_ms=300, duration_ms=460))
    short = build_ditto_ctrl_info(plan, 10, frame_offset=13)
    assert all(c['delta_pitch'] == 0 for c in short.values())
    long = build_ditto_ctrl_info(plan, 60, frame_offset=13)
    assert any(c['delta_pitch'] > 0 for c in long.values())
    assert all(long[i]['delta_pitch'] == 0 for i in range(21))
    assert build_ditto_ctrl_info(plan, 0) == {}


def test_aversion_returns_and_does_not_repeat_or_truncate():
    from app.main import GazeIntent
    plan = MotionPlan(intensity=0, gaze=GazeIntent(mode='pupil', pattern='avert_return', x=.6))
    controls = build_ditto_ctrl_info(plan, 200, frame_offset=13, hold_expression_end=True)
    for frame in (13, 13+49, 13+85, 13+199):
        assert not np.any(controls[frame]['delta_exp'])
    assert np.any(controls[13+62]['delta_exp'])
    assert all(not np.any(c.get('delta_exp', 0)) for c in build_ditto_ctrl_info(plan, 75).values())


def test_listening_loop_has_separate_brief_nod_and_gaze_events():
    from app.main import build_idle_ctrl_info
    controls = build_idle_ctrl_info(2, 400)
    assert all(not np.any(controls[i]['delta_exp']) for i in (0, 100, 161, 399))
    assert np.any(controls[140]['delta_exp'])
    # Both acknowledgements settle well before the loop's boundary.
    assert controls[69]['delta_pitch'] > 1
    assert controls[264]['delta_pitch'] > .8
    assert abs(controls[90]['delta_pitch']) < .6
    assert abs(controls[300]['delta_pitch']) < .6


def test_acoustic_clips_are_anchored_and_channels_are_separate():
    from app.main import build_idle_ctrl_info
    for variant,count in ((3,60),(4,75)):
        controls=build_idle_ctrl_info(variant,count,13)
        assert controls[13]['boundary_alpha']==controls[count+12]['boundary_alpha']==0
        assert controls[13]['delta_pitch']==controls[count+12]['delta_pitch']==0
        assert not np.any(controls[13]['delta_exp']) and not np.any(controls[count+12]['delta_exp'])
        if variant==3:
            assert max(c['delta_pitch'] for c in controls.values()) <= 1.6
            assert all(not np.any(c['delta_exp']) for c in controls.values())
        else:
            assert all(c['delta_pitch']==0 for c in controls.values())


def test_sobia_envelope_uses_current_pcm_and_keeps_pupil_intent():
    from app.main import BlinkAwareMotionStitch, RealtimePcmTimeline
    class Stitch:
        idx=0
        def __call__(self, source, driving, **kwargs):
            self.idx+=1
            return kwargs['delta_exp']
    timeline=RealtimePcmTimeline(lead_frames=1,tail_frames=1)
    timeline.append(np.full(640*4,8000,np.int16));timeline.finish()
    assert timeline.frame_rms(0) is None and timeline.frame_rms(5) is None
    assert np.isclose(timeline.frame_rms(1),8000/32768)
    adapter=BlinkAwareMotionStitch(Stitch());adapter.set_speech_timeline(timeline,0)
    delta=np.ones((1,63),np.float32)*.001
    first=adapter(None,None,delta_exp=delta).reshape(21,3)
    assert first[1,0]==0 and first[11,0]==0
    active=adapter(None,None,delta_exp=delta).reshape(21,3)
    assert 0<active[1,0]<.001 and active[11,0]==delta[0,33]
    assert np.all(delta==.001)
    timeline.cancel();assert timeline.frame_rms(1) is None


def test_short_stream_returns_pupil_during_actual_tail_not_provisional_length():
    from app.main import BlinkAwareMotionStitch, RealtimePcmTimeline
    class Stitch:
        idx=25
        def __call__(self, source, driving, **kwargs):
            self.idx+=1
            return kwargs['delta_exp'].reshape(21,3)[11,0]
    timeline=RealtimePcmTimeline(25,25)
    timeline.append(np.full(640*10,8000,np.int16))
    timeline.finish()
    wrapper=BlinkAwareMotionStitch(Stitch());wrapper.set_speech_timeline(timeline,0)
    delta=np.ones((1,63),np.float32)*.001
    values=[wrapper(None,None,delta_exp=delta) for _ in range(35)]
    assert np.allclose(values[:11],.001)
    assert values[-1]==0
    assert all(a>=b for a,b in zip(values[10:],values[11:]))

    # A glance scheduled only in silence must not start after a short reply.
    stitch=Stitch();stitch.idx=25
    wrapper=BlinkAwareMotionStitch(stitch);wrapper.set_speech_timeline(timeline,0)
    zero=np.zeros((1,63),np.float32)
    for _ in range(10): assert wrapper(None,None,delta_exp=zero)==0
    for _ in range(25): assert wrapper(None,None,delta_exp=delta)==0


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


def test_idle_coordinates_close_at_visible_not_preroll_endpoints():
    from app.main import build_idle_ctrl_info, BlinkAwareMotionStitch, DITTO_PREROLL_FRAMES
    class Stitch:
        def __call__(self, source, driving, **kwargs):
            assert 'boundary_alpha' not in kwargs
            return source, driving
    wrapper = BlinkAwareMotionStitch(Stitch())
    source = np.zeros((1,21,3),np.float32)
    driving = np.ones_like(source)
    for variant in range(3):
        controls=build_idle_ctrl_info(variant,400,frame_offset=DITTO_PREROLL_FRAMES)
        start=DITTO_PREROLL_FRAMES
        end=start+399
        assert controls[start]['boundary_alpha'] == controls[end]['boundary_alpha'] == 0
        assert controls[start+40]['boundary_alpha'] == 1
        assert controls[start+1]['boundary_alpha'] < .002
        assert controls[end-1]['boundary_alpha'] < .002
        for i in (start,end):
            _, output=wrapper(source,driving,**controls[i])
            assert np.array_equal(source,output)


def test_idle_duration_and_blinks_cover_the_longer_loop():
    from app.main import IDLE_FRAME_COUNT, IDLE_FPS, idle_blink_open_frames
    assert IDLE_FRAME_COUNT / IDLE_FPS == 16
    for variant in range(3):
        gaps = idle_blink_open_frames(variant)
        assert len(gaps) == 4 and len(set(gaps)) > 2
        assert sum(gaps) + 15 * len(gaps) < IDLE_FRAME_COUNT - 25


def test_speech_boundary_anchors_only_silent_frames_with_live_duration():
    from app.main import RealtimePcmTimeline, BlinkAwareMotionStitch
    timeline = RealtimePcmTimeline(12, 12)
    timeline.append(np.ones(640 * 10, dtype=np.int16))
    assert timeline.boundary_weight(0) == 0
    assert timeline.boundary_weight(11) == 1
    assert all(timeline.boundary_weight(i) == 1 for i in range(12, 22))
    assert timeline.boundary_weight(33) == 1  # End not yet known.
    timeline.finish()
    assert timeline.boundary_weight(22) == 1
    assert timeline.boundary_weight(33) == 0
    assert all(timeline.boundary_weight(i) >= timeline.boundary_weight(i+1) for i in range(22,33))
    class Stitch:
        idx = 46  # 13 preroll + final visible frame 33
        def __call__(self, source, driving, **kwargs):
            return source, driving
    wrapper = BlinkAwareMotionStitch(Stitch())
    wrapper.set_boundary_timeline(timeline, 13)
    source = np.zeros((1,21,3), np.float32)
    driving = np.ones_like(source)
    assert np.array_equal(wrapper(source, driving)[1], source)


def test_native_motion_defaults_and_original_idle_are_restored():
    import inspect
    from app.main import DittoLiveRuntime, DittoRealtimeRuntime, IDLE_ASSET_VERSION, build_idle_ctrl_info, DITTO_TURN_LEAD_FRAMES, DITTO_TURN_TAIL_FRAMES
    # Do not regress into expression-only head locking in either setup path.
    assert 'use_d_keys=' not in inspect.getsource(DittoLiveRuntime._generate_idle_blocking)
    assert 'use_d_keys=' not in inspect.getsource(DittoRealtimeRuntime._run_realtime_sdk)
    assert 'set_boundary_timeline(' not in inspect.getsource(DittoRealtimeRuntime._run_realtime_sdk)
    assert IDLE_ASSET_VERSION == 13  # Rest-mouth calibration invalidates older loops.
    assert DITTO_TURN_LEAD_FRAMES == DITTO_TURN_TAIL_FRAMES == 25
    for variant in range(3):
        controls=build_idle_ctrl_info(variant,400)
        assert controls[40]['boundary_alpha'] == 1
        assert controls[0]['boundary_alpha'] == controls[399]['boundary_alpha'] == 0
        if variant == 2:
            assert max(abs(c['delta_pitch']) for c in controls.values()) > 1


def test_direct_handoff_keeps_expression_through_last_native_frame():
    controls = build_ditto_ctrl_info(MotionPlan(expression='happy', intensity=1), 60, hold_expression_end=True)
    assert np.array_equal(controls[30]['delta_exp'], controls[59]['delta_exp'])
