"""Install a repository-scoped notification callback without losing existing notify."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib


root = Path(__file__).resolve().parents[1]
home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
config_path = home / 'config.toml'
source = config_path.read_text(encoding='utf-8')
config = tomllib.loads(source)
directory = home / 'repository-notifiers' / root.name
directory.mkdir(parents=True, exist_ok=True)
wrapper = directory / 'codex_notify.py'
settings = wrapper.with_suffix('.json')
python = sys._base_executable
command = [python, str(wrapper)]
previous = config.get('notify', [])
if previous == command:
    previous = json.loads(settings.read_text(encoding='utf-8'))['previous_notify']
settings.write_text(json.dumps({'repository': str(root), 'python': python, 'previous_notify': previous}, indent=2), encoding='utf-8')
shutil.copyfile(root / 'scripts' / 'codex_notify.py', wrapper)
line = 'notify = ' + json.dumps(command)
if 'notify' in config:
    # Refuse unfamiliar multiline syntax rather than rewriting unrelated config.
    pattern = r'^notify\s*=\s*\[[^\r\n]*\]\s*$'
    updated, count = re.subn(pattern, lambda _: line, source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError('Existing notify uses unsupported syntax; config was not changed')
else:
    updated = line + '\n' + source
parsed = tomllib.loads(updated)
expected = dict(config, notify=command)
if parsed != expected:
    raise RuntimeError('Unexpected config change; config was not changed')
backup = directory / 'config.before-notify.toml'
if not backup.exists():
    shutil.copyfile(config_path, backup)
config_path.write_text(updated, encoding='utf-8')
print(json.dumps({'installed': str(wrapper), 'backup': str(backup), 'repository': str(root)}))
