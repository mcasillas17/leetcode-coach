"""Exercise the MCP tool contract against real temporary tracker storage."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys

if importlib.util.find_spec('mcp'):
    from leetcode_coach.mcp_server import create_server


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Optional MCP dependencies are not installed')
class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.server = create_server(self.root)

    async def call(self, name, **arguments):
        result = await self.server.call_tool(name, arguments)
        self.assertFalse(result.is_error)
        return result.structured_content

    async def start(self):
        return await self.call('start_attempt', slug='two-sum', frontend_id=1, title='Two Sum', difficulty='Easy')

    async def test_full_practice_flow_retains_unverified_judge_provenance(self):
        attempt = await self.start()
        self.assertEqual(attempt['state'], 'running')
        self.assertEqual(attempt['phase'], 'reasoning')
        attempt = await self.call('change_phase', attempt_id=1, phase='implementation')
        path = self.root / attempt['working_file']
        path.write_text('print("test fixture; never execute")\n')
        snapshot = await self.call('snapshot_solution', attempt_id=1)
        frozen = await self.call('get_snapshot', snapshot_id=snapshot['id'])
        self.assertEqual(frozen['code'], path.read_text())
        await self.call('pause_attempt', attempt_id=1, reason='judge')
        result = await self.call('record_judge_result', attempt_id=1, snapshot_id=snapshot['id'],
                                 verdict='accepted', source='mcp')
        self.assertEqual(result['source'], 'user-reported')
        attempt = await self.call('finish_attempt', attempt_id=1, outcome='accepted')
        self.assertFalse(attempt['acceptance']['verified'])
        await self.call('save_feedback', attempt_id=1, feedback={'complexity': 'O(n) time'},
                        teach_back=True, independent=True)
        await self.call('end_session', summary='Finished practice')
        report = await self.call('get_progress', group_by='difficulty')
        self.assertEqual(report['totals']['accepted'], 1)
        self.assertEqual(report['totals']['verified_accepted'], 0)
        self.assertEqual(report['totals']['independent_solves'], 1)

    async def test_recovery_assistance_and_corrections_use_existing_invariants(self):
        await self.start()
        recovered = await self.call('recover_attempt', attempt_id=1)
        self.assertFalse(recovered['timing']['confirmed'])
        interval = recovered['intervals'][0]['id']
        await self.call('correct_timing', attempt_id=1, interval_id=interval, seconds=120, reason='User confirmed')
        await self.call('confirm_timing', attempt_id=1)
        await self.call('resume_attempt', attempt_id=1)
        await self.call('record_hint', attempt_id=1, level=1, note='Asked about duplicates')
        attempt = await self.call('get_attempt', attempt_id=1)
        self.assertEqual(attempt['hint_count'], 1)
        await self.call('finish_attempt', attempt_id=1, outcome='unsolved')
        state = await self.call('get_status')
        self.assertIsNone(state['active'])
        self.assertEqual(len(state['attempts']), 1)

    async def test_tools_cannot_escape_workspace_claim_verified_evidence_or_execute(self):
        from mcp.server.mcpserver.exceptions import ToolError
        tools = {tool.name: tool for tool in await self.server.list_tools()}
        for forbidden in ('execute', 'read_file', 'restore', 'get_problem_solution'):
            self.assertNotIn(forbidden, tools)
        for schema in (tools['start_attempt'].input_schema, tools['record_judge_result'].input_schema):
            self.assertNotIn('root', schema.get('properties', {}))
            self.assertNotIn('working_file', schema.get('properties', {}))
            self.assertNotIn('source', schema.get('properties', {}))
        self.assertTrue(tools['get_problem'].annotations.read_only_hint)
        self.assertFalse(tools['start_attempt'].annotations.read_only_hint)
        for name in ('run_code', 'submit_solution', 'get_submission_status'):
            self.assertIn(name, tools)
            self.assertFalse(tools[name].annotations.read_only_hint)
        self.assertTrue(tools['submit_solution'].annotations.destructive_hint)
        for name in ('run_code', 'submit_solution'):
            self.assertNotIn('code', tools[name].input_schema.get('properties', {}))
            self.assertNotIn('credentials', tools[name].input_schema.get('properties', {}))
        with self.assertRaises(ToolError):
            await self.call('start_attempt', slug='../escape', frontend_id=1, title='X', difficulty='Easy')
        await self.start()
        with self.assertRaises(ToolError):
            await self.call('finish_attempt', attempt_id=1, outcome='accepted')
        outside = self.root / 'outside.txt'
        outside.write_text('private')
        state = await self.call('get_attempt', attempt_id=1)
        path = self.root / state['working_file']
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ToolError):
            await self.call('snapshot_solution', attempt_id=1)

    async def test_registered_public_tools_use_sanitized_results(self):
        import json
        import httpx2
        from unittest.mock import patch
        from test_leetcode_public import QUESTION
        async def response(transport, request):
            return httpx2.Response(200, stream=httpx2.ByteStream(json.dumps({'data': {'question': QUESTION}}).encode()))
        with patch('httpx2.AsyncHTTPTransport.handle_async_request', response):
            problem = await self.call('get_problem', titleSlug='two-sum')
        self.assertEqual(problem['frontend_id'], 1)
        self.assertNotIn('hints', problem)

    async def test_boolean_and_numeric_coercions_cannot_record_confirmations(self):
        from mcp.server.mcpserver.exceptions import ToolError
        with self.assertRaises(ToolError):
            await self.call('start_attempt', slug='two-sum', frontend_id=True, title='Two Sum', difficulty='Easy')
        self.assertEqual((await self.call('get_status'))['attempts'], [])
        await self.start()
        for name, arguments in [('get_attempt', {'attempt_id': True}),
                                ('record_hint', {'attempt_id': 1, 'level': True, 'note': 'X'}),
                                ('correct_timing', {'attempt_id': 1, 'interval_id': 1, 'seconds': True, 'reason': 'X'})]:
            with self.assertRaises(ToolError):
                await self.call(name, **arguments)
        await self.call('finish_attempt', attempt_id=1, outcome='unsolved')
        for confirmation in ({'independent': 'true'}, {'teach_back': 1}):
            with self.assertRaises(ToolError):
                await self.call('save_feedback', attempt_id=1, feedback={'approach': 'X'}, **confirmation)
        attempt = await self.call('get_attempt', attempt_id=1)
        self.assertFalse(attempt['independent'])
        self.assertFalse(attempt['teach_back'])

    async def test_stdio_handshake_lists_our_tools_from_another_directory(self):
        import asyncio
        import subprocess
        import tomllib
        from scripts.check_mcp import probe
        launcher = Path(__file__).resolve().parents[1] / 'scripts' / 'serve_mcp.py'
        printed = await asyncio.to_thread(subprocess.check_output,
            [sys.executable, str(launcher), '--root', str(self.root), '--print-config'], text=True, cwd=self.root)
        config = tomllib.loads(printed)['mcp_servers']['leetcode']
        result = await asyncio.to_thread(probe, [config['command'], *config['args']], cwd=self.root)
        self.assertEqual(result['server']['name'], 'leetcode-coach')
        self.assertIn('get_progress', [tool['name'] for tool in result['tools']])

    async def test_slow_public_lookup_does_not_block_pausing_the_timer(self):
        import asyncio
        import anyio
        import httpx2
        import threading
        from unittest.mock import patch
        started, release = threading.Event(), threading.Event()
        async def respond(transport, request):
            started.set()
            while not release.is_set():
                await anyio.sleep(0.01)
            return httpx2.Response(403)
        await self.start()
        with patch('httpx2.AsyncHTTPTransport.handle_async_request', respond):
            lookup = asyncio.create_task(self.server.call_tool('get_problem', {'titleSlug': 'two-sum'}))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                paused = await asyncio.wait_for(self.call('pause_attempt', attempt_id=1), timeout=1)
                self.assertEqual(paused['state'], 'paused')
            finally:
                release.set()
                await asyncio.gather(lookup, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
