"""Exercise publication checks against a real disposable Git index/history."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/security-check.py', self.repo / 'scripts/security-check.py')
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', '123+fixture@users.noreply.github.com')

    def git(self, *args, env=None):
        return subprocess.run(['git', *args], cwd=self.repo, env=env,
                              check=True, capture_output=True)

    def check(self, mode):
        return subprocess.run(['python3', 'scripts/security-check.py', mode],
                              cwd=self.repo, capture_output=True, text=True)

    def test_staged_secret_is_blocked_even_when_working_copy_is_clean(self):
        token = 'ghp_' + 'A' * 40
        file = self.repo / 'config.json'
        file.write_text(json.dumps({'token': token}))
        self.git('add', 'config.json')
        file.write_text('{}')
        result = self.check('--staged')
        self.assertEqual(result.returncode, 1)
        self.assertIn('token GitHub', result.stdout)
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_personal_email_is_blocked_in_committer_even_if_author_is_noreply(self):
        (self.repo / 'README.md').write_text('Clean fixture')
        self.git('add', 'README.md')
        env = dict(os.environ, GIT_COMMITTER_EMAIL='fixture' + '@' + 'example.test')
        self.git('commit', '-q', '-m', 'Fixture', env=env)
        result = self.check('--history')
        self.assertEqual(result.returncode, 1)
        self.assertIn('autor o committer sin noreply', result.stdout)
        self.assertNotIn(env['GIT_COMMITTER_EMAIL'], result.stdout + result.stderr)

    def test_private_file_is_blocked_even_when_force_added(self):
        (self.repo / 'auth.json').write_text('{}')
        self.git('add', '-f', 'auth.json')
        result = self.check('--staged')
        self.assertEqual(result.returncode, 1)
        self.assertIn('archivo privado', result.stdout)

    def test_clean_noreply_history_is_allowed(self):
        (self.repo / 'README.md').write_text('Clean fixture')
        self.git('add', 'README.md')
        self.git('commit', '-q', '-m', 'Fixture')
        self.assertEqual(self.check('--history').returncode, 0)
