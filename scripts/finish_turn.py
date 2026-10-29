"""Commit and push this checkout; also usable by the Codex notify adapter."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def git(root, *args):
    result = subprocess.run(
        ['git', '-C', str(root), *args], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def finish(root, message):
    root = Path(root).resolve()
    actual = Path(git(root, 'rev-parse', '--show-toplevel')).resolve()
    if actual != root:
        raise RuntimeError('Expected the checkout root')
    gitdir = Path(git(root, 'rev-parse', '--absolute-git-dir'))
    lock = gitdir / 'codex-finish-turn.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f'Another finalizer is active, or a stale lock needs review: {lock}')
    try:
        os.close(fd)
        branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG'):
            if (gitdir / name).exists():
                raise RuntimeError(f'Unfinished Git operation: {name}')
        if git(root, 'ls-files', '--unmerged'):
            raise RuntimeError('Resolve conflicts before finishing')
        remote = git(root, 'config', '--get', f'branch.{branch}.remote')
        merge = git(root, 'config', '--get', f'branch.{branch}.merge')
        if remote != 'origin' or merge != f'refs/heads/{branch}':
            raise RuntimeError('Configure origin upstream with the same branch name first')
        if git(root, 'status', '--porcelain'):
            git(root, 'add', '-A')
            git(root, 'diff', '--cached', '--check')
            # Inspect staged blobs, including files that were already staged.
            paths = git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z')
            for path in filter(None, paths.split('\0')):
                if int(git(root, 'cat-file', '-s', ':' + path)) > 10 * 1024 * 1024:
                    raise RuntimeError(f'Large Git blob: {path}. Ignore generated output or configure Git LFS first.')
            if git(root, 'diff', '--cached', '--name-only'):
                git(root, 'commit', '-m', message)
        ahead = int(git(root, 'rev-list', '--count', '@{upstream}..HEAD'))
        if ahead:
            # Existing LFS pre-push hook runs normally. Never force, pull or rebase.
            git(root, 'push', 'origin', f'HEAD:refs/heads/{branch}')
        return {'status': 'ok', 'commit': git(root, 'rev-parse', '--short', 'HEAD'), 'pushed_commits': ahead}
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--message', default='chore: checkpoint completed Codex turn')
    parser.add_argument('--event', help='Codex notification JSON; only the matching checkout is handled')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.event:
        event = json.loads(args.event)
        if event.get('type') != 'agent-turn-complete' or not event.get('cwd'):
            return 0
        try:
            event_root = Path(git(event['cwd'], 'rev-parse', '--show-toplevel')).resolve()
        except (RuntimeError, OSError):
            return 0
        if event_root != root:
            return 0
    try:
        result = finish(root, args.message)
        code = 0
    except Exception as exc:
        result = {'status': 'error', 'error': str(exc)}
        code = 1
    result['time'] = datetime.now(timezone.utc).isoformat()
    result['trigger'] = 'notify' if args.event else 'manual'
    # Logs contain Git status only, never prompts or assistant messages.
    log = Path(git(root, 'rev-parse', '--absolute-git-dir')) / 'codex-finish-turn.jsonl'
    with log.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=True) + '\n')
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
