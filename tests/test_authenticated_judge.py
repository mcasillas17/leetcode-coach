import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from leetcode_coach.tracker import Tracker


@unittest.skipUnless(importlib.util.find_spec('httpx2'), 'Optional MCP dependencies are not installed')
class AuthenticatedJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from leetcode_coach.judge import JudgeService
        from leetcode_coach.credentials import Credentials
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        with Tracker(self.root) as tracker:
            attempt = tracker.start('two-sum', 1, 'Two Sum', 'Easy')
            self.path = self.root / attempt['working_file']
            self.path.write_text('class Solution:\n    pass\n')
            self.snapshot = tracker.snapshot(1)['id']
        self.service = JudgeService(self.root)
        self.credentials = Credentials('fixture-session-not-a-real-secret', 'fixture-csrf-not-a-real-secret')
        self.auth = patch('leetcode_coach.judge.load_credentials', return_value=self.credentials)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.sent = []
        self.polls = [{'state': 'SUCCESS', 'status_code': 10, 'status_msg': 'Accepted',
                       'submission_id': 987, 'status_runtime': '3 ms', 'status_memory': '16.25 MB',
                       'total_correct': 10, 'total_testcases': 10}]
        self.start_error = None
        self.identity = {'questionId': '42', 'questionFrontendId': '1', 'titleSlug': 'two-sum',
                         'codeSnippets': [{'langSlug': 'python3'}]}

        async def respond(transport, request):
            import httpx2
            self.assertEqual(request.url.host, 'leetcode.com')
            self.assertEqual(request.url.scheme, 'https')
            self.assertEqual(type(transport._pool).__name__, 'AsyncConnectionPool')
            payload = json.loads(request.content) if request.content else None
            self.sent.append((request, payload))
            if request.url.path == '/graphql/':
                self.assertNotIn('cookie', request.headers)
                result = {'data': {'question': self.identity}}
            else:
                self.assertEqual(request.headers['cookie'],
                                 'LEETCODE_SESSION=fixture-session-not-a-real-secret; csrftoken=fixture-csrf-not-a-real-secret')
                self.assertEqual(request.headers['x-csrftoken'], self.credentials.csrf)
                if request.method == 'POST':
                    if self.start_error:
                        raise self.start_error
                    result = {'interpret_id': 'runcode_fixture'} if 'interpret_solution' in request.url.path else {'submission_id': 987}
                else:
                    result = self.polls.pop(0)
            return httpx2.Response(200, stream=httpx2.ByteStream(json.dumps(result).encode()))
        transport = patch('httpx2.AsyncHTTPTransport.handle_async_request', respond)
        transport.start()
        self.addCleanup(transport.stop)

    async def test_submits_exact_snapshot_and_internal_id_pauses_and_records_verified_result(self):
        self.path.write_text('changed after snapshot; must not send')
        operation = await self.service.start(1, self.snapshot, 'submission')
        self.assertEqual(operation['state'], 'pending')
        body = self.sent[-1][1]
        self.assertEqual(body['question_id'], '42')
        self.assertEqual(body['typed_code'], 'class Solution:\n    pass\n')
        with Tracker(self.root) as tracker:
            self.assertEqual(tracker.attempt(1)['state'], 'paused')
        result = await self.service.status(operation['operation_id'])
        self.assertEqual(result['verdict'], 'accepted')
        self.assertEqual(result['runtime_ms'], 3)
        self.assertEqual(result['memory_mb'], 16.25)
        with Tracker(self.root) as tracker:
            attempt = tracker.attempt(1)
            self.assertTrue(attempt['acceptance']['verified'])
            self.assertEqual(attempt['judge_results'][0]['snapshot_id'], self.snapshot)
            self.assertEqual(attempt['state'], 'paused')
        repeated = await self.service.status(operation['operation_id'])
        self.assertEqual(repeated, result)

    async def test_test_pass_does_not_establish_submission_acceptance(self):
        self.polls[0]['submission_id'] = 'runcode_fixture'
        operation = await self.service.start(1, self.snapshot, 'test', '[2,7,11,15]\n9')
        self.assertEqual(self.sent[-1][1]['data_input'], '[2,7,11,15]\n9')
        await self.service.status(operation['operation_id'])
        with Tracker(self.root) as tracker:
            self.assertFalse(tracker.attempt(1)['acceptance']['accepted'])
            self.assertEqual(tracker.attempt(1)['judge_results'][0]['kind'], 'test')

    async def test_lost_response_is_persisted_and_never_reposts_on_retry_or_restart(self):
        import httpx2
        from leetcode_coach.judge import JudgeService
        self.start_error = httpx2.ReadTimeout('fixture-session-not-a-real-secret')
        first = await self.service.start(1, self.snapshot, 'submission')
        self.assertEqual(first['state'], 'unknown')
        for service in (self.service, JudgeService(self.root)):
            repeated = await service.start(1, self.snapshot, 'submission')
            self.assertEqual(first['operation_id'], repeated['operation_id'])
            await service.status(first['operation_id'])
        self.assertEqual(sum(r.method == 'POST' and r.url.path.endswith('/submit/') for r, _ in self.sent), 1)
        self.assertNotIn(self.credentials.session, json.dumps(first))
        self.assertNotIn(self.credentials.session.encode(), (self.root / '.coach/progress.sqlite3').read_bytes())

    async def test_concurrent_repeated_request_only_posts_once(self):
        a, b = await asyncio.gather(self.service.start(1, self.snapshot, 'submission'),
                                    self.service.start(1, self.snapshot, 'submission'))
        self.assertEqual(a['operation_id'], b['operation_id'])
        self.assertEqual(sum(r.url.path.endswith('/submit/') for r, _ in self.sent), 1)

    async def test_pending_status_and_unrecognized_verdict_do_not_claim_acceptance(self):
        self.polls = [{'state': 'PENDING'}, {'state': 'SUCCESS', 'status_code': 999, 'status_msg': 'Surprise'}]
        operation = await self.service.start(1, self.snapshot, 'submission')
        pending = await self.service.status(operation['operation_id'])
        self.assertEqual(pending['state'], 'pending')
        result = await self.service.status(operation['operation_id'])
        self.assertEqual(result['verdict'], 'unknown')
        with Tracker(self.root) as tracker:
            self.assertFalse(tracker.attempt(1)['acceptance']['accepted'])

    async def test_missing_credentials_and_wrong_problem_identity_do_not_pause_or_send(self):
        from leetcode_coach.credentials import CredentialError
        from leetcode_coach.judge import JudgeError
        with patch('leetcode_coach.judge.load_credentials', side_effect=CredentialError('Run local login')):
            with self.assertRaises(CredentialError):
                await self.service.start(1, self.snapshot, 'submission')
        self.identity['questionFrontendId'] = '2'
        with self.assertRaises(JudgeError):
            await self.service.start(1, self.snapshot, 'submission')
        with Tracker(self.root) as tracker:
            self.assertEqual(tracker.attempt(1)['state'], 'running')
        self.assertFalse(any(r.url.path.endswith('/submit/') for r, _ in self.sent))

    async def test_status_cannot_read_arbitrary_remote_id_or_accept_mismatched_response(self):
        from leetcode_coach.judge import JudgeError
        with self.assertRaises(JudgeError):
            await self.service.status('987')
        operation = await self.service.start(1, self.snapshot, 'submission')
        self.polls[0]['submission_id'] = '999'
        with self.assertRaises(JudgeError):
            await self.service.status(operation['operation_id'])
        with Tracker(self.root) as tracker:
            self.assertFalse(tracker.attempt(1)['acceptance']['accepted'])

    async def test_concurrent_stale_poll_cannot_replace_completed_acceptance(self):
        operation = await self.service.start(1, self.snapshot, 'submission')
        accepted = self.polls[0]
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0
        async def check(*args):
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                await release.wait()
                return {'state': 'SUCCESS', 'status_code': 999, 'status_msg': 'Surprise'}
            return accepted
        with patch.object(self.service.api, 'check', check):
            stale = asyncio.create_task(self.service.status(operation['operation_id']))
            await entered.wait()
            result = await self.service.status(operation['operation_id'])
            release.set()
            late = await stale
        self.assertEqual(result['verdict'], 'accepted')
        self.assertEqual(late['verdict'], 'accepted')
        self.assertEqual((await self.service.status(operation['operation_id']))['verdict'], 'accepted')

    async def test_unknown_terminal_result_can_be_reconciled_by_later_poll(self):
        accepted = self.polls[0]
        self.polls = [{'state': 'SUCCESS', 'status_code': 999, 'status_msg': 'Surprise'}, accepted]
        operation = await self.service.start(1, self.snapshot, 'submission')
        self.assertEqual((await self.service.status(operation['operation_id']))['verdict'], 'unknown')
        self.assertEqual((await self.service.status(operation['operation_id']))['verdict'], 'accepted')

    async def test_malformed_or_contradictory_acceptance_stays_unknown(self):
        from leetcode_coach.leetcode_judge import normalize_result
        accepted = self.polls[0]
        for change in [
            {'total_correct': '0'}, {'total_correct': -1, 'total_testcases': -1},
            {'total_testcases': None}, {'total_correct': True}, {'run_success': False},
            {'runtime_error': 'fixture failure'}, {'compile_error': 'fixture failure'},
            {'status_msg': []}, {'status_code': True},
        ]:
            with self.subTest(change=change):
                self.assertEqual(normalize_result({**accepted, **change}, self.credentials)['verdict'], 'unknown')

    async def test_authenticated_transport_rejects_redirects_and_hides_upstream_errors(self):
        import httpx2
        from leetcode_coach.leetcode_judge import JudgeError
        for status, headers, body in [
            (302, {'location': 'https://example.org/collect'}, b''),
            (403, {}, self.credentials.session.encode()),
            (200, {}, json.dumps({'error': self.credentials.session}).encode()),
            (200, {}, b'{invalid-json'),
            (200, {'content-encoding': 'gzip'}, b'compressed'),
            (200, {}, b' ' * 1_000_001),
        ]:
            calls = []
            async def respond(transport, request):
                calls.append(request)
                return httpx2.Response(status, headers=headers, stream=httpx2.ByteStream(body))
            with self.subTest(status=status, headers=headers, size=len(body)), \
                    patch('httpx2.AsyncHTTPTransport.handle_async_request', respond):
                with self.assertRaises(JudgeError) as error:
                    await self.service.api.check('987', 'submission', 'two-sum', self.credentials)
                self.assertEqual(len(calls), 1)
                self.assertNotIn(self.credentials.session, str(error.exception))

    async def test_result_evidence_and_operation_commit_atomically(self):
        operation = await self.service.start(1, self.snapshot, 'submission')
        accepted = self.polls[0]
        original = Tracker.event
        def failing_event(tracker, attempt_id, kind, data, *args):
            if kind == 'remote_judge':
                raise OSError('simulated storage interruption')
            return original(tracker, attempt_id, kind, data, *args)
        with patch.object(Tracker, 'event', failing_event):
            with self.assertRaises(OSError):
                await self.service.status(operation['operation_id'])
        with Tracker(self.root) as tracker:
            self.assertEqual(tracker.attempt(1)['judge_results'], [])
        self.polls.append(accepted)
        self.assertEqual((await self.service.status(operation['operation_id']))['verdict'], 'accepted')

    async def test_diagnostics_redact_credentials_and_cap_returned_text(self):
        from leetcode_coach.leetcode_judge import normalize_result
        result = normalize_result({**self.polls[0], 'std_output': self.credentials.session + self.credentials.csrf + 'x' * 8000},
                                  self.credentials)
        output = result['diagnostics']['std_output']
        self.assertEqual(len(output), 4000)
        self.assertNotIn(self.credentials.session, output)
        self.assertNotIn(self.credentials.csrf, output)

    async def test_registered_mcp_tools_submit_poll_and_enforce_input_types(self):
        from leetcode_coach.mcp_server import create_server
        from mcp.server.mcpserver.exceptions import ToolError
        server = create_server(self.root)
        with self.assertRaises(ToolError):
            await server.call_tool('submit_solution', {'attempt_id': True, 'snapshot_id': self.snapshot})
        self.assertEqual(self.sent, [])
        started = await server.call_tool('submit_solution', {'attempt_id': 1, 'snapshot_id': self.snapshot})
        self.assertFalse(started.is_error)
        operation = started.structured_content
        result = await server.call_tool('get_submission_status', {'operation_id': operation['operation_id']})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content['verdict'], 'accepted')
        with Tracker(self.root) as tracker:
            self.assertTrue(tracker.attempt(1)['acceptance']['verified'])
