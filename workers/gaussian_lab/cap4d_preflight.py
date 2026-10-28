"""Fail-closed CAP4D prerequisites check; never substitute the standard FLAME basis."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CAP = ROOT / 'vendor/CAP4D'
PIXEL = ROOT / 'vendor/pixel3dmm'
OUT = ROOT / 'data/gaussian/reconstruction-v9'
EXPECTED = '13799d7215dcfe7d197cf98584fcd23a51521b87a9d22b463e98bd9073e75ff0'


def main():
    checkpoint = CAP / 'data/weights/mmdm/checkpoints/cap4d_mmdm_100k.ckpt'
    required_smoke = [CAP / 'data/assets/flame/flame2023_no_jaw.pkl', checkpoint]
    required_custom = [PIXEL / 'pretrained_weights/uv.ckpt', PIXEL / 'pretrained_weights/normals.ckpt',
                       PIXEL / 'src/pixel3dmm/preprocessing/MICA/data/FLAME2020/generic_model.pkl',
                       PIXEL / 'src/pixel3dmm/preprocessing/MICA/data/FLAME2023/flame2023_no_jaw.pkl']
    checksum = hashlib.file_digest(checkpoint.open('rb'), 'sha256').hexdigest() if checkpoint.is_file() else None
    missing_smoke = [str(p.relative_to(ROOT)) for p in required_smoke if not p.is_file()]
    missing_custom = [str(p.relative_to(ROOT)) for p in required_custom if not p.is_file()]
    report = {
        'status': 'blocked_missing_official_flame' if missing_smoke else 'prerequisites_present_not_yet_validated',
        'cap4d_commit': subprocess.check_output(['git', '-C', str(CAP), 'rev-parse', 'HEAD'], text=True).strip(),
        'pixel3dmm_commit': subprocess.check_output(['git', '-C', str(PIXEL), 'rev-parse', 'HEAD'], text=True).strip(),
        'mmdm_sha256': checksum, 'mmdm_verified': checksum == EXPECTED,
        'missing_smoke': missing_smoke, 'missing_custom_tracking': missing_custom,
        'custom_tracking_installation_complete': False,
        'generation_complete': False, 'quality_test_complete': False,
        'action': 'Obtain the official licensed FLAME2023 archive using the owner account; keep no_jaw basis unchanged. Complete Pixel3DMM setup and run smoke before custom jobs.',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'cap4d-preflight.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))
    return 2 if missing_smoke or checksum != EXPECTED else 0


if __name__ == '__main__':
    sys.exit(main())
