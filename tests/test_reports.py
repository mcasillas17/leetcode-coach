import unittest

from leetcode_coach.reports import build_report, render_markdown
from test_tracker import TrackerFixture


class ReportTests(TrackerFixture):
    def test_zero_logged_hints_does_not_establish_independent_solving(self):
        a = self.start()
        self.accepted(a)
        self.tracker.finish(a, 'accepted')
        self.assertEqual(build_report(self.tracker)['totals']['independent_solves'], 0)
        self.tracker.feedback(a, {'approach': 'User explained their own work'}, teach_back=True, independent=True)
        self.assertEqual(build_report(self.tracker)['totals']['independent_solves'], 1)

    def test_clock_invalid_finished_attempt_is_excluded_from_aggregate(self):
        a = self.start()
        self.clock.advance(10)
        self.tracker.finish(a, 'abandoned')
        # An inconsistent legacy/imported timestamp must never produce confirmed totals.
        self.tracker.db.execute('UPDATE attempts SET finished_at=started_at WHERE id=?', (a,))
        report = build_report(self.tracker)
        self.assertEqual(report['totals']['timing_excluded'], 1)

    def test_attempt_groups_separate_encounters_and_exclude_unconfirmed_timing(self):
        a = self.start()
        self.clock.advance(10)
        self.accepted(a)
        self.tracker.finish(a, 'accepted')
        self.tracker.feedback(a, {'mistakes': ['forgot-duplicates']}, teach_back=True, independent=True)
        b = self.start(review=True)
        self.clock.advance(999)
        self.tracker.recover(b)
        self.tracker.hint(b, 2, 'An invariant prompt')
        self.tracker.finish(b, 'unsolved')
        self.tracker.feedback(b, {'mistakes': ['forgot-duplicates']})
        report = build_report(self.tracker, 'encounter')
        self.assertEqual(report['totals']['attempts'], 2)
        self.assertEqual(report['totals']['accepted'], 1)
        self.assertEqual(report['totals']['verified_accepted'], 0)
        self.assertEqual(report['totals']['independent_solves'], 1)
        self.assertEqual(report['totals']['timing_samples'], 1)
        self.assertEqual(report['totals']['timing_excluded'], 1)
        self.assertEqual(report['totals']['active_seconds'], 10)
        self.assertEqual(report['groups']['first']['attempts'], 1)
        self.assertEqual(report['groups']['repeat']['hint_count'], 1)
        self.assertEqual(report['mistakes'], {'forgot-duplicates': 2})
        self.assertEqual(build_report(self.tracker, 'topic')['groups']['hash-table']['attempts'], 2)
        self.assertEqual(build_report(self.tracker, 'language')['groups']['python3']['attempts'], 2)
        self.assertEqual(build_report(self.tracker, 'assistance')['groups']['assisted']['attempts'], 1)

    def test_report_hides_active_tags_and_escapes_user_content(self):
        a = self.tracker.start('example', 10, 'A | B <script>alert(1)</script>', 'Easy', tags=['spoiler'])['id']
        report = build_report(self.tracker, 'topic')
        self.assertNotIn('spoiler', str(report))
        self.tracker.finish(a, 'abandoned')
        self.tracker.feedback(a, {'approach': '<img src=x onerror=alert(1)>', 'mistakes': []})
        md = render_markdown(build_report(self.tracker, 'difficulty'))
        self.assertNotIn('<script>', md)
        self.assertNotIn('<img', md)
        self.assertIn('A \\| B', md)
        self.assertIn('unverified', md.lower())

    def test_session_filter_and_empty_reports(self):
        self.assertEqual(build_report(self.tracker)['totals']['attempts'], 0)
        a = self.start()
        self.tracker.finish(a, 'abandoned')
        session = self.tracker.end_session('First practice')
        b = self.start()
        self.tracker.finish(b, 'unsolved')
        report = build_report(self.tracker, session_id=session['id'])
        self.assertEqual(len(report['attempts']), 1)
        self.assertEqual(report['sessions'][0]['summary'], 'First practice')
        self.assertIn('First practice', render_markdown(report))


if __name__ == '__main__':
    unittest.main()
