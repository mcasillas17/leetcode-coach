"""Public network boundary: fixed destinations, no credentials, no answer leakage."""

import importlib.util
import json
import os
import unittest
from unittest.mock import patch

from leetcode_coach.leetcode_public import PublicLeetCode, PublicAPIError


QUESTION = {
    'questionFrontendId': '1', 'title': 'Two Sum', 'titleSlug': 'two-sum',
    'difficulty': 'Easy', 'isPaidOnly': False,
    'content': '<p>Find <code>two</code> numbers.</p><script>steal()</script><p>Return indices.</p>',
    'exampleTestcases': '[2,7,11,15]\n9',
    'codeSnippets': [{'langSlug': 'python3', 'lang': 'Python3', 'code': 'class Solution:\n    pass'}],
    'hints': ['Use a hash map'], 'topicTags': [{'name': 'Hash Table'}], 'solution': 'spoiler',
}


@unittest.skipUnless(importlib.util.find_spec('httpx2'), 'Optional MCP network dependencies are not installed')
class PublicClientTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, payload, operation):
        import httpx2
        requests = []

        async def respond(transport, request):
            requests.append(request)
            # A proxy-aware client would select an AsyncHTTPProxy pool instead.
            self.assertEqual(type(transport._pool).__name__, 'AsyncConnectionPool')
            return httpx2.Response(200, stream=httpx2.ByteStream(json.dumps(payload).encode()))

        with patch('httpx2.AsyncHTTPTransport.handle_async_request', respond):
            result = await operation(PublicLeetCode())
        request = requests[0]
        self.assertEqual(str(request.url), 'https://leetcode.com/graphql/')
        self.assertEqual(request.method, 'POST')
        self.assertNotIn('cookie', request.headers)
        self.assertNotIn('authorization', request.headers)
        return result, json.loads(request.content)

    async def test_problem_returns_statement_and_starter_without_spoilers_or_active_html(self):
        result, sent = await self.request({'data': {'question': QUESTION}}, lambda c: c.get_problem('two-sum'))
        self.assertEqual(sent['variables'], {'titleSlug': 'two-sum'})
        self.assertEqual(result['frontend_id'], 1)
        self.assertEqual(result['titleSlug'], 'two-sum')
        self.assertIn('Return indices.', result['statement'])
        self.assertNotIn('<', result['statement'])
        self.assertNotIn('steal()', result['statement'])
        for field in ('hints', 'topicTags', 'solution'):
            self.assertNotIn(field, result)
            self.assertNotIn(field, sent['query'])

    async def test_daily_and_search_use_bounded_queries_and_normalize_metadata(self):
        daily, _ = await self.request({'data': {'activeDailyCodingChallengeQuestion': {
            'date': '2026-09-21', 'link': 'https://evil.invalid/', 'question': QUESTION}}},
            lambda c: c.get_daily_challenge())
        self.assertEqual(daily['url'], 'https://leetcode.com/problems/two-sum/')
        self.assertEqual(daily['date'], '2026-09-21')
        found, sent = await self.request({'data': {'problemsetQuestionList': {'total': 1, 'questions': [QUESTION]}}},
                                   lambda c: c.search_problems('two', 'Easy', 5, 0))
        self.assertEqual(found['problems'][0]['title'], 'Two Sum')
        self.assertEqual(sent['variables']['limit'], 5)
        self.assertEqual(sent['variables']['filters']['difficulty'], 'EASY')
        self.assertNotIn('content', found['problems'][0])

    async def test_invalid_input_rejected_before_network(self):
        with patch('httpx2.AsyncHTTPTransport.handle_async_request', side_effect=AssertionError('network reached')):
            client = PublicLeetCode()
            for slug in ('../secrets', 'https://example.org', '', 'a' * 151):
                with self.assertRaises(PublicAPIError):
                    await client.get_problem(slug)
            for args in (('', None, 51, 0), ('', None, True, 0), ('', None, 1, -1),
                         ('x' * 201, None, 1, 0), ('x', 'Impossible', 1, 0)):
                with self.assertRaises(PublicAPIError):
                    await client.search_problems(*args)

    async def test_malformed_upstream_is_an_error_not_empty_success_or_raw_error_leak(self):
        import httpx2
        for payload in ({'errors': [{'message': 'SECRET from upstream'}]}, {'data': {}},
                        {'data': {'question': None}}, {'data': {'question': {'title': 'Partial'}}}):
            with self.subTest(payload=payload), self.assertRaises(PublicAPIError) as error:
                await self.request(payload, lambda c: c.get_problem('two-sum'))
            self.assertNotIn('SECRET', str(error.exception))
        for raw in (b'not json SECRET', b'[' * 2000, b'x' * 1_000_001):
            async def respond(transport, request):
                return httpx2.Response(200, stream=httpx2.ByteStream(raw))
            with patch('httpx2.AsyncHTTPTransport.handle_async_request', respond):
                with self.assertRaises(PublicAPIError):
                    await PublicLeetCode().get_problem('two-sum')

    async def test_network_failures_redirects_and_limits_are_sanitized_without_retries(self):
        import httpx2
        for failure in (httpx2.ReadTimeout('SECRET'), httpx2.ConnectError('SECRET'),
                        httpx2.RemoteProtocolError('SECRET'), 429, 302, 403):
            calls = []
            async def respond(transport, request):
                calls.append(str(request.url))
                if isinstance(failure, int):
                    return httpx2.Response(failure, headers={'location': 'https://evil.invalid/'}, content=b'SECRET')
                raise failure
            with patch('httpx2.AsyncHTTPTransport.handle_async_request', respond):
                with self.assertRaises(PublicAPIError) as error:
                    await PublicLeetCode().get_problem('two-sum')
                self.assertNotIn('SECRET', str(error.exception))
                self.assertEqual(calls, ['https://leetcode.com/graphql/'])

    async def test_ambient_proxy_and_credentials_are_not_used(self):
        with patch.dict(os.environ, {'LEETCODE_SESSION': 'SECRET', 'HTTPS_PROXY': 'http://evil.invalid:80'}):
            result, _ = await self.request({'data': {'question': QUESTION}}, lambda c: c.get_problem('two-sum'))
        self.assertEqual(result['title'], 'Two Sum')

    async def test_total_deadline_cancels_delayed_headers_and_delayed_body_end(self):
        import anyio
        import httpx2
        import time
        closed = []
        class SlowBody(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield json.dumps({'data': {'question': QUESTION}}).encode()
                await anyio.sleep(2)
            async def aclose(self):
                closed.append(True)
        for slow_headers in (True, False):
            async def respond(transport, request):
                if slow_headers:
                    await anyio.sleep(2)
                return httpx2.Response(200, stream=SlowBody())
            with patch('httpx2.AsyncHTTPTransport.handle_async_request', respond), patch('leetcode_coach.leetcode_public.TIMEOUT', 0.05):
                started = time.monotonic()
                with self.assertRaises(PublicAPIError):
                    await PublicLeetCode().get_problem('two-sum')
                self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(closed)

    async def test_premium_statement_remains_unavailable(self):
        question = {**QUESTION, 'isPaidOnly': True, 'content': None, 'codeSnippets': None}
        result, _ = await self.request({'data': {'question': question}}, lambda c: c.get_problem('two-sum'))
        self.assertTrue(result['paid_only'])
        self.assertIsNone(result['statement'])
        self.assertEqual(result['code_snippets'], [])

    async def test_slow_dns_does_not_extend_the_request_deadline(self):
        import socket
        import time
        def slow_resolver(*args, **kwargs):
            time.sleep(0.4)
            raise socket.gaierror('fixture: no network')
        with patch('socket.getaddrinfo', slow_resolver), patch('leetcode_coach.leetcode_public.TIMEOUT', 0.05):
            started = time.monotonic()
            with self.assertRaises(PublicAPIError):
                await PublicLeetCode().get_problem('two-sum')
            self.assertLess(time.monotonic() - started, 0.3)


if __name__ == '__main__':
    unittest.main()
