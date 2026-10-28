"""Measure source vs actual browser render with the same 68-point detector.

Read-only image analysis. Does not retouch or synthesize input/render pixels.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import numpy as np


def align_eyes(source, rendered):
    def anchors(points):
        return np.array([points[36:42].mean(0), points[42:48].mean(0)])
    src, dst = anchors(source), anchors(rendered)
    a, b = src[1]-src[0], dst[1]-dst[0]
    scale = np.linalg.norm(b)/np.linalg.norm(a)
    angle = np.arctan2(b[1], b[0])-np.arctan2(a[1], a[0])
    rotation = np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    return (source-src.mean(0)) @ rotation.T*scale+dst.mean(0), np.linalg.norm(b)


def metrics(source, rendered):
    target, distance = align_eyes(source, rendered)
    residual = target-rendered
    groups = {'contour':slice(0,17),'brows':slice(17,27),'nose':slice(27,36),
              'eyes':slice(36,48),'mouth':slice(48,68),'all':slice(0,68)}
    return target, {k:float(np.linalg.norm(residual[s],axis=1).mean()/distance*100)
                    for k,s in groups.items()}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('source',type=Path);parser.add_argument('render',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--render-box',type=int,nargs=4,metavar=('X','Y','W','H'))
    args=parser.parse_args();sys.argv=[sys.argv[0]]
    root=Path(os.environ.get('LAM_ROOT','/opt/lam'));os.chdir(root);sys.path.insert(0,str(root))
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD']='1'
    if 'int' not in np.__dict__: np.int = int
    import cv2
    from external.landmark_detection.infer_image import Alignment
    from external.landmark_detection.FaceBoxesV2.faceboxes_detector import FaceBoxesDetector
    path=str(root/'model_zoo/flame_tracking_models/68_keypoints_model.pkl')
    model=Alignment(argparse.Namespace(config_name='alignment',model_path=path),path,'pytorch',[0])
    detector=FaceBoxesDetector('FaceBoxes',str(root/'model_zoo/flame_tracking_models/FaceBoxesV2.pth'),True,'cuda:0')
    def detect(path,box=None):
        img=cv2.imread(str(path))
        if box:
            x,y,w,h=box;img=img[y:y+h,x:x+w].copy()
        detections,_=detector.detect(img,.8,1)
        if not len(detections):raise ValueError('No face detected: '+str(path))
        detection=max(detections,key=lambda d:d[4]*d[5]); x,y,w,h=detection[2:6]
        return model.analyze(img,float(max(w,h)/180),float(x+w/2),float(y+h/2)), list(img.shape[:2])
    source,_=detect(args.source);render,shape=detect(args.render,args.render_box)
    target,score=metrics(source,render)
    report={'source':str(args.source),'render':str(args.render),'render_size':shape,'render_box':args.render_box,
            'metric':'mean landmark distance / eye-center distance (%) after eye similarity alignment',
            'source_landmarks':source.tolist(),'render_landmarks':render.tolist(),'target_landmarks':target.tolist(),
            'error_percent':score}
    args.output.write_text(json.dumps(report,indent=2));print(json.dumps(score))


if __name__=='__main__':main()
