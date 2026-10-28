import asyncio
import base64
import pytest
from app.gaussian_realtime import RealtimeVoice, BehaviorIntent


def test_manual_mode_skips_tool_planning_and_preserves_selected_emotion():
    async def run():
        voice=RealtimeVoice('unused','unused','marin','',lambda *args:None)
        voice.manual_intent=BehaviorIntent(emotion='sad',intensity=.8,head={'pitch':3})
        sent=[];plans=[];audio=[]
        async def start(): pass
        async def send(event): sent.append(event)
        events=iter([{'type':'response.output_audio.delta','delta':base64.b64encode(bytes(100)).decode()},
                     {'type':'response.done','response':{'status':'completed'}}])
        async def receive(*args): return next(events)
        async def intent(plan): plans.append(plan)
        async def speech(pcm): audio.append(pcm)
        async def transcript(*args):pass
        voice.start=start;voice.send=send;voice.receive=receive
        await voice.turn('Good news',None,'',intent,speech,transcript)
        responses=[e['response'] for e in sent if e['type']=='response.create']
        assert responses==[{'tool_choice':'none'}]
        assert plans[0].emotion=='sad' and plans[0].head.pitch==3
        assert audio
    asyncio.run(run())


def test_auto_head_and_gaze_are_bounded():
    assert BehaviorIntent(head={'yaw':8},gaze={'y':-.2}).head.yaw==8
    with pytest.raises(ValueError): BehaviorIntent(head={'yaw':80})
    with pytest.raises(ValueError): BehaviorIntent(gaze={'x':float('nan')})


def test_head_tilt_alias_preserves_strict_validation_and_canonical_output():
    plan = BehaviorIntent.model_validate_json('{"head":{"tilt":-3}}')
    assert plan.head.roll == -3
    assert plan.model_dump()['head'] == {'pitch': 0, 'yaw': 0, 'roll': -3}
    assert BehaviorIntent(head={'roll': -3, 'tilt': -3}).head.roll == -3
    for head in ({'tilt': 7}, {'tilt': float('nan')},
                 {'tilt': -3, 'roll': 2}, {'unknown': 0}):
        with pytest.raises(ValueError):
            BehaviorIntent(head=head)


@pytest.mark.parametrize('event_type', ['response.output_item.done', 'response.function_call_arguments.done'])
def test_auto_tilt_tool_response_continues_to_speech(event_type):
    async def run():
        voice = RealtimeVoice('unused', 'unused', 'marin', '', lambda *args: None)
        sent, plans, audio = [], [], []
        call = {'type': 'function_call', 'name': 'set_avatar_behavior',
                'arguments': '{"emotion":"sad","head":{"tilt":-3,"nod":true}}', 'call_id': 'test-call'}
        event = ({'type': event_type, 'item': call} if event_type == 'response.output_item.done'
                 else {**call, 'type': event_type})
        events = iter([event, {'type': 'response.done', 'response': {'status': 'completed'}},
                       {'type': 'response.output_audio.delta', 'delta': base64.b64encode(bytes(100)).decode()},
                       {'type': 'response.done', 'response': {'status': 'completed'}}])
        async def start(): pass
        async def send(event): sent.append(event)
        async def receive(*args): return next(events)
        async def intent(plan): plans.append(plan)
        async def speech(pcm): audio.append(pcm)
        async def transcript(*args): pass
        voice.start, voice.send, voice.receive = start, send, receive
        result = await voice.turn('test', None, '', intent, speech, transcript)
        assert plans[0].head.roll == -3 and plans[0].emotion == 'sad'
        assert plans[0].nod is True
        assert audio and result['samples'] == 50
        assert sent[-1] == {'type': 'response.create', 'response': {'tool_choice': 'none'}}
    asyncio.run(run())
