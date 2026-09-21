"""Deterministic progress summaries; no inferred time or acceptance."""

import html
import statistics
from collections import Counter, defaultdict

from .store import CoachError


GROUPS = ('problem', 'topic', 'difficulty', 'language', 'assistance', 'encounter')


def aggregate(attempts):
    finished = [a for a in attempts if a['state'] == 'finished']
    timed = [a for a in finished if a['timing']['confirmed'] and a['timing']['active_seconds'] is not None]
    accepted = [a for a in finished if a['outcome'] == 'accepted']
    return {
        'attempts': len(attempts), 'finished': len(finished),
        'accepted': len(accepted), 'verified_accepted': sum(a['acceptance']['verified'] for a in accepted),
        'independent_solves': sum(a['independent'] for a in accepted),
        'hint_count': sum(a['hint_count'] for a in attempts),
        'timing_samples': len(timed), 'timing_excluded': len(finished) - len(timed),
        'active_seconds': round(sum(a['timing']['active_seconds'] for a in timed), 3),
        'median_seconds': statistics.median(a['timing']['active_seconds'] for a in timed) if timed else None,
        'phase_seconds': {phase: round(sum(a['timing']['phase_seconds'][phase] for a in timed), 3)
                          for phase in ('reasoning', 'implementation', 'debugging')},
    }


def build_report(tracker, group_by='problem', session_id=None):
    if group_by not in GROUPS:
        raise CoachError('Unknown report grouping.')
    state = tracker.status()
    seen = set()
    for attempt in state['attempts']:
        attempt['encounter'] = 'repeat' if attempt['slug'] in seen else 'first'
        seen.add(attempt['slug'])
    if session_id is not None and not any(s['id'] == session_id for s in state['sessions']):
        raise CoachError('Session not found.')
    attempts = [a for a in state['attempts'] if session_id is None or a['session_id'] == session_id]
    grouped = defaultdict(list)
    mistakes = Counter()
    for attempt in attempts:
        labels = {
            'problem': [attempt['slug']], 'topic': attempt['problem'].get('tags', []) or ['unclassified'],
            'difficulty': [attempt['problem']['difficulty']], 'language': [attempt['language']],
            'assistance': [attempt['assistance']],
            'encounter': [attempt['encounter']],
        }[group_by]
        for label in set(labels):
            grouped[label].append(attempt)
        mistakes.update(set((attempt['feedback'] or {}).get('mistakes', [])))
    return {'generated_at': tracker.now(), 'group_by': group_by, 'totals': aggregate(attempts),
            'groups': {label: aggregate(items) for label, items in sorted(grouped.items())},
            'attempts': attempts, 'mistakes': dict(mistakes.most_common()),
            'due_reviews': state['due_reviews'],
            'sessions': [s for s in state['sessions'] if session_id is None or s['id'] == session_id]}


def safe(value):
    # Escape both HTML and Markdown so imported titles/feedback remain literal data.
    value = html.escape(str(value), quote=True).replace('\n', ' ').replace('\r', ' ')
    for character in '\\`*_{}[]()#+-.!|>':
        value = value.replace(character, '\\' + character)
    return value


def duration(seconds):
    return 'unknown' if seconds is None else f'{seconds / 60:.2f} min'


def render_markdown(report):
    totals = report['totals']
    lines = ['# LeetCode practice', '',
             f"{totals['attempts']} attempts · {totals['accepted']} accepted · "
             f"{totals['verified_accepted']} verified by recorded MCP evidence · "
             f"{totals['independent_solves']} independent solves", '',
             f"Confirmed solve time: {duration(totals['active_seconds'])}; "
             f"{totals['timing_samples']} samples, {totals['timing_excluded']} unconfirmed timings excluded.",
             'User-reported acceptance is unverified. Local tests do not establish LeetCode acceptance.', '',
             f"## By {report['group_by']}", '',
             '| Group | Attempts | Accepted | Hints | Median solve | Reasoning | Coding | Debugging |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for label, group in report['groups'].items():
        phase = group['phase_seconds']
        lines.append(f"| {safe(label)} | {group['attempts']} | {group['accepted']} | {group['hint_count']} | "
                     f"{duration(group['median_seconds'])} | {duration(phase['reasoning'])} | "
                     f"{duration(phase['implementation'])} | {duration(phase['debugging'])} |")
    lines.extend(['', '## Attempts', ''])
    for attempt in report['attempts']:
        timing = attempt['timing']
        lines.extend([f"### {attempt['id']}. {safe(attempt['problem']['title'])}", '',
                      f"{safe(attempt['outcome'] or attempt['state'])} · {safe(attempt['language'])} · "
                      f"{attempt['encounter']} encounter · "
                      f"{attempt['assistance']} independence/assistance · "
                      f"{attempt['hint_count']} hints (maximum level {attempt['hint_level']})", '',
                      f"Solve: {duration(timing['active_seconds'])} "
                      f"({'confirmed' if timing['confirmed'] else 'unconfirmed'}); "
                      f"wall elapsed: {duration(timing['wall_seconds'])}.",
                      f"Reasoning: {duration(timing['phase_seconds']['reasoning'])}; "
                      f"coding: {duration(timing['phase_seconds']['implementation'])}; "
                      f"debugging: {duration(timing['phase_seconds']['debugging'])}.",
                      f"Teach-back: {'complete' if attempt['teach_back'] else 'incomplete'}. "
                      f"Review: {attempt['review_date'] or 'not scheduled'}.", ''])
        for result in attempt['judge_results']:
            lines.append(f"- {safe(result['kind'])}: {safe(result['verdict'])} "
                         f"({safe(result['source'])}, snapshot {result['snapshot_id']}, "
                         f"submission {safe(result['submission_id'] or 'not supplied')}); "
                         f"runtime {result['runtime_ms'] if result['runtime_ms'] is not None else 'unknown'} ms, "
                         f"memory {result['memory_mb'] if result['memory_mb'] is not None else 'unknown'} MB.")
        for key, value in (attempt['feedback'] or {}).items():
            rendered = ', '.join(value) if isinstance(value, list) else value
            lines.append(f'- {safe(key.replace("_", " ").capitalize())}: {safe(rendered)}')
        lines.append('')
    lines.extend(['## Reviews due (current workspace)', ''])
    lines.extend(f"- {safe(item['title'])}: {item['review_date']}" for item in report['due_reviews'])
    if not report['due_reviews']:
        lines.append('No reviews due.')
    lines.extend(['', '## Repeated mistakes', ''])
    lines.extend(f'- {safe(mistake)}: {count} attempts' for mistake, count in report['mistakes'].items())
    if not report['mistakes']:
        lines.append('No mistakes recorded.')
    for session in report['sessions']:
        if session['summary']:
            lines.extend(['', f"## Session {session['id']}", '', safe(session['summary'])])
    return '\n'.join(lines).rstrip() + '\n'
