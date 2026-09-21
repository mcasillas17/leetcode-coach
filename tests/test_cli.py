import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, success=True):
        process = subprocess.run([sys.executable, '-m', 'leetcode_coach', '--root', str(self.root), '--json', *args],
                                 cwd=REPO, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0 if success else 2, process.stderr + process.stdout)
        return json.loads(process.stdout) if success else process

    def test_offline_interview_with_saved_source_and_user_reported_result(self):
        initialized = self.run_cli('init')
        self.assertEqual(initialized['config']['language'], 'python3')
        attempt = self.run_cli('start', 'two-sum', '--id', '1', '--title', 'Two Sum', '--difficulty', 'Easy')
        a = str(attempt['id'])
        (self.root / attempt['working_file']).write_text('class Solution:\n    pass\n')
        self.run_cli('phase', a, 'implementation')
        snapshot = self.run_cli('snapshot', a)
        snap = str(snapshot['id'])
        self.assertEqual(self.run_cli('show-snapshot', snap)['code'], 'class Solution:\n    pass\n')
        self.run_cli('pause', a, '--reason', 'judge')
        self.run_cli('judge', a, '--snapshot', snap, '--source', 'user-reported', '--verdict', 'accepted')
        self.run_cli('finish', a, '--outcome', 'accepted')
        feedback = self.root / 'feedback.json'
        feedback.write_text(json.dumps({'approach': 'Explain invariant', 'complexity': 'O(n)', 'mistakes': []}))
        self.run_cli('feedback', a, '--file', str(feedback), '--teach-back', '--independent')
        self.run_cli('end-session', '--summary', 'Completed practice')
        report = self.run_cli('report', '--group-by', 'difficulty')
        self.assertEqual(report['totals']['accepted'], 1)
        self.assertEqual(report['totals']['verified_accepted'], 0)
        self.assertEqual(report['totals']['independent_solves'], 1)
        self.assertTrue(self.run_cli('show', a)['teach_back'])
        destination = self.root / 'reports' / 'session.md'
        self.run_cli('report', '--output', str(destination))
        self.assertIn('Two Sum', destination.read_text())
        self.run_cli('report', '--output', str(destination), success=False)

    def test_help_invalid_arguments_and_config_are_actionable(self):
        output = self.run_cli('phase', '999', 'implementation', success=False)
        self.assertIn('Attempt not found', output.stderr)
        self.assertNotIn('Traceback', output.stderr)
        self.run_cli('init')
        (self.root / 'coach.local.json').write_text('{invalid json')
        result = self.run_cli('start', 'x', '--id', '1', '--title', 'X', '--difficulty', 'Easy', success=False)
        self.assertIn('config', result.stderr.lower())

    def test_malformed_config_types_return_errors_without_tracebacks(self):
        for value in ([], {}, True, None, 1):
            with self.subTest(value=value):
                (self.root / 'coach.json').write_text(json.dumps({'language': value}))
                result = self.run_cli('status', success=False)
                self.assertIn('Config language', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_configured_language_and_path_are_respected_without_overwriting(self):
        self.run_cli('init')
        (self.root / 'coach.local.json').write_text(json.dumps({'language': 'typescript', 'mode': 'guided'}))
        working = self.root / 'workspace' / 'leetcode' / '1.two-sum.ts'
        working.parent.mkdir(parents=True)
        working.write_text('// Existing work')
        result = self.run_cli('start', 'two-sum', '--id', '1', '--title', 'Two Sum', '--difficulty', 'Easy',
                              '--file', 'workspace/leetcode/1.two-sum.ts')
        self.assertEqual(result['language'], 'typescript')
        self.assertEqual(result['mode'], 'guided')
        self.assertEqual(working.read_text(), '// Existing work')

    def test_restore_cli_does_not_initialize_target_first(self):
        self.run_cli('init')
        backup = self.root / 'backup.sqlite3'
        self.run_cli('backup', str(backup))
        destination = self.root / 'new-root'
        result = subprocess.run([sys.executable, '-m', 'leetcode_coach', '--root', str(destination), '--json', 'restore', str(backup)],
                                cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((destination / '.coach' / 'progress.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
