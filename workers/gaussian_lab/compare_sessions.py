"""Print comparable results from two or more local Gaussian Studio recordings."""
import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.gaussian_review import summary
from app.gaussian_store import checked_id


def peak(report, field):
    metric = report["sampled_ranges"].get(field)
    return "n/a" if metric is None else f"{metric['max']:.3f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="+", help="Session IDs from the studio's summary links")
    parser.add_argument("--data", type=Path, default=Path(os.getenv("GAUSSIAN_DATA_DIR", ROOT / "data/gaussian")))
    parser.add_argument("--json", action="store_true", help="Output full reports, including settings history")
    args = parser.parse_args()
    try:
        reports = [summary(args.data / "sessions" / checked_id(sid)) for sid in args.session]
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Could not read recording: {exc}\n")
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    for report in reports:
        print(f"{report['id']}  {report['mode'] or 'unrecorded'}  {report['controller']}  avatar {report['avatar_id']}")
        for tid, turn in report["turns"].items():
            print(f"  turn {tid}  expression={turn.get('plan', {}).get('emotion')}  "
                  f"WAV SHA256={turn.get('pcm_sha256', 'n/a')}  A2F frames={turn.get('animation_frames', 'n/a')}")
        print(f"  Samples {report['sample_stages']}  head driver {report['head_drivers']}  "
              f"peak applied pitch={peak(report, 'renderer_pitch_deg')} deg  "
              f"peak torso drift={peak(report, 'renderer_torso_drift_mm')} mm")
        print(f"  Nod decisions {report['nod_decisions']}  expression samples {report['sampled_face_states']}  "
              f"errors={report['events'].get('turn.error', 0) + report['events'].get('command.error', 0)}")


if __name__ == "__main__":
    main()
