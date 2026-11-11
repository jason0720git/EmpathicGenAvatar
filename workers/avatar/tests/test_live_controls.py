import numpy as np
import pytest

from app.main import MotionPlan, live_target_controls, BlinkAwareMotionStitch
from app.live_controls import LiveControlState


def state(plan=None):
    events=[]
    return LiveControlState(lambda patch:live_target_controls(plan or MotionPlan(),patch),events.append),events


@pytest.mark.parametrize('payload',[
    {'type':'control','seq':1},
    {'type':'control','seq':True,'intensity':.5},
    {'type':'control','seq':1,'intensity':float('nan')},
    {'type':'control','seq':1,'gaze':{'x':1.1}},
    {'type':'control','seq':1,'head':{'yaw_deg':13}},
    {'type':'control.reset','seq':1,'expression':'happy'},
    {'type':'control','seq':1,'expression':'invented'},
    {'type':'control','seq':1,'head':{'roll_deg':7}},
])
def test_invalid_targets_do_not_advance_mailbox(payload):
    control,events=state()
    with pytest.raises(ValueError):control.receive(payload)
    assert control.receive({'type':'control','seq':1,'intensity':.5})['seq']==1
    assert not events


def test_head_speed_bound_new_targets_continue_from_current_and_reset():
    control,events=state()
    control.receive({'type':'control','seq':1,'head':{'yaw_deg':12}})
    values=[control.apply({},i*40)['delta_yaw'] for i in range(80)]
    assert 0<values[0]<=.24
    assert np.max(np.abs(np.diff(values)))<=.240001
    assert 11.9<values[-1]<=12
    control.receive({'type':'control','seq':2,'head':{'yaw_deg':-12}})
    changed=control.apply({},3200)['delta_yaw']
    assert abs(changed-values[-1])<=.240001
    control.receive({'type':'control.reset','seq':3})
    reset=[control.apply({},3240+i*40).get('delta_yaw',0) for i in range(160)]
    assert abs(reset[-1])<.001
    assert [e['seq'] for e in events]==[1,2,3]
    assert events[1]['pts_ms']==3200
    assert control.apply({'delta_yaw':2.5},10000)=={'delta_yaw':2.5}


def test_gaze_does_not_change_head_or_affect_and_input_controls_immutable():
    control,events=state()
    delta=np.ones((1,63),np.float32)*.001
    baseline={'delta_exp':delta,'delta_yaw':1.25}
    control.receive({'type':'control','seq':1,'gaze':{'x':.8,'y':-.2}})
    result=control.apply(baseline,2000)
    assert result['delta_yaw']==1.25
    assert np.all(result['delta_exp'].reshape(21,3)[[1,2,18]]==.001)
    assert not np.array_equal(result['delta_exp'].reshape(21,3)[11],delta.reshape(21,3)[11])
    assert np.all(delta==.001)
    assert events[0]['pupil_delta']==result['delta_exp'].reshape(21,3)[[11,15]].tolist()


def test_latest_sequence_is_applied_once_and_closed_turn_cannot_control_next():
    control,events=state()
    control.receive({'type':'control','seq':1,'intensity':.1})
    control.receive({'type':'control','seq':2,'expression':'sad'})
    with pytest.raises(ValueError):control.receive({'type':'control.reset','seq':1})
    control.apply({},1000);control.apply({},1040)
    assert [e['seq'] for e in events]==[2]
    control.close()
    with pytest.raises(ValueError):control.receive({'type':'control.reset','seq':3})
    next_turn,_=state()
    assert next_turn.apply({},1080)=={}
    assert next_turn.receive({'type':'control','seq':1,'intensity':.2})['seq']==1


def test_ownership_log_counts_paced_channels_and_release_without_counting_zero_weight_frames():
    control, _ = state()
    control.receive({"type": "control", "seq": 1, "gaze": {"x": .5}})
    control.apply({}, 0, boundary_weight=0.)
    control.apply({}, 40)
    control.receive({"type": "control", "seq": 2, "head": {"pitch_deg": 2}})
    control.apply({}, 80)
    assert control.diagnostics()["channel_owned_frames"] == {"face": 0, "gaze": 2, "head": 1}
    control.receive({"type": "control.reset", "seq": 3})
    for frame in range(160):
        control.apply({}, 120 + frame * 40)
    final = control.diagnostics()
    control.apply({}, 8000)
    assert final == control.diagnostics()
    assert final["last_applied_seq"] == final["last_received_seq"] == 3
    assert final["channel_owned_frames"]["head"] > 1 and final["channel_owned_frames"]["face"] == 0


def test_face_override_is_applied_inside_blink_and_lip_protection():
    # A fake stitch includes a coupled lip displacement to verify that live
    # override cannot bypass the existing final articulation projection.
    class Stitch:
        idx=13
        drive_eye=False
        def __call__(self,source,driving,**kwargs):
            self.idx+=1
            output=np.zeros((1,21,3),np.float32)
            if 'delta_exp' in kwargs:
                output+=kwargs['delta_exp'].reshape(1,21,3)
                output[:,17]=1  # coupling from stitching network
            return np.zeros_like(output),output
    control,events=state()
    control.receive({'type':'control','seq':1,'expression':'sad','intensity':.7})
    wrapper=BlinkAwareMotionStitch(Stitch());wrapper.set_live_controls(control,13)
    _,output=wrapper(None,None)
    assert np.any(output)
    assert np.all(output[:,17]==0)
    assert events[0]['pts_ms']==0


def test_actual_boundary_returns_owned_face_head_and_gaze_to_automatic():
    control,_=state()
    control.receive({'type':'control','seq':1,'expression':'happy','intensity':.7,'head':{'yaw_deg':5},'gaze':{'x':.8}})
    for i in range(75):control.apply({},i*40)
    endpoint=control.apply({'delta_yaw':.5},4000,boundary_weight=0)
    assert not np.any(endpoint['delta_exp'])
    assert endpoint['delta_yaw']==.5


def test_socket_receives_controls_while_sending_video_and_rejects_stale(monkeypatch,tmp_path):
    import asyncio
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import app.main as main
    control,_=state()
    packets=asyncio.Queue()
    packets.put_nowait(('video',40,b'jpeg'))
    turn=SimpleNamespace(packets=packets,websocket_connected=asyncio.Event(),
        controls=control,control_events=asyncio.Queue(),task=SimpleNamespace(done=lambda:False))
    monkeypatch.setenv('AVATAR_RENDER_MODE','ditto_realtime')
    monkeypatch.setenv('AVATAR_DATA_ROOT',str(tmp_path))
    monkeypatch.delenv('WORKER_SHARED_TOKEN',raising=False)
    monkeypatch.setattr(main,'DittoRealtimeRuntime',lambda config:SimpleNamespace(turns={'live':turn}))
    with TestClient(main.create_app()) as client:
        with client.websocket_connect('/v1/live/live') as ws:
            assert ws.receive_bytes()==b'\x02\x00\x00\x00\x28jpeg'
            ws.send_json({'type':'control','seq':1,'gaze':{'x':.4}})
            assert ws.receive_json()=={'type':'control.received','seq':1,'mode':'residual_only'}
            ws.send_json({'type':'control.reset','seq':1})
            assert ws.receive_json()['type']=='control.error'
            ws.send_json({'type':'control.reset','seq':2})
            assert ws.receive_json()['type']=='control.received'
    with pytest.raises(ValueError,match='closed'):
        control.receive({'type':'control.reset','seq':3})


def test_playback_feedback_bounds_lookahead_and_close_wakes_native_thread():
    import threading
    control,_=state()
    control.playback({'type':'playback','pts_ms':-1})
    control.wait_for_frame(1200)  # Startup must reach the first audio at 1s.
    entered=threading.Event();completed=threading.Event()
    def render():
        entered.set();control.wait_for_frame(1240);completed.set()
    thread=threading.Thread(target=render);thread.start();assert entered.wait(1)
    assert not completed.wait(.03)
    control.playback({'type':'playback','pts_ms':440})
    assert completed.wait(1);thread.join()
    completed.clear()
    thread=threading.Thread(target=lambda:(control.wait_for_frame(1280),completed.set()));thread.start()
    assert not completed.wait(.03)
    control.close()
    assert completed.wait(1);thread.join()


def test_playback_invalid_regression_and_stale_feedback_release(monkeypatch):
    import app.live_controls as module
    control,events=state()
    for bad in [True,1.5,-2,3_600_001]:
        with pytest.raises(ValueError):control.playback({'type':'playback','pts_ms':bad})
    control.playback({'type':'playback','pts_ms':-1})
    control.wait_for_frame(0)
    control.playback({'type':'playback','pts_ms':0})
    with pytest.raises(ValueError):control.playback({'type':'playback','pts_ms':-1})
    with pytest.raises(ValueError):control.playback({'type':'playback','pts_ms':10000})
    future=module.time.monotonic()+6
    monkeypatch.setattr(module.time,'monotonic',lambda:future)
    control.wait_for_frame(1000)  # No five-second wall-clock wait in the test.
    assert events[-1]['type']=='control.error'
    with pytest.raises(ValueError,match='timeout'):
        control.receive({'type':'control','seq':1,'intensity':.5})
    control.wait_for_frame(20000)  # Rendering can finish rather than deadlock.


def test_consumers_without_playback_feedback_keep_offline_throughput():
    control,_=state()
    control.wait_for_frame(20000)
    assert control.receive({'type':'control','seq':1,'intensity':.4})['seq']==1


def test_early_timing_uses_completed_pcm_with_exact_rounded_tail_endpoint():
    from app.main import RealtimePcmTimeline
    timeline=RealtimePcmTimeline(25,25)
    timeline.append(np.zeros(641,np.int16))  # Partial final PCM frame rounds up.
    assert timeline.final_timing() is None
    timeline.finish()
    assert timeline.final_timing()=={'type':'stream.timing','tail_start_ms':1080,'video_end_ms':2080}
    assert timeline.final_timing()['video_end_ms']==timeline.frame_count()*40
    assert timeline.accepts_video(2040) and not timeline.accepts_video(2080)
    with pytest.raises(ValueError,match='completion'):
        timeline.append(np.zeros(640,np.int16))
    timeline.cancel()
    assert timeline.final_timing() is None
