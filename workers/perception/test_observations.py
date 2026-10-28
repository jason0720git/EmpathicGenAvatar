import time
from fastapi.testclient import TestClient
from observations import ObservationBuffer
from service import CameraOwner,create_app


def face(label='happiness'):
    return dict(usable=True,provider='test',scores={label:.8,'neutral':.1},
                cues={'smile':.7,'mouthOpen':.9,'browRaise':.05,'eyeWide':.05},head={'yaw':3})


def test_missing_is_not_neutral_and_drops_prior_face():
    b=ObservationBuffer()
    assert b.summarize(10)['status']=='unavailable'
    for t in (9.7,9.8,9.9):b.add(t,face())
    assert b.summarize(10)['label']=='happiness'
    b.add(10,None)
    assert b.summarize(10)['status']=='unavailable'
    assert b.summarize(12)['reason']=='stale'


def test_speech_mouth_alone_does_not_assert_surprise():
    b=ObservationBuffer()
    for t in (9.7,9.8,9.9):b.add(t,face('surprise'))
    assert b.summarize(10,speaking=True)['label']=='uncertain'
    assert b.summarize(10,speaking=False)['label']=='surprise'


def test_bounded_and_low_quality():
    b=ObservationBuffer()
    for i in range(2000):b.add(i/10,None)
    assert len(b.samples)==1800
    for t in (199.8,199.9,200):b.add(t,face())
    assert b.summarize(200)['reason']=='insufficient_quality'
    b.clear()
    assert not b.samples


def test_completed_speech_excludes_post_speech_face():
    b=ObservationBuffer()
    for t in (9.1,9.3,9.5):b.add(t,face('happiness'))
    for t in (9.8,9.9,10):b.add(t,face('anger'))
    result=b.summarize(10,1000,True,end_age_ms=500)
    assert result['label']=='happiness'
    b.add(10.1,None)
    assert b.summarize(10.1,1000,True,end_age_ms=600)['status']=='unavailable'


def test_auth_session_isolation_and_stop_clear(tmp_path):
    owner=CameraOwner(tmp_path)
    assert owner.thread is None  # Merely opening website/service never opens webcam.
    owner.session='a';owner.state='running'
    owner.buffer.add(time.monotonic(),face())
    c=TestClient(create_app(owner,'x'*48))
    assert c.get('/health').status_code==401
    headers={'X-Perception-Token':'x'*48}
    assert c.post('/summary',headers=headers,json={'session_id':'b'}).status_code==409
    assert c.post('/status',headers=headers,json={'session_id':'a'}).status_code==200
    assert owner.analysis_fps==5 and owner.preview_until==0
    assert c.post('/preview',headers=headers,json={'session_id':'a'}).status_code==200
    assert owner.preview_until>time.monotonic()
    assert owner.deadline>time.monotonic()
    assert c.post('/stop',headers=headers,json={'session_id':'a'}).status_code==200
    assert owner.stop_event.is_set() and not owner.buffer.samples
    assert c.post('/summary',headers=headers,json={'session_id':'a'}).json()['observation']['status']=='unavailable'
