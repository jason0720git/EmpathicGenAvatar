"""Offline fixture smoke test. Does not open a camera or call any external API."""
import json
import argparse
import time
from pathlib import Path
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from sobia_face import EmotionClassifierRuntime,build_face_candidate_payload
from observations import ObservationBuffer

root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--frames',type=int,default=12)
parser.add_argument('--fps',type=float,default=10)
args=parser.parse_args()
cv2.setNumThreads(1)
models=root/'models/perception'
runtime=EmotionClassifierRuntime(models/'classifier.json')
assert runtime.enabled,runtime.last_error
image=cv2.cvtColor(cv2.imread(str(root/'artifacts/geometry-handoff-qa/idle.jpg')),cv2.COLOR_BGR2RGB)
options=vision.FaceLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(models/'face_landmarker.task')),running_mode=vision.RunningMode.VIDEO,num_faces=1,output_face_blendshapes=True,output_facial_transformation_matrixes=True)
with vision.FaceLandmarker.create_from_options(options) as detector:
    timings=[]
    cpu_start=time.process_time(); wall_start=time.perf_counter()
    for index in range(max(3,args.frames)):
        t=time.perf_counter()
        result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=image),index*100)
        face=build_face_candidate_payload(result,0,image,runtime)
        assert face is not None and len(face['blendshapes'])>=50
        assert 'neutral' in face['apparentAffect']['apparentEkman']
        timings.append((time.perf_counter()-t)*1000)
        time.sleep(max(0,1/args.fps-(time.perf_counter()-t)))
    print(json.dumps({'fixture':'idle.jpg','frames':len(timings),'mean_ms':round(sum(timings[2:])/len(timings[2:]),2),'cpu_core_percent':round(100*(time.process_time()-cpu_start)/(time.perf_counter()-wall_start),1),'provider':runtime.provider,'label':face['apparentAffect']['classifierLabel'],'max_faces':1}))
