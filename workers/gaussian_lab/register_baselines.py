"""Add reproducible, clearly labelled baseline assets without changing production IDs."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.gaussian_store import validate_asset_zip


def main():
    items = [('emma', 'Emma', '2a80fe76d5f44beba2a3c0ac', 'b90000000000000000000001'),
             ('seoyeon', '서연', '88546d4a362b4a97979c5360', 'b90000000000000000000002')]
    records = []
    for slug, label, original_id, avatar_id in items:
        source = ROOT / 'data/gaussian/avatars' / original_id / 'source.png'
        generated = ROOT / 'data/gaussian/reconstruction-v9' / slug
        asset = (generated / 'avatar.zip').read_bytes()
        validate_asset_zip(asset)
        manifest = json.loads((generated / 'generation.json').read_text())
        target = ROOT / 'data/gaussian/avatars' / avatar_id
        target.mkdir(parents=True, exist_ok=True)
        (target / 'asset.zip').write_bytes(asset)
        shutil.copyfile(source, target / 'source.png')
        record = dict(id=avatar_id, name=f'{label} · LAM 무보정 비교용 v9', source='photo',
                      status='ready', created_at=datetime.now(timezone.utc).isoformat(),
                      asset_url=f'/gaussian-api/avatars/{avatar_id}/asset.zip',
                      image_url=f'/gaussian-api/avatars/{avatar_id}/source',
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      asset_sha256=hashlib.sha256(asset).hexdigest(), engine='LAM', error=None,
                      source_camera=manifest['source_camera'],
                      generation={'method': 'upstream-lam-without-project-calibration',
                                  'derived_from_source': original_id, 'manifest': manifest,
                                  'purpose': 'diagnostic baseline; not an improved final avatar',
                                  'quality_pass': False,
                                  'limitation': 'Pale oral interior reproduced by native Python renderer at large jaw angles'})
        (target / 'record.json').write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf8')
        records.append({'id': avatar_id, 'name': record['name'], 'asset_sha256': record['asset_sha256']})
    (ROOT / 'data/gaussian/reconstruction-v9/baseline-library.json').write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps(records, ensure_ascii=False))


if __name__ == '__main__':
    main()
