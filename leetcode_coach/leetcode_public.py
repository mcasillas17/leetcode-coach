"""Credential-free, fixed-query access to LeetCode's undocumented public API."""

import json
import re
from html.parser import HTMLParser


ENDPOINT = 'https://leetcode.com/graphql/'
MAX_BYTES = 1_000_000
TIMEOUT = 10
SUMMARY_FIELDS = 'questionFrontendId title titleSlug difficulty isPaidOnly'


class PublicAPIError(ValueError):
    """A safe, actionable message without raw upstream data or secrets."""


class StatementText(HTMLParser):
    """Return inert text; do not load images, follow links, or render scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'iframe'):
            self.hidden += 1
        elif not self.hidden and tag in ('p', 'div', 'br', 'li', 'pre', 'tr'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'iframe') and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in ('p', 'div', 'li', 'pre', 'tr'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def field_text(value, name, maximum, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise PublicAPIError(f'Invalid {name}.')
    return value


def slug_value(value):
    if not isinstance(value, str) or len(value) > 150 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
        raise PublicAPIError('Problem slug must contain lowercase letters, digits, and single hyphens.')
    return value


def summary(question):
    if not isinstance(question, dict):
        raise PublicAPIError('LeetCode returned no problem or an unexpected problem format.')
    slug = slug_value(question.get('titleSlug'))
    identifier = question.get('questionFrontendId')
    if not isinstance(identifier, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', identifier):
        raise PublicAPIError('LeetCode returned an unsupported problem number.')
    difficulty = question.get('difficulty')
    if difficulty not in ('Easy', 'Medium', 'Hard') or type(question.get('isPaidOnly')) is not bool:
        raise PublicAPIError('LeetCode returned unexpected problem metadata.')
    return {'frontend_id': int(identifier), 'title': field_text(question.get('title'), 'title', 200),
            'titleSlug': slug, 'difficulty': difficulty, 'paid_only': question['isPaidOnly'],
            'url': f'https://leetcode.com/problems/{slug}/'}


class PublicLeetCode:
    async def _query(self, query, variables):
        # Imported only for optional public/MCP operations; the local CLI needs neither.
        import anyio
        import httpx2
        try:
            with anyio.fail_after(TIMEOUT):
                # A fresh credential-free client for each request. Redirects and
                # environment proxies are disabled; no cookie jar is retained.
                async with httpx2.AsyncClient(trust_env=False, follow_redirects=False, timeout=TIMEOUT) as client:
                    async with client.stream('POST', ENDPOINT,
                            json={'query': query, 'variables': variables},
                            headers={'Accept': 'application/json', 'Accept-Encoding': 'identity',
                                     'User-Agent': 'leetcode-coach/1.0'}) as response:
                        if response.status_code == 429:
                            raise PublicAPIError('LeetCode rate limited the request. Wait before trying again.')
                        if response.status_code != 200:
                            raise PublicAPIError(f'LeetCode returned HTTP {response.status_code}. Use the website if access is blocked.')
                        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                            raise PublicAPIError('LeetCode returned unsupported compressed content.')
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise PublicAPIError('LeetCode response exceeded the 1 MB limit.')
        except (TimeoutError, httpx2.HTTPError, OSError):
            raise PublicAPIError('Cannot reach LeetCode within the network timeout. Use the website or try later.') from None
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise PublicAPIError('LeetCode returned malformed JSON.') from None
        if not isinstance(payload, dict) or payload.get('errors') or not isinstance(payload.get('data'), dict):
            raise PublicAPIError('LeetCode rejected the query or changed its public API. No result was recorded.')
        return payload['data']

    async def get_problem(self, titleSlug):
        slug = slug_value(titleSlug)
        query = ('query CoachProblem($titleSlug: String!) { question(titleSlug: $titleSlug) { '
                 + SUMMARY_FIELDS + ' content exampleTestcases codeSnippets { langSlug lang code } } }')
        question = (await self._query(query, {'titleSlug': slug})).get('question')
        result = summary(question)
        if result['titleSlug'] != slug:
            raise PublicAPIError('LeetCode returned a different problem than requested.')
        content = question.get('content')
        result['statement'] = None
        if content is not None:
            parser = StatementText()
            parser.feed(field_text(content, 'problem statement', MAX_BYTES, empty=True))
            parser.close()
            result['statement'] = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
        elif not result['paid_only']:
            raise PublicAPIError('LeetCode did not return the public problem statement.')
        result['example_testcases'] = field_text(question.get('exampleTestcases') or '', 'examples', MAX_BYTES, empty=True)
        snippets = question.get('codeSnippets')
        if snippets is None:
            snippets = []
        if not isinstance(snippets, list) or len(snippets) > 100:
            raise PublicAPIError('LeetCode returned malformed starter code.')
        result['code_snippets'] = []
        for item in snippets:
            if not isinstance(item, dict):
                raise PublicAPIError('LeetCode returned malformed starter code.')
            result['code_snippets'].append({'language': field_text(item.get('langSlug'), 'language', 80),
                                           'code': field_text(item.get('code'), 'starter code', MAX_BYTES, empty=True)})
        return result

    async def search_problems(self, query='', difficulty=None, limit=20, offset=0):
        field_text(query, 'search text', 200, empty=True)
        if difficulty not in (None, 'Easy', 'Medium', 'Hard'):
            raise PublicAPIError('Difficulty must be Easy, Medium, or Hard.')
        if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 10000:
            raise PublicAPIError('Search limit must be 1–50 and offset 0–10000.')
        filters = {'searchKeywords': query}
        if difficulty:
            filters['difficulty'] = difficulty.upper()
        document = ('query CoachSearch($limit: Int!, $skip: Int!, $filters: QuestionListFilterInput) { '
                    'problemsetQuestionList: questionList(categorySlug: "", limit: $limit, skip: $skip, filters: $filters) '
                    '{ total: totalNum questions: data { ' + SUMMARY_FIELDS + ' } } }')
        listing = (await self._query(document, {'limit': limit, 'skip': offset, 'filters': filters})).get('problemsetQuestionList')
        if (not isinstance(listing, dict) or type(listing.get('total')) is not int or listing['total'] < 0
                or not isinstance(listing.get('questions'), list) or len(listing['questions']) > limit):
            raise PublicAPIError('LeetCode returned an unexpected search result.')
        return {'total': listing['total'], 'offset': offset, 'problems': [summary(q) for q in listing['questions']]}

    async def get_daily_challenge(self):
        document = 'query CoachDaily { activeDailyCodingChallengeQuestion { date question { ' + SUMMARY_FIELDS + ' } } }'
        daily = (await self._query(document, {})).get('activeDailyCodingChallengeQuestion')
        if not isinstance(daily, dict) or not isinstance(daily.get('date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', daily['date']):
            raise PublicAPIError('LeetCode returned an unexpected daily challenge.')
        return {**summary(daily.get('question')), 'date': daily['date']}
