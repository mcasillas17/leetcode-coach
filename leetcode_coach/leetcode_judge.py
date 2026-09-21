"""Authenticated judge transport; destinations and payload fields are fixed."""

import json
import re

from .leetcode_public import PublicAPIError, PublicLeetCode, slug_value


class JudgeError(ValueError):
    pass


def remote_id(value, kind):
    if type(value) is int:
        value = str(value)
    # Test IDs include decimal timestamps, e.g. runcode_1627219627.5662382_EI7iasnhLm.
    # Keep the prefix and path-safe alphabet; submission IDs remain numeric only.
    pattern = r'[1-9][0-9]{0,19}' if kind == 'submission' else r'(?:[1-9][0-9]{0,19}|runcode_[A-Za-z0-9_.-]{1,100})'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise JudgeError('LeetCode returned an invalid judge ID. Do not automatically resend.')
    return value


class LeetCodeJudge:
    async def question_id(self, slug, frontend_id, language):
        query = ('query CoachJudgeIdentity($titleSlug: String!) { question(titleSlug: $titleSlug) '
                 '{ questionId questionFrontendId titleSlug codeSnippets { langSlug } } }')
        try:
            question = (await PublicLeetCode()._query(query, {'titleSlug': slug_value(slug)})).get('question')
        except PublicAPIError as exc:
            raise JudgeError(str(exc)) from None
        if (not isinstance(question, dict) or question.get('titleSlug') != slug
                or question.get('questionFrontendId') != str(frontend_id)):
            raise JudgeError('Problem identity could not be verified. No code was sent.')
        snippets = question.get('codeSnippets')
        if not isinstance(snippets, list) or language not in [s.get('langSlug') for s in snippets if isinstance(s, dict)]:
            raise JudgeError('LeetCode did not confirm support for this solution language. No code was sent.')
        return remote_id(question.get('questionId'), 'submission')

    async def _request(self, method, path, slug, credentials, body=None):
        import anyio
        import httpx2
        slug_value(slug)
        try:
            with anyio.fail_after(10):
                async with httpx2.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client:
                    headers = {'Cookie': f'LEETCODE_SESSION={credentials.session}; csrftoken={credentials.csrf}',
                               'X-CSRFToken': credentials.csrf, 'Origin': 'https://leetcode.com',
                               'Referer': f'https://leetcode.com/problems/{slug}/',
                               'Accept': 'application/json', 'Accept-Encoding': 'identity',
                               'User-Agent': 'leetcode-coach/1.0'}
                    async with client.stream(method, 'https://leetcode.com' + path, json=body, headers=headers) as response:
                        if response.status_code in (401, 403):
                            raise JudgeError('LeetCode authentication expired or access was blocked. Run local login or use the website.')
                        if response.status_code != 200:
                            raise JudgeError(f'LeetCode returned HTTP {response.status_code}. No automatic retry was made.')
                        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                            raise JudgeError('LeetCode returned unsupported compressed data.')
                        raw = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(raw) + len(chunk) > 1_000_000:
                                raise JudgeError('LeetCode judge response exceeded the size limit.')
                            raw.extend(chunk)
        except (TimeoutError, httpx2.HTTPError, OSError):
            raise JudgeError('LeetCode did not return a complete response within the network deadline. Do not automatically resend.') from None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise JudgeError('LeetCode returned malformed judge data. Do not automatically resend.') from None
        if not isinstance(result, dict) or result.get('error') or result.get('errors'):
            raise JudgeError('LeetCode rejected the judge request. No automatic retry was made.')
        return result

    async def start(self, slug, question_id, language, code, kind, credentials, data_input):
        endpoint = 'submit' if kind == 'submission' else 'interpret_solution'
        body = {'question_id': question_id, 'lang': language, 'typed_code': code}
        if kind == 'test':
            body['data_input'] = data_input
        result = await self._request('POST', f'/problems/{slug_value(slug)}/{endpoint}/', slug, credentials, body)
        return remote_id(result.get('submission_id' if kind == 'submission' else 'interpret_id'), kind)

    async def check(self, identifier, kind, slug, credentials):
        identifier = remote_id(identifier, kind)
        result = await self._request('GET', f'/submissions/detail/{identifier}/check/', slug, credentials)
        if 'submission_id' in result and remote_id(result['submission_id'], kind) != identifier:
            raise JudgeError('LeetCode returned a result for a different judge request; no verdict was recorded.')
        return result


def normalize_result(result, credentials):
    state = result.get('state')
    if state in ('PENDING', 'STARTED'):
        return {'state': 'pending', 'poll_after_seconds': 2}
    if state != 'SUCCESS':
        raise JudgeError('LeetCode returned an unrecognized judge state. No verdict was recorded.')
    verdicts = {'Accepted': (10, 'accepted'), 'Wrong Answer': (11, 'wrong-answer'),
                'Memory Limit Exceeded': (12, 'memory-limit'), 'Time Limit Exceeded': (14, 'time-limit'),
                'Runtime Error': (15, 'runtime-error'), 'Compile Error': (20, 'compile-error')}
    message = result.get('status_msg')
    expected, verdict = verdicts.get(message, (None, 'unknown')) if isinstance(message, str) else (None, 'unknown')
    if type(result.get('status_code')) is not int or result['status_code'] != expected:
        verdict = 'unknown'
    correct, total = result.get('total_correct'), result.get('total_testcases')
    if verdict == 'accepted':
        malformed_counts = any(key in result and (type(result[key]) is not int or result[key] < 0)
                               for key in ('total_correct', 'total_testcases'))
        mismatched_counts = correct is not None and total is not None and correct != total
        failed = ('run_success' in result and result['run_success'] is not True
                  or result.get('runtime_error') or result.get('compile_error'))
        if malformed_counts or mismatched_counts or failed:
            verdict = 'unknown'
    normalized = {'state': 'unknown' if verdict == 'unknown' else 'completed',
                  'verdict': verdict, 'runtime_ms': None, 'memory_mb': None}
    for field, unit, target in [('status_runtime', 'ms', 'runtime_ms'), ('status_memory', 'MB', 'memory_mb')]:
        value = result.get(field)
        match = re.fullmatch(r'([0-9]{1,9}(?:\.[0-9]{1,6})?)\s*' + unit, value) if isinstance(value, str) else None
        if match:
            normalized[target] = float(match[1])
    diagnostics = {}
    for key in ('compile_error', 'runtime_error', 'std_output', 'code_output', 'expected_code_answer', 'last_testcase'):
        value = result.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            value = '\n'.join(value)
        if isinstance(value, str) and value:
            value = value.replace(credentials.session, '[redacted]').replace(credentials.csrf, '[redacted]')
            diagnostics[key] = value[:4000]
    normalized['diagnostics'] = diagnostics
    return normalized
