"""Command-line interface for the user and the repository coaching skill."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .reports import GROUPS, build_report, render_markdown
from .tracker import LANGUAGES, MODES, PHASES, VERDICTS, CoachError, Tracker, choice, text


DEFAULTS = {'language': 'python3', 'communication_language': 'English', 'mode': 'interview', 'endpoint': 'leetcode.com'}


def read_json(path, label):
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(100_001)
        if len(raw) > 100_000:
            raise CoachError(f'{label} exceeds 100 KB.')
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoachError(f'Cannot read {label}; provide a valid UTF-8 JSON file.') from exc
    if not isinstance(data, dict):
        raise CoachError(f'{label} must be a JSON object.')
    return data


def config(root):
    result = dict(DEFAULTS)
    for filename in ('coach.json', 'coach.local.json'):
        path = root / filename
        if path.exists():
            data = read_json(path, 'config')
            if set(data) - set(DEFAULTS):
                raise CoachError('Config contains unknown fields; see coach.json for supported settings.')
            result.update(data)
    choice(result['language'], LANGUAGES, 'Config language')
    choice(result['mode'], MODES, 'Config mode')
    choice(result['endpoint'], ('leetcode.com', 'leetcode.cn'), 'Config endpoint')
    text(result['communication_language'], 'Communication language', 100)
    return result


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--root', type=Path, default=argparse.SUPPRESS, help='Practice workspace (default: this repository)')
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='Emit machine-readable JSON')
    cli = argparse.ArgumentParser(description='Time, record, and review personal LeetCode practice.', parents=[common])
    commands = cli.add_subparsers(dest='command', required=True)

    def command(name, help_text):
        return commands.add_parser(name, help=help_text, parents=[common])

    command('init', 'Initialize private local storage and default configuration')
    command('status', 'Show the current attempt and due reviews')
    p = command('start', 'Start a problem and its reasoning timer')
    p.add_argument('slug')
    p.add_argument('--id', type=int, required=True, dest='frontend_id')
    p.add_argument('--title', required=True)
    p.add_argument('--difficulty', choices=['Easy', 'Medium', 'Hard'], required=True)
    p.add_argument('--tags', nargs='*', default=[])
    p.add_argument('--language', choices=LANGUAGES)
    p.add_argument('--mode', choices=MODES)
    p.add_argument('--review', action='store_true')
    p.add_argument('--file', dest='working_file', help='Existing file relative to workspace root; never overwritten')
    for name, help_text in [('show', 'Inspect an attempt and its evidence'), ('pause', 'Exclude a break or judge wait'),
                            ('resume', 'Resume a paused timer'), ('recover', 'Pause an interrupted attempt and flag its timing'),
                            ('confirm-timing', 'Record the user confirmation of elapsed intervals'),
                            ('snapshot', 'Freeze the saved solution before judging or reviewing')]:
        p = command(name, help_text)
        p.add_argument('attempt', type=int)
        if name == 'pause':
            p.add_argument('--reason', default='break')
    p = command('phase', 'Switch between reasoning, implementation, and debugging')
    p.add_argument('attempt', type=int)
    p.add_argument('phase', choices=PHASES)
    p = command('correct', 'Correct a closed interval while retaining its original duration')
    p.add_argument('attempt', type=int)
    p.add_argument('--interval', type=int, required=True)
    p.add_argument('--seconds', type=float, required=True)
    p.add_argument('--reason', required=True)
    p = command('hint', 'Record assistance actually given')
    p.add_argument('attempt', type=int)
    p.add_argument('--level', type=int, choices=range(1, 6), required=True)
    p.add_argument('--note', required=True)
    p = command('show-snapshot', 'Read the immutable code to send to a judge')
    p.add_argument('snapshot', type=int)
    p = command('judge', 'Record a result, its source, and its code snapshot; does not submit code')
    p.add_argument('attempt', type=int)
    p.add_argument('--snapshot', type=int, required=True)
    p.add_argument('--source', choices=['mcp', 'user-reported', 'local-test'], required=True)
    p.add_argument('--verdict', choices=VERDICTS, required=True)
    p.add_argument('--kind', choices=['submission', 'test'], default='submission')
    p.add_argument('--submission-id')
    p.add_argument('--runtime-ms', type=float)
    p.add_argument('--memory-mb', type=float)
    p = command('finish', 'Stop solve time and record an outcome before debrief')
    p.add_argument('attempt', type=int)
    p.add_argument('--outcome', choices=['accepted', 'unsolved', 'abandoned'], required=True)
    p = command('feedback', 'Save a JSON debrief and schedule the next review')
    p.add_argument('attempt', type=int)
    p.add_argument('--file', type=Path, required=True)
    p.add_argument('--teach-back', action='store_true')
    p.add_argument('--review-date')
    p = command('end-session', 'Close the session after all attempts are finished')
    p.add_argument('--summary', default='')
    p = command('report', 'Show progress or export a Markdown report')
    p.add_argument('--group-by', choices=GROUPS, default='problem')
    p.add_argument('--session', type=int)
    p.add_argument('--output', type=Path, help='Create a new Markdown file; refuses to overwrite')
    for name in ('backup', 'restore'):
        p = command(name, 'Copy a consistent database' if name == 'backup' else 'Restore into a root without an existing database')
        p.add_argument('path', type=Path)
    return cli


def dispatch(tracker, args, settings):
    command = args.command
    if command == 'init':
        path = tracker.root / 'coach.json'
        if not path.exists():
            with path.open('x', encoding='utf-8') as handle:
                handle.write(json.dumps(settings, indent=2) + '\n')
        return {'root': str(tracker.root), 'database': str(tracker.store.path), 'config': settings}
    if command == 'status':
        state = tracker.status()
        # Startup context stays compact even after years of practice.
        return {'config': settings, 'active': state['active'], 'due_reviews': state['due_reviews'],
                'attempt_count': len(state['attempts']), 'latest_session': state['sessions'][-1] if state['sessions'] else None}
    if command == 'start':
        return tracker.start(args.slug, args.frontend_id, args.title, args.difficulty, tags=args.tags,
                             language=args.language or settings['language'], mode=args.mode or settings['mode'],
                             review=args.review, endpoint=settings['endpoint'], working_file=args.working_file)
    if command == 'show':
        return tracker.attempt(args.attempt)
    if command in ('resume', 'recover', 'confirm-timing', 'snapshot'):
        return getattr(tracker, command.replace('-', '_'))(args.attempt)
    if command == 'phase':
        return tracker.phase(args.attempt, args.phase)
    if command == 'pause':
        return tracker.pause(args.attempt, args.reason)
    if command == 'correct':
        return tracker.correct_interval(args.attempt, args.interval, args.seconds, args.reason)
    if command == 'hint':
        return tracker.hint(args.attempt, args.level, args.note)
    if command == 'show-snapshot':
        return {**tracker.snapshot_info(args.snapshot), 'code': tracker.snapshot_content(args.snapshot).decode('utf-8')}
    if command == 'judge':
        return tracker.judge(args.attempt, args.snapshot, args.source, args.verdict, kind=args.kind,
                             submission_id=args.submission_id, runtime_ms=args.runtime_ms, memory_mb=args.memory_mb)
    if command == 'finish':
        return tracker.finish(args.attempt, args.outcome)
    if command == 'feedback':
        return tracker.feedback(args.attempt, read_json(args.file, 'feedback'), teach_back=args.teach_back, review_date=args.review_date)
    if command == 'end-session':
        return tracker.end_session(args.summary)
    if command == 'backup':
        return tracker.backup(args.path)
    if command == 'report':
        report = build_report(tracker, args.group_by, args.session)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with args.output.open('x', encoding='utf-8') as handle:
                    handle.write(render_markdown(report))
            except FileExistsError as exc:
                raise CoachError('Report destination exists; choose a new filename.') from exc
            return {'path': str(args.output.resolve()), 'totals': report['totals']}
        return report
    raise CoachError('Unknown command.')


def main(argv=None):
    args = parser().parse_args(argv)
    root = getattr(args, 'root', Path(__file__).resolve().parents[1]).expanduser().resolve()
    as_json = getattr(args, 'json', False)
    try:
        if args.command == 'restore':
            result = Tracker.restore(root, args.path)
        else:
            settings = config(root)
            with Tracker(root) as tracker:
                result = dispatch(tracker, args, settings)
        if args.command == 'report' and not args.output and not as_json:
            print(render_markdown(result), end='')
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (CoachError, OSError, sqlite3.Error) as exc:
        # State and data errors are concise; programming errors retain their traceback.
        print(f'coach: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
