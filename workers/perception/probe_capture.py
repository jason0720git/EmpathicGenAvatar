"""Short capture-only diagnostic. No inference, preview, storage or cloud calls."""
import argparse
import json
import time
import cv2

parser = argparse.ArgumentParser()
parser.add_argument('--backend', choices=['dshow','msmf'], default='dshow')
parser.add_argument('--mjpg', action='store_true')
parser.add_argument('--seconds', type=int, default=8)
args = parser.parse_args()
cv2.setNumThreads(1)
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if args.backend=='dshow' else cv2.CAP_MSMF)
try:
    if args.mjpg:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    if args.mjpg:
        cap.set(cv2.CAP_PROP_FPS,10)
    properties={name:cap.get(value) for name,value in [('width',cv2.CAP_PROP_FRAME_WIDTH),('height',cv2.CAP_PROP_FRAME_HEIGHT),('fps',cv2.CAP_PROP_FPS),('fourcc',cv2.CAP_PROP_FOURCC)]}
    start=time.perf_counter();cpu=time.process_time();frames=0;read_ms=[];shape=None
    while time.perf_counter()-start<args.seconds:
        tick=time.perf_counter()
        ok,frame=cap.read()
        if not ok: raise RuntimeError('No camera frame')
        shape=frame.shape
        frames+=1;read_ms.append((time.perf_counter()-tick)*1000)
        time.sleep(max(0,.2-(time.perf_counter()-tick)))
    print(json.dumps(dict(backend=args.backend,mjpg=args.mjpg,properties=properties,shape=shape,frames=frames,read_ms=round(sum(read_ms)/len(read_ms),2),cpu_core_percent=round(100*(time.process_time()-cpu)/(time.perf_counter()-start),2))))
finally:
    cap.release()
