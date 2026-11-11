import numpy as np

from app.companion_expression import CompanionExpression
from app.main import BlinkAwareMotionStitch, MotionPlan, RealtimePcmTimeline, build_ditto_ctrl_info


def test_regions_enter_settle_and_respond_to_accent_only_after_audio_arrives():
    policy = CompanionExpression("sad", .7, "story18")
    residual = np.ones((1, 63), dtype=np.float32)
    trace = [None] * 10 + [.05] * 75 + [.009] * 16 + [.17] * 8 + [0.] * 12 + [.12] * 12 + [None] * 25
    # Sample the actual worker transform, including causal audio and turn style.
    series = np.array([policy.apply(residual, rms)[[1, 13, 3], 1] for rms in trace])
    assert not np.any(series[:10])
    assert series[12, 0] > series[12, 2]
    assert .85 < series[36].min() <= series.max() <= 1
    assert series[84, 0] < .5 and series[84, 2] > series[84, 0]
    assert np.all(series[108] > series[99] + .05)
    assert np.all(series[120] < series[108])
    assert np.all(series[-1] < .04)
    assert np.max(abs(np.diff(series, axis=0))) < .15
    np.testing.assert_array_equal(residual, np.ones_like(residual))


def test_style_is_turn_local_replayable_and_preserves_channel_ownership():
    plan = MotionPlan(expression="surprise", intensity=.7, gaze={"mode": "pupil", "x": .6})
    residual = build_ditto_ctrl_info(plan, 100)[20]["delta_exp"].reshape(21, 3)
    protected = [6, 11, 12, 15, 17, 18, 19]
    def render(key):
        policy = CompanionExpression(plan.expression, plan.intensity, key)
        return np.asarray([policy.apply(residual, .05) for _ in range(60)])
    rendered = render("turn-a")
    np.testing.assert_array_equal(rendered, render("turn-a"))
    assert not np.allclose(rendered, render("turn-b"))
    np.testing.assert_array_equal(rendered[:, protected], np.broadcast_to(residual[protected], rendered[:, protected].shape))
    assert np.all(np.abs(rendered) <= np.abs(residual) + 1e-8)
    assert not np.any(rendered[:, [14, 20]])


def test_explicit_mode_retains_raw_residual_and_quiet_lead_does_not_start_performance():
    class Stitch:
        idx = 0
        def __call__(self, source, driving, **kwargs):
            self.idx += 1
            return kwargs["delta_exp"]

    timeline = RealtimePcmTimeline()
    timeline.append(np.concatenate((np.zeros(640 * 4, np.int16), np.full(640 * 8, 9000, np.int16))))
    timeline.finish()
    residual = np.ones((1, 63), dtype=np.float32)
    wrapper = BlinkAwareMotionStitch(Stitch())
    wrapper.set_speech_timeline(timeline, 0, "surprise", turn_key="a", shape_expression=False)
    np.testing.assert_array_equal(wrapper(None, None, delta_exp=residual), residual)
    wrapper = BlinkAwareMotionStitch(Stitch())
    wrapper.set_speech_timeline(timeline, 0, "surprise", turn_key="a")
    sequence = [wrapper(None, None, delta_exp=residual).reshape(21, 3) for _ in range(12)]
    assert all(not np.any(frame[[1, 2, 13, 16, 3, 7]]) for frame in sequence[:4])
    assert sequence[-1][1, 1] > .5


def test_post_render_diagnostics_measure_only_the_pre_stitch_residual():
    policy = CompanionExpression("surprise", .6, "logged")
    plan = MotionPlan(expression="surprise", intensity=.6)
    residual = build_ditto_ctrl_info(plan, 100)[20]["delta_exp"]
    trace = [None] * 5 + [.08] * 50 + [0.] * 15 + [None] * 25
    rendered = np.asarray([policy.apply(residual, rms) for rms in trace])
    stats = policy.diagnostics()
    assert stats["evaluated_frames"] == len(trace) and stats["voiced_frames"] == 50
    assert stats["accent_at_least_0_2_frames"] > 0 and stats["pause_boundary_frames"] > 0
    assert stats["peak_target_gain"]["cheek_corner"] > .9
    # Surprise has no cheek/corner residual even though the shared envelope runs.
    assert stats["peak_abs_residual_component"]["cheek_corner"] == 0
    assert np.isclose(stats["peak_abs_residual_component"]["brow"], abs(rendered[:, [1, 2]]).max(), atol=6e-8)
    assert "pre" in stats["stage"] or "before" in stats["stage"]
