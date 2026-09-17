from __future__ import annotations

from app.behavior import BehaviorPlanner
from app.models import AffectIntent, MotionPlan


def test_affect_contract_maps_concern_intensity_to_bounded_pose() -> None:
    decision = BehaviorPlanner().from_affect(AffectIntent(emotion="sad", intensity=0.5))

    assert decision.source == "realtime_tool"
    assert decision.motion_plan.expression == "sad"
    assert decision.motion_plan.intensity == 0.5
    assert decision.motion_plan.head.pitch_deg == 1.1
    assert decision.motion_plan.gaze.y == -0.3


def test_affect_contract_distinguishes_the_six_supported_display_states() -> None:
    planner = BehaviorPlanner()
    states = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise", "contempt")

    assert tuple(planner.from_affect(AffectIntent(emotion=state, intensity=0.4)).motion_plan.expression for state in states) == states


def test_manual_expression_test_preset_is_visibly_stronger_than_auto() -> None:
    planner = BehaviorPlanner()
    affect = AffectIntent(emotion="sad", intensity=0.5)

    automatic = planner.from_affect(affect)
    manual = planner.from_affect(affect, expression_test=True)

    assert manual.motion_plan.expression_test is True
    assert manual.motion_plan.head.pitch_deg > automatic.motion_plan.head.pitch_deg
    assert manual.motion_plan.gaze.y < automatic.motion_plan.gaze.y


def test_manual_joy_preset_has_a_bounded_nod_at_half_intensity() -> None:
    plan = BehaviorPlanner().from_affect(AffectIntent(emotion="happy", intensity=0.5), expression_test=True).motion_plan

    assert plan.nod is not None
    assert plan.nod.amplitude_deg == 2.5


def test_surprise_does_not_receive_a_happy_nod() -> None:
    for manual in (False, True):
        plan = BehaviorPlanner().from_affect(
            AffectIntent(emotion="surprise", intensity=1), expression_test=manual
        ).motion_plan
        assert plan.nod is None


def test_manual_override_is_the_only_way_to_bypass_the_tool_affect() -> None:
    planner = BehaviorPlanner()
    automatic = planner.resolve(
        affect=AffectIntent(emotion="happy", intensity=0.6),
        requested=MotionPlan(expression="neutral", intensity=0),
        motion_override=False,
    )
    overridden = planner.resolve(
        affect=AffectIntent(emotion="happy", intensity=0.6),
        requested=MotionPlan(expression="neutral", intensity=0),
        motion_override=True,
    )

    assert automatic.motion_plan.expression == "happy"
    assert overridden.motion_plan.expression == "neutral"
    assert overridden.source == "manual_override"


def test_non_realtime_backends_have_a_declared_neutral_fallback() -> None:
    decision = BehaviorPlanner().fallback()

    assert decision.affect == AffectIntent(emotion="neutral", intensity=0)
    assert decision.motion_plan == MotionPlan(expression="neutral", intensity=0)
