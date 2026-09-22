"""Copy approved local SOBIA model assets; no network model downloads."""
import argparse
import hashlib
import json
import secrets
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('sobia',type=Path)
args = parser.parse_args()
source = args.sobia.resolve()/'Tools/mediapipe_webcam_bridge/models'
dest = root/'models/perception'
dest.mkdir(parents=True,exist_ok=True)
config_path = source/'emotion_classifier/emotion_classifier_config_v3_guard_strict.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
config['hard_negative_logging']['enabled'] = False
assets = ['image_model','image_metadata','blendshape_model','blendshape_metadata','gated_fusion_model','gated_fusion_metadata']
for key in assets:
    shutil.copy2(source/'emotion_classifier'/config[key],dest/config[key])
shutil.copy2(source/'face_landmarker.task',dest/'face_landmarker.task')
# Generated runtime configs, not source-code edits.
(dest/'classifier.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
files = [config[k] for k in assets]+['face_landmarker.task','classifier.json']
manifest = dict(preset='SOBIA V3GuardStrict',sha256={n:hashlib.sha256((dest/n).read_bytes()).hexdigest() for n in files})
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
token_path = root/'data/perception/token'
token_path.parent.mkdir(parents=True,exist_ok=True)
if not token_path.exists():
    token_path.write_text(secrets.token_urlsafe(48),encoding='utf-8')
print('Provisioned local assets and private token; no camera opened.')
