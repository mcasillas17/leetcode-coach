"""Practice transitions and evidence; no network calls or generated answers."""

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from .store import CoachError, Store


PHASES = ('reasoning', 'implementation', 'debugging')
MODES = ('interview', 'guided')
LANGUAGES = {'python3': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
             'cpp': 'cpp', 'c': 'c', 'csharp': 'cs', 'golang': 'go', 'rust': 'rs',
             'swift': 'swift', 'kotlin': 'kt', 'ruby': 'rb'}
VERDICTS = ('accepted', 'wrong-answer', 'time-limit', 'memory-limit', 'runtime-error',
            'compile-error', 'unknown')
FEEDBACK_FIELDS = {'approach', 'correctness', 'complexity', 'optimizations', 'testing',
                   'communication', 'mistakes', 'next_exercise'}


def utc_now():
    return datetime.now(timezone.utc)


def text(value, name, limit=4000, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise CoachError(f'{name} must be nonempty text of at most {limit} characters.')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise CoachError(f'{name} contains control characters.')
    return value


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise CoachError(f'{name} must be a finite, nonnegative number.')
    return value


def choice(value, options, name):
    if not isinstance(value, str) or value not in options:
        raise CoachError(f'{name} must be one of: {", ".join(options)}.')
    return value


def write(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.store.transaction():
            return method(self, *args, **kwargs)
    return wrapped


class Tracker:
    def __init__(self, root, clock=utc_now):
        self.root = Path(root).expanduser().resolve()
        self.clock = clock
        self.store = Store(self.root)
        self.db = self.store.db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.store.close()

    def now(self):
        value = self.clock()
        if value.tzinfo is None:
            raise CoachError('Clock must provide a timezone-aware datetime.')
        return value.astimezone(timezone.utc).isoformat()

    def row(self, attempt_id):
        if type(attempt_id) is not int or attempt_id < 1:
            raise CoachError('Attempt ID must be a positive integer.')
        row = self.db.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
        if row is None:
            raise CoachError('Attempt not found; run status to find its ID.')
        return row

    def event(self, attempt_id, kind, data, at=None):
        self.db.execute('INSERT INTO events(attempt_id, at, kind, data) VALUES (?, ?, ?, ?)',
                        (attempt_id, at or self.now(), kind, json.dumps(data)))

    def close_interval(self, attempt_id, at, recovering=False):
        interval = self.db.execute('SELECT * FROM intervals WHERE attempt_id=? AND ended_at IS NULL', (attempt_id,)).fetchone()
        if interval is None:
            raise CoachError('No active timer interval; inspect the attempt before continuing.')
        if at < interval['started_at'] and not recovering:
            raise CoachError('Clock moved backwards; run recover, then correct the interval.')
        self.db.execute('UPDATE intervals SET ended_at=? WHERE id=?', (at, interval['id']))

    def open_interval(self, attempt_id, phase, at):
        self.db.execute('INSERT INTO intervals(attempt_id, phase, started_at) VALUES (?, ?, ?)', (attempt_id, phase, at))

    @write
    def start(self, slug, frontend_id, title, difficulty, *, tags=None, language='python3',
              mode='interview', review=False, endpoint='leetcode.com', working_file=None):
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or len(slug) > 150:
            raise CoachError('Problem slug must use lowercase letters, digits, and single hyphens.')
        if type(frontend_id) is not int or frontend_id < 1:
            raise CoachError('Problem ID must be a positive integer.')
        text(title, 'Title', 200)
        choice(difficulty, ('Easy', 'Medium', 'Hard'), 'Difficulty')
        choice(language, LANGUAGES, 'Language')
        choice(mode, MODES, 'Mode')
        choice(endpoint, ('leetcode.com', 'leetcode.cn'), 'Endpoint')
        tags = [] if tags is None else tags
        if not isinstance(tags, list) or len(tags) > 30:
            raise CoachError('Tags must be a list of at most 30 strings.')
        for tag in tags:
            text(tag, 'Tag', 80)
        if self.db.execute("SELECT id FROM attempts WHERE state IN ('running','paused')").fetchone():
            raise CoachError('An attempt is already open. Resume or finish it before starting another.')
        old = self.db.execute('SELECT * FROM problems WHERE slug=? OR frontend_id=?', (slug, frontend_id)).fetchall()
        if old and (len(old) != 1 or old[0]['slug'] != slug or old[0]['frontend_id'] != frontend_id):
            raise CoachError('Problem ID and slug conflict with an existing problem.')
        self.db.execute('INSERT INTO problems VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(slug) DO NOTHING',
                        (slug, frontend_id, title, difficulty, f'https://{endpoint}/problems/{slug}/', json.dumps(tags)))
        at = self.now()
        session = self.db.execute('SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1').fetchone()
        if session and session['mode'] != mode:
            self.db.execute('UPDATE sessions SET ended_at=? WHERE id=?', (at, session['id']))
            session = None
        session_id = session['id'] if session else self.db.execute('INSERT INTO sessions(started_at, mode) VALUES (?, ?)', (at, mode)).lastrowid
        attempt_id = self.db.execute('''INSERT INTO attempts(session_id, slug, language, mode, is_review, state, phase, started_at)
            VALUES (?, ?, ?, ?, ?, 'running', 'reasoning', ?)''',
            (session_id, slug, language, mode, bool(review), at)).lastrowid
        relative = working_file or f'workspace/leetcode/{attempt_id}/{frontend_id}.{slug}.{LANGUAGES[language]}'
        path = self.workspace_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open('x', encoding='utf-8') as handle:
                handle.write('')
        self.db.execute('UPDATE attempts SET working_file=? WHERE id=?', (str(path.relative_to(self.root)), attempt_id))
        self.open_interval(attempt_id, 'reasoning', at)
        self.event(attempt_id, 'start', {'mode': mode, 'review': bool(review)}, at)
        return self.attempt(attempt_id)

    def workspace_path(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise CoachError('Solution path must be relative to workspace/leetcode.')
        workspace = self.root / 'workspace' / 'leetcode'
        if not workspace.resolve().is_relative_to(self.root) or workspace.resolve() != workspace:
            raise CoachError('Solution workspace must not escape through a symlink.')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(workspace) or path == workspace:
            raise CoachError('Solution path must stay inside workspace/leetcode.')
        return path

    @write
    def phase(self, attempt_id, phase):
        choice(phase, PHASES, 'Phase')
        row = self.row(attempt_id)
        if row['state'] != 'running':
            raise CoachError('Only a running attempt can change phase; resume it first.')
        if row['phase'] == phase:
            return self.attempt(attempt_id)
        at = self.now()
        self.close_interval(attempt_id, at)
        self.open_interval(attempt_id, phase, at)
        self.db.execute('UPDATE attempts SET phase=? WHERE id=?', (phase, attempt_id))
        self.event(attempt_id, 'phase', {'phase': phase}, at)
        return self.attempt(attempt_id)

    @write
    def pause(self, attempt_id, reason='break'):
        text(reason, 'Pause reason', 500)
        if self.row(attempt_id)['state'] != 'running':
            raise CoachError('Only a running attempt can be paused.')
        at = self.now()
        self.close_interval(attempt_id, at)
        self.db.execute("UPDATE attempts SET state='paused' WHERE id=?", (attempt_id,))
        self.event(attempt_id, 'pause', {'reason': reason}, at)
        return self.attempt(attempt_id)

    @write
    def resume(self, attempt_id):
        row = self.row(attempt_id)
        if row['state'] != 'paused':
            raise CoachError('Only a paused attempt can be resumed.')
        at = self.now()
        last_end = self.db.execute('SELECT ended_at FROM intervals WHERE attempt_id=? ORDER BY id DESC LIMIT 1', (attempt_id,)).fetchone()[0]
        if at < last_end:
            raise CoachError('Clock moved backwards; correct the clock before resuming.')
        self.open_interval(attempt_id, row['phase'], at)
        self.db.execute("UPDATE attempts SET state='running' WHERE id=?", (attempt_id,))
        self.event(attempt_id, 'resume', {}, at)
        return self.attempt(attempt_id)

    @write
    def recover(self, attempt_id):
        row = self.row(attempt_id)
        if row['state'] == 'finished':
            raise CoachError('This attempt is finished; use show to inspect it.')
        if row['state'] == 'running':
            at = self.now()
            self.close_interval(attempt_id, at, recovering=True)
            self.db.execute("UPDATE attempts SET state='paused', timing_confirmed=0 WHERE id=?", (attempt_id,))
            self.event(attempt_id, 'recover', {'timing_requires_confirmation': True}, at)
        return self.attempt(attempt_id)

    @write
    def correct_interval(self, attempt_id, interval_id, seconds, reason):
        self.row(attempt_id)
        number(seconds, 'Corrected seconds')
        text(reason, 'Correction reason', 1000)
        interval = self.db.execute('SELECT * FROM intervals WHERE id=? AND attempt_id=?', (interval_id, attempt_id)).fetchone()
        if interval is None or interval['ended_at'] is None:
            raise CoachError('Correct a closed interval belonging to this attempt; pause or recover first.')
        self.db.execute('UPDATE intervals SET corrected_seconds=? WHERE id=?', (seconds, interval_id))
        self.db.execute('UPDATE attempts SET timing_confirmed=0 WHERE id=?', (attempt_id,))
        self.event(attempt_id, 'correction', {'interval_id': interval_id, 'previous_correction': interval['corrected_seconds'], 'seconds': seconds, 'reason': reason})
        return self.attempt(attempt_id)

    @write
    def confirm_timing(self, attempt_id):
        row = self.row(attempt_id)
        if row['state'] == 'running':
            raise CoachError('Pause or finish before confirming timing.')
        if self.attempt(attempt_id)['timing']['clock_error']:
            raise CoachError('Correct invalid intervals before confirming timing.')
        self.db.execute('UPDATE attempts SET timing_confirmed=1 WHERE id=?', (attempt_id,))
        self.event(attempt_id, 'confirm-timing', {})
        return self.attempt(attempt_id)

    @write
    def hint(self, attempt_id, level, note):
        row = self.row(attempt_id)
        if type(level) is not int or not 1 <= level <= 5:
            raise CoachError('Hint level must be an integer from 1 to 5.')
        text(note, 'Hint note', 2000)
        self.db.execute('UPDATE attempts SET hint_level=?, hint_count=hint_count+1 WHERE id=?', (max(level, row['hint_level']), attempt_id))
        self.event(attempt_id, 'hint', {'level': level, 'note': note})
        self.schedule(attempt_id)
        return self.attempt(attempt_id)

    @write
    def snapshot(self, attempt_id):
        row = self.row(attempt_id)
        path = self.workspace_path(row['working_file'])
        try:
            with path.open('rb') as handle:
                code = handle.read(1_000_001)
        except OSError as exc:
            raise CoachError('Cannot read solution file; save it inside workspace/leetcode first.') from exc
        if not code.strip() or len(code) > 1_000_000:
            raise CoachError('Solution must be nonempty and at most 1 MB.')
        try:
            code.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise CoachError('Solution must be UTF-8 text.') from exc
        at = self.now()
        digest = hashlib.sha256(code).hexdigest()
        snapshot_id = self.db.execute('INSERT INTO snapshots(attempt_id, created_at, language, sha256, code) VALUES (?, ?, ?, ?, ?)',
                                      (attempt_id, at, row['language'], digest, code)).lastrowid
        self.event(attempt_id, 'snapshot', {'snapshot_id': snapshot_id, 'sha256': digest}, at)
        return self.snapshot_info(snapshot_id)

    def snapshot_info(self, snapshot_id):
        row = self.db.execute('SELECT id, attempt_id, created_at, language, sha256 FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if row is None:
            raise CoachError('Snapshot not found.')
        return dict(row)

    def snapshot_content(self, snapshot_id):
        self.snapshot_info(snapshot_id)
        return self.db.execute('SELECT code FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()[0]

    @write
    def judge(self, attempt_id, snapshot_id, source, verdict, *, kind='submission',
              submission_id=None, runtime_ms=None, memory_mb=None):
        return self._record_judge(attempt_id, snapshot_id, source, verdict, kind=kind,
                                  submission_id=submission_id, runtime_ms=runtime_ms, memory_mb=memory_mb)

    def _record_judge(self, attempt_id, snapshot_id, source, verdict, *, kind='submission',
                      submission_id=None, runtime_ms=None, memory_mb=None):
        """Record evidence inside the caller's existing write transaction."""
        self.row(attempt_id)
        if self.snapshot_info(snapshot_id)['attempt_id'] != attempt_id:
            raise CoachError('Snapshot belongs to another attempt.')
        choice(source, ('mcp', 'user-reported', 'local-test'), 'Evidence source')
        choice(verdict, VERDICTS, 'Verdict')
        choice(kind, ('submission', 'test'), 'Judge operation')
        if source == 'local-test' and kind != 'test':
            raise CoachError('Local tests cannot be recorded as a LeetCode submission.')
        if source == 'mcp' and kind == 'submission' and verdict != 'unknown' and not submission_id:
            raise CoachError('A verified MCP submission requires its submission ID.')
        submission_id = '' if submission_id is None else text(submission_id, 'Submission ID', 100)
        if runtime_ms is not None:
            number(runtime_ms, 'Runtime milliseconds')
        if memory_mb is not None:
            number(memory_mb, 'Memory MB')
        if submission_id:
            conflict = self.db.execute('SELECT snapshot_id, attempt_id FROM judge_results WHERE source=? AND kind=? AND submission_id=?',
                                       (source, kind, submission_id)).fetchone()
            if conflict and (conflict['snapshot_id'] != snapshot_id or conflict['attempt_id'] != attempt_id):
                raise CoachError('Submission ID is already linked to a different snapshot.')
            terminal = self.db.execute("""SELECT verdict FROM judge_results
                WHERE source=? AND kind=? AND submission_id=? AND verdict!='unknown'""",
                (source, kind, submission_id)).fetchone()
            if terminal and verdict != 'unknown' and terminal['verdict'] != verdict:
                raise CoachError('Conflicting terminal verdict for this submission; original evidence is preserved.')
        values = (attempt_id, snapshot_id, source, kind, verdict, submission_id)
        old = self.db.execute('''SELECT * FROM judge_results WHERE attempt_id=? AND snapshot_id=?
            AND source=? AND kind=? AND verdict=? AND submission_id=?''', values).fetchone()
        if old:
            if old['runtime_ms'] != runtime_ms or old['memory_mb'] != memory_mb:
                raise CoachError('Conflicting duplicate judge result; preserve the original evidence.')
            return dict(old)
        result_id = self.db.execute('''INSERT INTO judge_results(attempt_id,snapshot_id,source,kind,verdict,submission_id,at,runtime_ms,memory_mb)
            VALUES (?,?,?,?,?,?,?,?,?)''', (*values, self.now(), runtime_ms, memory_mb)).lastrowid
        self.event(attempt_id, 'judge', {'result_id': result_id})
        return dict(self.db.execute('SELECT * FROM judge_results WHERE id=?', (result_id,)).fetchone())

    def acceptance(self, attempt_id):
        rows = self.db.execute("""SELECT * FROM judge_results WHERE attempt_id=? AND kind='submission'
            AND source IN ('mcp','user-reported') AND verdict='accepted' ORDER BY id""", (attempt_id,)).fetchall()
        return {'accepted': bool(rows), 'verified': any(r['source'] == 'mcp' for r in rows),
                'sources': sorted({r['source'] for r in rows}), 'snapshot_ids': sorted({r['snapshot_id'] for r in rows})}

    @write
    def finish(self, attempt_id, outcome):
        choice(outcome, ('accepted', 'unsolved', 'abandoned'), 'Outcome')
        row = self.row(attempt_id)
        if row['state'] == 'finished':
            if row['outcome'] != outcome:
                raise CoachError('Attempt already finished with a different outcome; history is preserved.')
            return self.attempt(attempt_id)
        if outcome == 'accepted' and not self.acceptance(attempt_id)['accepted']:
            raise CoachError('Record accepted submission evidence before finishing as accepted.')
        at = self.now()
        last = self.db.execute('SELECT ended_at FROM intervals WHERE attempt_id=? ORDER BY id DESC LIMIT 1', (attempt_id,)).fetchone()
        if at < row['started_at'] or (last['ended_at'] and at < last['ended_at']):
            raise CoachError('Clock moved backwards; correct the clock before finishing.')
        if row['state'] == 'running':
            self.close_interval(attempt_id, at)
        self.db.execute("UPDATE attempts SET state='finished', finished_at=?, outcome=? WHERE id=?", (at, outcome, attempt_id))
        self.event(attempt_id, 'finish', {'outcome': outcome}, at)
        self.schedule(attempt_id)
        return self.attempt(attempt_id)

    def schedule(self, attempt_id):
        row = self.row(attempt_id)
        if row['state'] != 'finished':
            return
        interval = 1
        if row['outcome'] == 'accepted' and self.independent(attempt_id) and row['teach_back']:
            interval = 30 if row['is_review'] else 7
        due = row['review_override'] or (datetime.fromisoformat(row['finished_at']).date() + timedelta(days=interval)).isoformat()
        self.db.execute('UPDATE attempts SET review_date=? WHERE id=?', (due, attempt_id))

    @write
    def feedback(self, attempt_id, data, *, teach_back=False, independent=False, review_date=None):
        row = self.row(attempt_id)
        if row['state'] != 'finished':
            raise CoachError('Finish solve timing before saving the debrief.')
        if not isinstance(data, dict) or not data or set(data) - FEEDBACK_FIELDS:
            raise CoachError('Feedback must be an object containing only the documented feedback fields.')
        if type(teach_back) is not bool:
            raise CoachError('Teach-back must be a boolean.')
        if type(independent) is not bool:
            raise CoachError('Independence confirmation must be a boolean.')
        if independent and row['hint_level']:
            raise CoachError('Cannot confirm independence when assistance is recorded.')
        for key, value in data.items():
            if key == 'mistakes':
                if not isinstance(value, list) or len(value) > 30:
                    raise CoachError('Mistakes must be a list of at most 30 strings.')
                for mistake in value:
                    text(mistake, 'Mistake', 120)
            else:
                text(value, f'Feedback {key}', 6000)
        if review_date is not None:
            try:
                if date.fromisoformat(review_date).isoformat() != review_date:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise CoachError('Review date must be YYYY-MM-DD.') from exc
        self.db.execute('INSERT INTO feedback VALUES (?, ?, ?) ON CONFLICT(attempt_id) DO UPDATE SET at=excluded.at,data=excluded.data',
                        (attempt_id, self.now(), json.dumps(data)))
        self.db.execute('UPDATE attempts SET teach_back=?, review_override=COALESCE(?,review_override) WHERE id=?',
                        (teach_back, review_date, attempt_id))
        self.event(attempt_id, 'feedback', {'feedback': data, 'teach_back': teach_back,
                                          'independent': independent, 'review_date': review_date})
        self.schedule(attempt_id)
        return self.attempt(attempt_id)

    def independent(self, attempt_id):
        latest = self.db.execute("SELECT data FROM events WHERE attempt_id=? AND kind='feedback' ORDER BY id DESC LIMIT 1",
                                 (attempt_id,)).fetchone()
        return bool(latest and json.loads(latest['data']).get('independent') is True
                    and self.row(attempt_id)['hint_level'] == 0)

    @write
    def end_session(self, summary=''):
        text(summary, 'Session summary', 6000, empty=True)
        if self.db.execute("SELECT id FROM attempts WHERE state IN ('running','paused')").fetchone():
            raise CoachError('Finish the open attempt before ending the session.')
        row = self.db.execute('SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1').fetchone()
        if row is None:
            raise CoachError('No open session.')
        self.db.execute('UPDATE sessions SET ended_at=?,summary=? WHERE id=?', (self.now(), summary, row['id']))
        return dict(self.db.execute('SELECT * FROM sessions WHERE id=?', (row['id'],)).fetchone())

    def attempt(self, attempt_id):
        result = dict(self.row(attempt_id))
        problem = dict(self.db.execute('SELECT * FROM problems WHERE slug=?', (result['slug'],)).fetchone())
        if result['state'] == 'finished':
            problem['tags'] = json.loads(problem['tags'])
        else:
            problem.pop('tags')
        result['problem'] = problem
        now = self.now()
        intervals = [dict(r) for r in self.db.execute('SELECT * FROM intervals WHERE attempt_id=? ORDER BY id', (attempt_id,))]
        totals = dict.fromkeys(PHASES, 0)
        invalid = False
        for interval in intervals:
            elapsed = (datetime.fromisoformat(interval['ended_at'] or now) - datetime.fromisoformat(interval['started_at'])).total_seconds()
            seconds = interval['corrected_seconds'] if interval['corrected_seconds'] is not None else elapsed
            interval['original_seconds'] = elapsed
            interval['seconds'] = seconds if seconds >= 0 else None
            invalid |= seconds < 0
            if seconds >= 0:
                totals[interval['phase']] += seconds
        wall = (datetime.fromisoformat(result['finished_at'] or now) - datetime.fromisoformat(result['started_at'])).total_seconds()
        boundary = datetime.fromisoformat(result['finished_at'] or now)
        clock_error = invalid or wall < 0 or any(
            interval['ended_at'] and datetime.fromisoformat(interval['ended_at']) > boundary
            for interval in intervals)
        result['timing'] = {'phase_seconds': {k: round(v, 3) for k, v in totals.items()} if not invalid else dict.fromkeys(PHASES),
                            'active_seconds': round(sum(totals.values()), 3) if not invalid else None,
                            'wall_seconds': round(wall, 3) if wall >= 0 else None,
                            'confirmed': bool(result['timing_confirmed']) and not clock_error,
                            'clock_error': bool(clock_error)}
        result['intervals'] = intervals
        result['events'] = [{**dict(r), 'data': json.loads(r['data'])} for r in self.db.execute('SELECT * FROM events WHERE attempt_id=? ORDER BY id', (attempt_id,))]
        result['snapshots'] = [dict(r) for r in self.db.execute('SELECT id,created_at,language,sha256 FROM snapshots WHERE attempt_id=? ORDER BY id', (attempt_id,))]
        result['judge_results'] = [dict(r) for r in self.db.execute('SELECT * FROM judge_results WHERE attempt_id=? ORDER BY id', (attempt_id,))]
        feedback = self.db.execute('SELECT data FROM feedback WHERE attempt_id=?', (attempt_id,)).fetchone()
        result['feedback'] = json.loads(feedback['data']) if feedback else None
        result['acceptance'] = self.acceptance(attempt_id)
        result['independent'] = self.independent(attempt_id)
        result['assistance'] = 'assisted' if result['hint_level'] else ('independent' if result['independent'] else 'unconfirmed')
        return result

    def status(self):
        attempts = [self.attempt(r['id']) for r in self.db.execute('SELECT id FROM attempts ORDER BY id')]
        latest = {}
        for attempt in attempts:
            latest[attempt['slug']] = attempt
        today = datetime.fromisoformat(self.now()).date().isoformat()
        due = [{'slug': a['slug'], 'title': a['problem']['title'], 'review_date': a['review_date'], 'last_attempt_id': a['id']}
               for a in latest.values() if a['state'] == 'finished' and a['review_date'] <= today]
        return {'active': next((a for a in attempts if a['state'] != 'finished'), None),
                'attempts': attempts, 'due_reviews': sorted(due, key=lambda a: (a['review_date'], a['slug'])),
                'sessions': [dict(r) for r in self.db.execute('SELECT * FROM sessions ORDER BY id')]}

    def backup(self, destination):
        return {'path': self.store.backup(destination)}

    @staticmethod
    def restore(root, source):
        return {'path': Store.restore(root, source)}
