import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('finish_turn', Path(__file__).with_name('finish_turn.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FinishTurnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.remote = base / 'remote.git'
        self.repo = base / 'checkout'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'init', '-b', 'main', str(self.repo)], check=True, capture_output=True)
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / '.gitignore').write_text('artifacts/\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-u', 'origin', 'main')

    def git(self, *args):
        return module.git(self.repo, *args)

    def test_commit_push_ignore_and_noop(self):
        (self.repo / 'source.txt').write_text('hello\n')
        (self.repo / 'artifacts').mkdir()
        (self.repo / 'artifacts' / 'replay.jpg').write_bytes(b'local')
        result = module.finish(self.repo, 'test change')
        self.assertEqual(result['pushed_commits'], 1)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))
        self.assertNotIn('replay.jpg', self.git('ls-files'))
        self.assertTrue((self.repo / 'artifacts' / 'replay.jpg').exists())
        self.assertEqual(module.finish(self.repo, 'noop')['pushed_commits'], 0)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD'), '2')

    def test_failed_push_keeps_commit_then_retries(self):
        self.git('remote', 'set-url', 'origin', str(self.repo / 'missing.git'))
        (self.repo / 'source.txt').write_text('retained\n')
        with self.assertRaises(RuntimeError):
            module.finish(self.repo, 'retained')
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'retained')
        self.git('remote', 'set-url', 'origin', str(self.remote))
        self.assertEqual(module.finish(self.repo, 'retry')['pushed_commits'], 1)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD'), '2')

    def test_detached_head_refused(self):
        self.git('checkout', '--detach')
        with self.assertRaises(RuntimeError):
            module.finish(self.repo, 'no')

    def test_remote_divergence_does_not_overwrite(self):
        other = Path(self.temp.name) / 'other'
        subprocess.run(['git', 'clone', '-b', 'main', str(self.remote), str(other)], check=True, capture_output=True)
        module.git(other, 'config', 'user.email', 'test@example.invalid')
        module.git(other, 'config', 'user.name', 'Test')
        (other / 'remote.txt').write_text('remote work\n')
        module.git(other, 'add', '.')
        module.git(other, 'commit', '-m', 'remote work')
        module.git(other, 'push')
        remote_head = module.git(other, 'rev-parse', 'HEAD')
        (self.repo / 'local.txt').write_text('local work\n')
        with self.assertRaises(RuntimeError):
            module.finish(self.repo, 'local work')
        self.assertEqual(module.git(self.remote, 'rev-parse', 'main'), remote_head)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'local work')

    def test_other_checkout_notification_is_ignored(self):
        import json
        import sys
        result = subprocess.run([sys.executable, str(Path(module.__file__)), '--event',
                                 json.dumps({'type': 'agent-turn-complete', 'cwd': str(self.repo)})],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / '.git' / 'codex-finish-turn.jsonl').exists())

    def test_lock_refused(self):
        (self.repo / '.git' / 'codex-finish-turn.lock').touch()
        with self.assertRaises(RuntimeError):
            module.finish(self.repo, 'no')

    def test_large_blob_refused(self):
        (self.repo / 'generated.bin').write_bytes(b'x' * (10 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, 'Large Git blob'):
            module.finish(self.repo, 'no')
        self.assertEqual(self.git('rev-list', '--count', 'HEAD'), '1')


if __name__ == '__main__':
    unittest.main()
