import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leetcode_coach.tracker import CoachError, Tracker


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class TrackerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.tracker = Tracker(self.root, clock=self.clock)

    def tearDown(self):
        self.tracker.close()
        self.temp.cleanup()

    def start(self, **kwargs):
        return self.tracker.start('two-sum', 1, 'Two Sum', 'Easy', tags=['array', 'hash-table'], **kwargs)['id']

    def source(self, attempt_id, text='class Solution:\n    pass\n'):
        path = self.root / self.tracker.attempt(attempt_id)['working_file']
        path.write_text(text)
        return path

    def accepted(self, attempt_id, source='user-reported'):
        self.source(attempt_id)
        snap = self.tracker.snapshot(attempt_id)
        return self.tracker.judge(attempt_id, snap['id'], source, 'accepted', kind='submission', submission_id='123' if source == 'mcp' else None)


class TrackerTests(TrackerFixture):
    def test_recorded_help_prevents_independence_confirmation(self):
        a = self.start()
        self.tracker.hint(a, 5, 'User reports using an outside solution')
        self.accepted(a)
        self.tracker.finish(a, 'accepted')
        with self.assertRaises(CoachError):
            self.tracker.feedback(a, {'approach': 'Copied solution'}, teach_back=True, independent=True)

    def test_paused_finish_rejects_clock_rollback_without_mutation(self):
        a = self.start()
        self.clock.advance(10)
        self.tracker.pause(a)
        self.clock.advance(-5)
        with self.assertRaisesRegex(CoachError, 'Clock'):
            self.tracker.finish(a, 'abandoned')
        self.assertEqual(self.tracker.attempt(a)['state'], 'paused')

    def test_conflicting_terminal_judge_verdicts_cannot_manufacture_acceptance(self):
        a = self.start()
        self.source(a)
        snap = self.tracker.snapshot(a)
        self.tracker.judge(a, snap['id'], 'mcp', 'wrong-answer', submission_id='123')
        with self.assertRaisesRegex(CoachError, 'Conflicting'):
            self.tracker.judge(a, snap['id'], 'mcp', 'accepted', submission_id='123')
        self.assertFalse(self.tracker.attempt(a)['acceptance']['verified'])

    def test_phase_timing_pauses_judge_wait_and_repeated_finish(self):
        a = self.start()
        self.clock.advance(60)
        self.tracker.phase(a, 'implementation')
        self.clock.advance(120)
        self.tracker.pause(a, 'break')
        self.clock.advance(900)
        self.tracker.resume(a)
        self.clock.advance(30)
        self.tracker.phase(a, 'debugging')
        self.clock.advance(10)
        self.tracker.pause(a, 'judge')
        self.clock.advance(20)
        first = self.tracker.finish(a, 'abandoned')
        self.clock.advance(60)
        self.assertEqual(self.tracker.finish(a, 'abandoned'), first)
        timing = first['timing']
        self.assertEqual(timing['phase_seconds'], {'reasoning': 60, 'implementation': 150, 'debugging': 10})
        self.assertEqual(timing['active_seconds'], 220)
        self.assertEqual(timing['wall_seconds'], 1140)
        self.assertEqual(first['review_date'], '2026-09-21')
        self.assertEqual(len(self.tracker.status()['attempts']), 1)

    def test_recovery_excludes_unconfirmed_time_and_preserves_correction_history(self):
        a = self.start()
        self.clock.advance(5400)
        self.tracker.close()
        self.tracker = Tracker(self.root, clock=self.clock)
        recovered = self.tracker.recover(a)
        self.assertEqual(recovered['state'], 'paused')
        self.assertFalse(recovered['timing']['confirmed'])
        interval_id = recovered['intervals'][0]['id']
        self.tracker.correct_interval(a, interval_id, 1800, 'User reports one-hour lunch')
        self.tracker.confirm_timing(a)
        result = self.tracker.finish(a, 'abandoned')
        interval = result['intervals'][0]
        self.assertEqual(interval['original_seconds'], 5400)
        self.assertEqual(interval['seconds'], 1800)
        self.assertTrue(result['timing']['confirmed'])
        self.assertIn('correction', [e['kind'] for e in result['events']])

    def test_paused_restart_preserves_time(self):
        a = self.start()
        self.clock.advance(11)
        self.tracker.pause(a)
        self.tracker.close()
        self.clock.advance(200)
        self.tracker = Tracker(self.root, clock=self.clock)
        self.tracker.resume(a)
        self.clock.advance(9)
        self.assertEqual(self.tracker.finish(a, 'abandoned')['timing']['active_seconds'], 20)

    def test_clock_rollback_requires_recovery_and_explicit_correction(self):
        a = self.start()
        self.clock.advance(-5)
        with self.assertRaisesRegex(CoachError, 'Clock'):
            self.tracker.phase(a, 'implementation')
        recovered = self.tracker.recover(a)
        self.assertIsNone(recovered['timing']['active_seconds'])
        with self.assertRaises(CoachError):
            self.tracker.confirm_timing(a)
        self.tracker.correct_interval(a, recovered['intervals'][0]['id'], 0, 'Clock corrected by user')
        self.clock.advance(5)
        self.tracker.confirm_timing(a)
        self.assertEqual(self.tracker.finish(a, 'abandoned')['timing']['active_seconds'], 0)

    def test_invalid_transitions_are_atomic_and_one_attempt_can_be_open(self):
        a = self.start()
        before = self.tracker.attempt(a)
        with self.assertRaises(CoachError):
            self.start()
        with self.assertRaises(CoachError):
            self.tracker.resume(a)
        self.assertEqual(self.tracker.attempt(a), before)
        self.tracker.pause(a)
        with self.assertRaises(CoachError):
            self.tracker.phase(a, 'debugging')
        self.tracker.finish(a, 'abandoned')
        with self.assertRaises(CoachError):
            self.tracker.resume(a)

    def test_two_writers_cannot_start_two_attempts(self):
        def run(_):
            with Tracker(self.root, clock=self.clock) as tracker:
                try:
                    return tracker.start('two-sum', 1, 'Two Sum', 'Easy')['id']
                except CoachError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_snapshot_bytes_are_immutable_and_judge_result_is_deduplicated(self):
        a = self.start()
        path = self.source(a, 'print("original")\n')
        snapshot = self.tracker.snapshot(a)
        path.write_text('print("later edit")\n')
        original = self.tracker.snapshot_content(snapshot['id'])
        self.assertEqual(original, b'print("original")\n')
        self.assertEqual(snapshot['sha256'], hashlib.sha256(original).hexdigest())
        kwargs = dict(kind='submission', submission_id='456', runtime_ms=3.5, memory_mb=16)
        first = self.tracker.judge(a, snapshot['id'], 'mcp', 'accepted', **kwargs)
        second = self.tracker.judge(a, snapshot['id'], 'mcp', 'accepted', **kwargs)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.tracker.attempt(a)['judge_results']), 1)
        self.assertTrue(self.tracker.attempt(a)['acceptance']['verified'])

    def test_local_test_pass_cannot_claim_acceptance(self):
        a = self.start()
        self.source(a)
        snapshot = self.tracker.snapshot(a)
        self.tracker.judge(a, snapshot['id'], 'local-test', 'accepted', kind='test')
        with self.assertRaisesRegex(CoachError, 'submission'):
            self.tracker.finish(a, 'accepted')
        with self.assertRaises(CoachError):
            self.tracker.judge(a, snapshot['id'], 'local-test', 'accepted', kind='submission')
        with self.assertRaises(CoachError):
            self.tracker.judge(a, snapshot['id'], 'mcp', 'accepted', kind='submission')
        self.assertEqual(self.tracker.attempt(a)['state'], 'running')

    def test_timeout_is_unknown_and_later_reconciliation_preserves_both_events(self):
        a = self.start()
        self.source(a)
        snap = self.tracker.snapshot(a)
        self.tracker.judge(a, snap['id'], 'mcp', 'unknown', kind='submission', submission_id='789')
        self.assertFalse(self.tracker.attempt(a)['acceptance']['accepted'])
        self.tracker.judge(a, snap['id'], 'mcp', 'accepted', kind='submission', submission_id='789')
        results = self.tracker.attempt(a)['judge_results']
        self.assertEqual([r['verdict'] for r in results], ['unknown', 'accepted'])

    def test_teach_back_and_assistance_drive_review_without_erasing_prior_attempt(self):
        a = self.start()
        self.accepted(a)
        self.tracker.finish(a, 'accepted')
        self.assertEqual(self.tracker.attempt(a)['review_date'], '2026-09-21')
        feedback = {'approach': 'Remember complements', 'complexity': 'O(n) time, O(n) space',
                    'correctness': 'Invariant explained', 'optimizations': 'One pass',
                    'testing': 'Duplicates covered', 'communication': 'Clear',
                    'mistakes': ['duplicate-handling'], 'next_exercise': 'Repeat independently'}
        self.tracker.feedback(a, feedback, teach_back=True, independent=True)
        self.assertEqual(self.tracker.attempt(a)['review_date'], '2026-09-27')
        self.clock.advance(86400)
        b = self.start(review=True)
        self.accepted(b)
        self.tracker.finish(b, 'accepted')
        self.tracker.feedback(b, feedback, teach_back=True, independent=True)
        self.assertEqual(self.tracker.attempt(b)['review_date'], '2026-10-21')
        self.assertEqual(len(self.tracker.status()['attempts']), 2)
        self.assertEqual(len(self.tracker.status()['due_reviews']), 0)
        self.assertFalse(self.tracker.attempt(a)['acceptance']['verified'])

    def test_hint_levels_and_review_override(self):
        a = self.start()
        for level in (1, 3, 5):
            self.tracker.hint(a, level, 'Requested help')
        self.accepted(a)
        self.tracker.finish(a, 'accepted')
        self.tracker.feedback(a, {'mistakes': []}, teach_back=True, review_date='2026-10-01')
        result = self.tracker.attempt(a)
        self.assertEqual(result['hint_level'], 5)
        self.assertEqual(result['hint_count'], 3)
        self.assertFalse(result['independent'])
        self.assertEqual(result['review_date'], '2026-10-01')

    def test_metadata_hidden_until_debrief_and_input_validation(self):
        a = self.start()
        self.assertNotIn('tags', self.tracker.attempt(a)['problem'])
        self.tracker.finish(a, 'abandoned')
        self.assertEqual(self.tracker.attempt(a)['problem']['tags'], ['array', 'hash-table'])
        for slug in ('../escape', '', '/absolute'):
            with self.assertRaises(CoachError):
                self.tracker.start(slug, 2, 'Example', 'Easy')
        for level in (-1, 6, True):
            with self.assertRaises(CoachError):
                self.tracker.hint(a, level, 'help')

    def test_snapshot_rejects_symlink_escape_and_missing_file(self):
        a = self.start()
        path = self.root / self.tracker.attempt(a)['working_file']
        path.unlink()
        with self.assertRaises(CoachError):
            self.tracker.snapshot(a)
        external = self.root / 'outside.py'
        external.write_text('secret')
        path.symlink_to(external)
        with self.assertRaisesRegex(CoachError, 'workspace'):
            self.tracker.snapshot(a)

    def test_backup_restore_preserves_history_without_overwriting(self):
        a = self.start()
        self.source(a)
        snap = self.tracker.snapshot(a)
        self.clock.advance(12)
        self.tracker.finish(a, 'abandoned')
        backup = self.root / 'backups' / 'practice.sqlite3'
        self.tracker.backup(backup)
        with self.assertRaises(CoachError):
            self.tracker.backup(backup)
        target = self.root / 'restored'
        Tracker.restore(target, backup)
        with Tracker(target, clock=self.clock) as restored:
            self.assertEqual(restored.attempt(a), self.tracker.attempt(a))
            self.assertEqual(restored.snapshot_content(snap['id']), self.tracker.snapshot_content(snap['id']))
        with self.assertRaises(CoachError):
            Tracker.restore(target, backup)

    def test_invalid_feedback_and_unknown_schema_do_not_mutate_data(self):
        a = self.start()
        with self.assertRaises(CoachError):
            self.tracker.feedback(a, {'unexpected': 'field'})
        with self.assertRaises(CoachError):
            self.tracker.correct_interval(a, 1, -5, 'invalid')
        self.tracker.close()
        db = self.root / '.coach' / 'progress.sqlite3'
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(CoachError, 'schema'):
            Tracker(self.root, clock=self.clock)


if __name__ == '__main__':
    unittest.main()
