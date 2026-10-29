"""Installed outside the repo so the original notifier survives repo removal."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    config = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    payload = sys.argv[-1]
    # Preserve the desktop's existing completion notification, even for other repos.
    previous = config.get('previous_notify', [])
    if previous:
        try:
            subprocess.run([*previous, payload], timeout=30, capture_output=True)
        except (OSError, subprocess.TimeoutExpired):
            pass
    script = Path(config['repository']) / 'scripts' / 'finish_turn.py'
    if script.is_file():
        result = subprocess.run([config['python'], str(script), '--event', payload], timeout=600, capture_output=True)
        if result.returncode:
            sys.stderr.buffer.write(result.stdout + result.stderr)
        return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
