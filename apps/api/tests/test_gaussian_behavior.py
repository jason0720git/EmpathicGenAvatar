from __future__ import annotations

import math

import pytest

from app.gaussian_a2f import ARKIT_NAMES
from app.gaussian_behavior import ARTICULATION_CHANNELS, BehaviorController


def test_empathy_controller_preserves_all_speech_articulation_channels():
    controller = BehaviorController()
    raw = {name: ((index * 17) % 100) / 100 for index, name in enumerate(ARKIT_NAMES)}
    result = controller.mix_frame(raw, 1., controller.from_affect("sad", .8, intent="supportive"))
    for name in ARTICULATION_CHANNELS:
        assert result["weights"][name] == raw[name]
    assert result["weights"]["browInnerUp"] > 0
    assert result["weights"]["mouthSmileLeft"] <= .035
    assert result["weights"]["mouthSmileRight"] <= .035
    assert result["raw_weights"] == raw
    assert result["composition"]["articulation_owner"] == "nvidia_a2f"


def test_listening_does_not_replay_stale_speech_and_keeps_gaze_blink():
    controller = BehaviorController()
    plan = controller.from_affect(intent="attentive", gaze={"x": .8, "y": -.5})
    frame = controller.mix_frame({"jawOpen": .8}, 3.18, plan, speaking=False)
    assert frame["weights"]["jawOpen"] == 0
    assert frame["weights"]["eyeBlinkLeft"] > .95
    assert frame["weights"]["eyeLookInLeft"] == .44
    assert frame["weights"]["eyeLookDownRight"] == .275
    assert frame["weights"]["browInnerUp"] > 0


def test_nod_is_bounded_and_returns_to_base_after_duration():
    controller = BehaviorController()
    plan = controller.from_affect("neutral", 0., nod=True, nod_start_seconds=.5, nod_duration_seconds=1., nod_amplitude_degrees=4.)
    for t, expected in ((.4, 0), (.5, 0), (1., 4), (1.5, 0), (2., 0)):
        frame = controller.mix_frame({}, t, plan, speaking=False, idle_motion=False)
        assert frame["head"]["pitch"] == pytest.approx(expected)


def test_bounded_manual_controls_and_nonfinite_rejection():
    controller = BehaviorController()
    plan = controller.from_affect("happy", 10., head={"yaw": 50., "pitch": -30}, gaze={"x": -12})
    assert plan.intensity == 1
    assert plan.head["yaw"] == 12
    assert plan.head["pitch"] == -10
    assert plan.gaze["x"] == -1
    with pytest.raises(ValueError, match="finite"):
        controller.from_affect("sad", math.nan)
    with pytest.raises(ValueError, match="Unsupported"):
        controller.from_affect("unknown", .5)


def test_policy_provenance_does_not_claim_trained_empathy_model():
    plan = BehaviorController().from_affect("sad", .5, intent="supportive").as_dict()
    assert plan["source"] == "rule_based_sobia_inspired"
    assert "no trained empathy model" in plan["provenance"]


@pytest.mark.parametrize('emotion,channel', [('happy','mouthSmileLeft'), ('sad','mouthFrownLeft')])
def test_speech_does_not_attenuate_policy_expression(emotion, channel):
    controller = BehaviorController()
    plan = controller.from_affect(emotion, .8)
    speaking = controller.mix_frame({'jawOpen': .4}, 1, plan, speaking=True)
    resting = controller.mix_frame({}, 1, plan, speaking=False)
    assert speaking['weights'][channel] == resting['weights'][channel]
    assert speaking['weights'][channel] >= .28
    assert speaking['weights']['jawOpen'] == .4

@pytest.mark.parametrize('emotion,channel', [('happy','mouthSmileLeft'),('sad','browInnerUp'),('angry','browDownLeft'),('fear','browInnerUp'),('surprise','browOuterUpLeft')])
def test_full_strength_reaches_primary_muscle_maximum(emotion,channel):
    c=BehaviorController()
    frame=c.mix_frame({'jawOpen':.31},1,c.from_affect(emotion,1),idle_motion=False)
    assert frame['weights'][channel]==1
    assert frame['weights']['jawOpen']==.31
