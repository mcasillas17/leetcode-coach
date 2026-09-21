"""Snapshot-bound, durable judge operations. Lost POST responses are never retried."""

import hashlib
import json
from pathlib import Path
import uuid

from .credentials import load_credentials
from .leetcode_judge import JudgeError, LeetCodeJudge, normalize_result
from .tracker import Tracker, text


class JudgeService:
    def __init__(self, root):
        self.root = Path(root)
        self.api = LeetCodeJudge()

    @staticmethod
    def _operations(tracker):
        operations = {}
        for row in tracker.db.execute("SELECT data FROM events WHERE kind='remote_judge' ORDER BY id"):
            operation = json.loads(row['data'])
            operations[operation['operation_id']] = operation
        return operations

    def _lookup(self, operation_id):
        try:
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise JudgeError('Use the local operation_id returned by run_code or submit_solution.') from None
        with Tracker(self.root) as tracker:
            operation = self._operations(tracker).get(operation_id)
        if operation is None:
            raise JudgeError('Judge operation not found in this workspace.')
        return operation

    def _record(self, operation):
        with Tracker(self.root) as tracker, tracker.store.transaction():
            tracker.event(operation['attempt_id'], 'remote_judge', operation)
        return operation

    async def start(self, attempt_id, snapshot_id, kind, data_input=''):
        import anyio
        if kind not in ('submission', 'test'):
            raise JudgeError('Unknown judge operation.')
        text(data_input, 'Test input', 100_000, empty=True)
        if kind == 'submission' and data_input:
            raise JudgeError('Submissions do not accept custom test input.')
        key = hashlib.sha256(f'{snapshot_id}:{kind}:{data_input}'.encode()).hexdigest()
        with Tracker(self.root) as tracker:
            attempt = tracker.attempt(attempt_id)
            snapshot = tracker.snapshot_info(snapshot_id)
            if snapshot['attempt_id'] != attempt_id:
                raise JudgeError('Snapshot belongs to a different attempt.')
            for operation in self._operations(tracker).values():
                if operation['request_key'] == key:
                    return operation
            if attempt['state'] == 'finished':
                raise JudgeError('Start a new practice attempt before sending more code.')
            if attempt['problem']['url'] != f"https://leetcode.com/problems/{attempt['slug']}/":
                raise JudgeError('Authenticated judging currently supports leetcode.com only.')
            code = tracker.snapshot_content(snapshot_id).decode('utf-8')
        credentials = await anyio.to_thread.run_sync(load_credentials)
        question_id = await self.api.question_id(attempt['slug'], attempt['problem']['frontend_id'], snapshot['language'])
        await anyio.lowlevel.checkpoint()
        with Tracker(self.root) as tracker, tracker.store.transaction():
            for operation in self._operations(tracker).values():
                if operation['request_key'] == key:
                    return operation
            row = tracker.row(attempt_id)
            if row['state'] not in ('running', 'paused'):
                raise JudgeError('Attempt was finished while preparing the request. No code was sent.')
            if row['state'] == 'running':
                at = tracker.now()
                tracker.close_interval(attempt_id, at)
                tracker.db.execute("UPDATE attempts SET state='paused' WHERE id=?", (attempt_id,))
                tracker.event(attempt_id, 'pause', {'reason': 'judge'}, at)
            operation = {'operation_id': str(uuid.uuid4()), 'request_key': key, 'attempt_id': attempt_id,
                         'snapshot_id': snapshot_id, 'sha256': snapshot['sha256'], 'slug': attempt['slug'],
                         'kind': kind, 'state': 'unknown', 'remote_id': None,
                         'message': 'Request reserved. If interrupted, do not resend automatically; inspect LeetCode history.'}
            tracker.event(attempt_id, 'remote_judge', operation)
        # The durable reservation precedes POST. Cancellation/crash at any point
        # leaves an unknown operation, preventing duplicate sends after restart.
        try:
            identifier = await self.api.start(attempt['slug'], question_id, snapshot['language'], code,
                                              kind, credentials, data_input)
        except JudgeError as exc:
            return self._record({**operation, 'message': str(exc)})
        return self._record({**operation, 'remote_id': identifier, 'state': 'pending', 'message': 'Judge request started.',
                             'poll_after_seconds': 2})

    async def status(self, operation_id):
        import anyio
        operation = self._lookup(operation_id)
        if operation['state'] == 'completed' or not operation['remote_id']:
            return operation
        credentials = await anyio.to_thread.run_sync(load_credentials)
        response = await self.api.check(operation['remote_id'], operation['kind'], operation['slug'], credentials)
        result = normalize_result(response, credentials)
        # Re-read under the write lock: a concurrent poll may have completed.
        # Evidence and operation state commit together, including across crashes.
        with Tracker(self.root) as tracker, tracker.store.transaction():
            operation = self._operations(tracker)[operation_id]
            if operation['state'] == 'completed':
                return operation
            if result['state'] == 'pending':
                return {**operation, **result}
            updated = {**operation, **result}
            if result['state'] == 'completed':
                tracker._record_judge(operation['attempt_id'], operation['snapshot_id'], 'mcp', result['verdict'],
                                      kind=operation['kind'], submission_id=operation['remote_id'],
                                      runtime_ms=result['runtime_ms'], memory_mb=result['memory_mb'])
                updated['message'] = 'Judge result recorded for the frozen snapshot.'
                updated.pop('poll_after_seconds', None)
            else:
                updated['message'] = 'Judge result remains unknown. Poll again or inspect LeetCode; do not resend.'
            tracker.event(operation['attempt_id'], 'remote_judge', updated)
            return updated
