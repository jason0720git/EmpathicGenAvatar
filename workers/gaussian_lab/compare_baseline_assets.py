"""Quantify asset edits separately from the renderer and coefficient transport."""
import json
from pathlib import Path
import sys
import zipfile
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'workers/gaussian'))
from export_asset import decode_glb
from calibrate_asset import read_vectors


def read(avatar_id):
    with zipfile.ZipFile(ROOT / 'data/gaussian/avatars' / avatar_id / 'asset.zip') as z:
        d, b = decode_glb(z.read(next(n for n in z.namelist() if n.endswith('/skin.glb'))))
    mesh = d['meshes'][0]; p = mesh['primitives'][0]
    pos = read_vectors(d, b, p['attributes']['POSITION'])[:20018]
    fields = {n: read_vectors(d, b, t['POSITION'])[:20018]
              for n, t in zip(mesh['extras']['targetNames'], p['targets'])}
    return pos, fields


def main():
    result = {}
    for name, raw_id, derived_id in [('emma','b90000000000000000000001','2a80fe76d5f44beba2a3c0ac'),
                                    ('seoyeon','b90000000000000000000002','88546d4a362b4a97979c5360')]:
        p, fields = read(raw_id); q, other = read(derived_id)
        delta = np.linalg.norm(q-p, axis=1)*1000
        channels = {}
        for key in sorted(fields.keys() & other.keys()):
            diff = np.linalg.norm(fields[key]-other[key], axis=1)*1000
            channels[key] = {'changed_vertices': int((diff>.001).sum()), 'max_difference_mm': float(diff.max())}
        result[name] = {'baseline':raw_id, 'current':derived_id,
                        'base_mean_difference_mm':float(delta.mean()),
                        'base_max_difference_mm':float(delta.max()),
                        'base_changed_vertices':int((delta>.001).sum()),
                        'morph_differences':channels,
                        'scope':'same topology native 20018 vertices; not a photo similarity metric'}
    out = ROOT / 'data/gaussian/reconstruction-v9/asset-comparison.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps({k:{n:v for n,v in data.items() if n!='morph_differences'} for k,data in result.items()},indent=2))


if __name__ == '__main__': main()
