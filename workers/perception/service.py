"""Local, authenticated camera owner. No camera opens until an explicit start.

Only one session owns the device; a heartbeat lease releases it after tab loss.
Raw frames and the preview are memory-only. No cloud calls or identity tracking.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from observations import ObservationBuffer

ROOT = Path(__file__).resolve().parents[2]


class CameraOwner:
    def __init__(self, model_dir, camera_index=0):
        self.model_dir = Path(model_dir)
        self.camera_index = camera_index
        self.lock = threading.RLock()
        self.session = None
        self.deadline = 0
        self.generation = 0
        self.state = 'off'
        self.error = ''
        self.error_session = None
        self.preview = b''
        self.buffer = ObservationBuffer()
        self.thread = None
        self.stop_event = threading.Event()

    def start(self, session):
        with self.lock:
            if self.session and self.session != session:
                raise HTTPException(409, 'Camera belongs to another active session')
            if self.thread and self.thread.is_alive():
                if self.stop_event.is_set():
                    raise HTTPException(409, 'Camera is closing; retry shortly')
                self.deadline = time.monotonic()+12
                return
            self.session = session
            self.deadline = time.monotonic()+12
            self.generation += 1
            self.buffer.clear()
            self.preview = b''
            self.error = ''
            self.error_session = None
            self.state = 'starting'
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self.run, args=(self.generation,), daemon=True)
            self.thread.start()

    def check(self, session):
        if session != self.session:
            raise HTTPException(409, 'No camera lease for this session')

    def stop(self, session):
        with self.lock:
            self.check(session)
            self.stop_event.set()
            self.buffer.clear()
            self.preview = b''
            self.state = 'off'

    def status(self, session, window=3000, speaking=False, heartbeat=False, end_age_ms=0):
        with self.lock:
            if session == self.error_session and self.state == 'error':
                return dict(state='error',error=self.error,observation={'status':'unavailable','reason':'camera_error'})
            self.check(session)
            if heartbeat and not self.stop_event.is_set():
                self.deadline = time.monotonic()+12
            summary = self.buffer.summarize(time.monotonic(), window, speaking,end_age_ms)
            return dict(state=self.state, error=self.error, observation=summary,
                        camera_index=self.camera_index, max_faces=1, preview_available=bool(self.preview))

    def run(self, generation):
        cap = detector = None
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            from sobia_face import EmotionClassifierRuntime, build_face_candidate_payload
            manifest = json.loads((self.model_dir/'manifest.json').read_text())
            for name, digest in manifest['sha256'].items():
                if hashlib.sha256((self.model_dir/name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError('Perception model hash mismatch: '+name)
            classifier = EmotionClassifierRuntime(self.model_dir/'classifier.json')
            if not classifier.enabled:
                raise RuntimeError('Classifier unavailable: '+classifier.last_error)
            detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.model_dir/'face_landmarker.task')),
                running_mode=vision.RunningMode.VIDEO, num_faces=1,
                output_face_blendshapes=True, output_facial_transformation_matrixes=True,
                min_face_detection_confidence=.5, min_face_presence_confidence=.5,
                min_tracking_confidence=.5))
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not cap.isOpened():
                raise RuntimeError('Cannot open camera; close other camera applications')
            missing = True
            stamp = 0
            while not self.stop_event.is_set() and time.monotonic() < self.deadline:
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Camera frame read failed')
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                stamp = max(stamp+1, round(started*1000))
                prediction = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), stamp)
                if not prediction.face_landmarks:
                    face = None
                    if not missing:
                        with self.lock:
                            self.buffer.clear()
                        # Drop temporal classifier memory on loss; never carry across people.
                        classifier._smoothed_probs = None
                        classifier._smoothing_timestamp = None
                        classifier._smoothing_label = None
                        classifier._guard_candidate_label = None
                        classifier._guard_candidate_count = 0
                        classifier._negative_class_candidate_label = None
                        classifier._negative_class_candidate_count = 0
                    missing = True
                else:
                    missing = False
                    raw = build_face_candidate_payload(prediction, 0, rgb, classifier)
                    affect = raw['apparentAffect']
                    ekman = affect['apparentEkman']
                    cues = {c['name']: c['score'] for c in affect['cues']}
                    blend = {c['name']: c['score'] for c in raw['blendshapes']}
                    cues['eyeWide'] = (blend.get('eyeWideLeft', 0)+blend.get('eyeWideRight', 0))/2
                    head = raw['headEulerDeg']
                    # Quality is explicitly a heuristic gate, not detector confidence.
                    face = dict(provider=affect['provider'],
                                usable=affect['provider'] == classifier.provider and raw['faceWidth'] >= .10 and abs(head['y']) <= 45 and abs(head['x']) <= 35,
                                scores={k:ekman[k] for k in ('neutral','happiness','sadness','anger','fear','surprise','disgust') if k in ekman},
                                cues=cues, head=dict(yaw=head['y'],pitch=head['x'],roll=head['z']),
                                face_center=raw['faceCenter'], face_width=raw['faceWidth'],
                                left_eye=raw['leftEye'], right_eye=raw['rightEye'],
                                blendshapes=blend, classifier_ms=affect.get('classifierLatencyMs',0))
                elapsed = (time.monotonic()-started)*1000
                _, jpeg = cv2.imencode('.jpg', cv2.resize(frame, (320,240)), [cv2.IMWRITE_JPEG_QUALITY,65])
                with self.lock:
                    if self.stop_event.is_set() or self.generation != generation:
                        break
                    self.state = 'running'
                    self.buffer.add(time.monotonic(), face, elapsed)
                    self.preview = jpeg.tobytes()
                self.stop_event.wait(max(0, .1-(time.monotonic()-started)))
        except Exception as exc:
            with self.lock:
                self.error = str(exc)[:250]
                self.error_session = self.session
                self.state = 'error'
        finally:
            if cap is not None:
                cap.release()
            if detector is not None:
                detector.close()
            with self.lock:
                self.buffer.clear()
                self.preview = b''
                self.session = None
                if self.state != 'error':
                    self.state = 'off'


class Control(BaseModel):
    session_id: str = Field(min_length=1,max_length=128)
    window_ms: int = Field(default=3000,ge=200,le=120000)
    speaking: bool = False
    end_age_ms: int = Field(default=0,ge=0,le=5000)


def create_app(owner, token):
    if len(token) < 32:
        raise ValueError('A strong local service token is required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def authenticate(request, call_next):
        if not secrets.compare_digest(request.headers.get('x-perception-token',''),token):
            return Response(status_code=401)
        return await call_next(request)

    @app.post('/{action}')
    def command(action: str, body: Control):
        if action == 'start':
            owner.start(body.session_id)
        elif action == 'stop':
            owner.stop(body.session_id)
            return {'state':'off'}
        elif action not in ('status','summary','preview'):
            raise HTTPException(404)
        if action == 'preview':
            with owner.lock:
                owner.check(body.session_id)
                return Response(owner.preview, media_type='image/jpeg',headers={'Cache-Control':'no-store'})
        return owner.status(body.session_id,body.window_ms,body.speaking,heartbeat=action in ('start','status'),end_age_ms=body.end_age_ms)

    @app.get('/health')
    def health():
        return {'status':'ok','state':owner.state,'error':owner.error,'max_faces':1}
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera',type=int,default=0)
    parser.add_argument('--port',type=int,default=8020)
    parser.add_argument('--host',default='127.0.0.1')
    args = parser.parse_args()
    import uvicorn
    token = (ROOT/'data/perception/token').read_text().strip()
    uvicorn.run(create_app(CameraOwner(ROOT/'models/perception',args.camera),token),host=args.host,port=args.port,access_log=False)
