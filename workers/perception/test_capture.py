import sys
from types import SimpleNamespace
from capture import open_camera

def test_explicit_capture_fps_and_backend(monkeypatch):
    class Capture:
        def __init__(self):self.properties={}
        def isOpened(self):return True
        def set(self,key,value):self.properties[key]=value
        def get(self,key):return self.properties.get(key,0)
        def getBackendName(self):return 'MSMF'
    cap=Capture();calls=[]
    cv=SimpleNamespace(CAP_MSMF=1400,CAP_DSHOW=700,CAP_PROP_FRAME_WIDTH=3,CAP_PROP_FRAME_HEIGHT=4,CAP_PROP_FPS=5,CAP_PROP_FOURCC=6,
        VideoCapture=lambda index,backend:(calls.append((index,backend)) or cap))
    monkeypatch.setitem(sys.modules,'cv2',cv)
    _,info=open_camera(0)
    assert calls==[(0,1400)]
    assert info['device_fps']==10 and info['width']==640 and info['height']==480
