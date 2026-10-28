"""Explicit Windows capture policy, separate from inference frequency."""
import os

# Do not create a hardware-transform path competing with Chrome/renderer GPUs.
# Set before importing cv2 (OpenCV reads this during backend initialization).
os.environ.setdefault('OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS', '0')

def open_camera(index, backend='msmf'):
    import cv2
    api = cv2.CAP_MSMF if backend == 'msmf' else cv2.CAP_DSHOW
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError('Cannot open camera; close other camera applications')
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    # Lower inference FPS alone does NOT lower device/USB capture FPS.
    cap.set(cv2.CAP_PROP_FPS, 10)
    metadata = dict(backend=cap.getBackendName(), requested_fps=10,
                    device_fps=cap.get(cv2.CAP_PROP_FPS),
                    width=cap.get(cv2.CAP_PROP_FRAME_WIDTH),height=cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
                    output_fourcc=cap.get(cv2.CAP_PROP_FOURCC), hardware_transforms=False)
    return cap, metadata
