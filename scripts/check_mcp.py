"""Smoke-test the pinned LeetCode server without credentials or submissions."""

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time


PACKAGE = '@jinzcdev/leetcode-mcp-server@1.4.0'


class ProbeError(RuntimeError):
    pass


def probe(command, problem=None, timeout=30):
    environment = {**os.environ, 'LEETCODE_SESSION': '', 'LEETCODE_SITE': 'global'}
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                               env=environment, start_new_session=os.name == 'posix')
    messages = queue.Queue()

    def read_stdout():
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and message.get('jsonrpc') == '2.0':
                    messages.put(message)
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    request_id = 0

    def send(message):
        try:
            process.stdin.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProbeError('MCP server exited before completing the request.') from exc

    def request(method, params=None):
        nonlocal request_id
        request_id += 1
        send({'id': request_id, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise ProbeError(f'MCP {method} timed out.') from exc
            if message is None:
                raise ProbeError(f'MCP server exited during {method}.')
            if message.get('id') == request_id:
                if 'error' in message or not isinstance(message.get('result'), dict):
                    raise ProbeError(f'MCP {method} returned an error or malformed result.')
                return message['result']

    try:
        initialized = request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                             'clientInfo': {'name': 'leetcode-coach-check', 'version': '1'}})
        send({'method': 'notifications/initialized'})
        listing = request('tools/list')
        tools = listing.get('tools')
        if not isinstance(tools, list) or not tools:
            raise ProbeError('MCP tool listing is empty or malformed.')
        result = {'package': PACKAGE, 'server': initialized.get('serverInfo'),
                  'protocol': initialized.get('protocolVersion'),
                  'tools': [{'name': tool['name'], 'inputSchema': tool.get('inputSchema')} for tool in tools]}
        if problem:
            response = request('tools/call', {'name': 'get_problem', 'arguments': {'titleSlug': problem}})
            if response.get('isError'):
                raise ProbeError('MCP problem retrieval failed; initialization may still be working.')
            payloads = []
            for block in response.get('content', []):
                if block.get('type') == 'text':
                    try:
                        payloads.append(json.loads(block['text']))
                    except (json.JSONDecodeError, KeyError):
                        continue
            data = next((p for p in payloads if isinstance(p, dict) and p.get('title') and p.get('titleSlug') == problem), None)
            if data is None:
                wrapped = next((p for p in payloads if isinstance(p, dict) and p.get('titleSlug') == problem
                                and isinstance(p.get('problem'), dict)), None)
                if wrapped and wrapped['problem'].get('title'):
                    data = {**wrapped['problem'], 'titleSlug': problem}
            if data is None:
                raise ProbeError('MCP problem retrieval returned an error or unrecognized problem metadata.')
            result['problem'] = {key: data.get(key) for key in ('title', 'titleSlug', 'difficulty')}
        return result
    finally:
        def terminate_group(sig):
            try:
                if os.name == 'posix':
                    # npx may exit before the server; its descendants still own the pipes.
                    os.killpg(process.pid, sig)
                elif process.poll() is None:
                    process.kill() if sig == signal.SIGKILL else process.terminate()
            except ProcessLookupError:
                pass
            except PermissionError:
                # macOS may report EPERM for an already-dead process group.
                # Ignore only once both launcher and pipe reader are known to be gone.
                reader.join(timeout=0.1)
                if process.poll() is None or reader.is_alive():
                    raise

        terminate_group(signal.SIGTERM)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            terminate_group(signal.SIGKILL)
            process.wait(timeout=1)
        process.stdin.close()
        reader.join(timeout=1)
        if reader.is_alive():
            # Also stop descendants that ignored TERM after their launcher exited.
            terminate_group(signal.SIGKILL)
            reader.join(timeout=1)
        if reader.is_alive():
            # Never take BufferedReader's lock while its reader is stuck in read().
            raise ProbeError('MCP child retained stdout after bounded process cleanup.')
        process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--problem', help='Optionally retrieve public problem metadata by slug')
    args = parser.parse_args()
    try:
        result = probe(['npx', '-y', PACKAGE, '--site', 'global'], args.problem)
        print(json.dumps(result, indent=2))
        return 0
    except (ProbeError, OSError) as exc:
        print(f'MCP check: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
