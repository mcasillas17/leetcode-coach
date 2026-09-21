import sys
import os
import time
import unittest

from scripts.check_mcp import ProbeError, probe


FAKE = '''
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg: continue
    if msg['method'] == 'initialize':
        result = {'protocolVersion':'2024-11-05','serverInfo':{'name':'fixture','version':'1'},'capabilities':{}}
    elif msg['method'] == 'tools/list':
        result = {'tools':[{'name':'get_problem','inputSchema':{'type':'object','properties':{'titleSlug':{'type':'string'}},'required':['titleSlug']}}]}
    else:
        result = {'content':[{'type':'text','text':json.dumps({'title':'Two Sum','titleSlug':'two-sum'})}]}
    print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}), flush=True)
'''


class ProbeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Process groups are POSIX-specific')
    def test_exited_launcher_cannot_leave_inherited_stdout_hanging(self):
        launcher = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'])"
        started = time.monotonic()
        with self.assertRaises(ProbeError):
            probe([sys.executable, '-c', launcher], timeout=0.1)
        self.assertLess(time.monotonic() - started, 2)

    def test_protocol_handshake_tool_schema_and_public_lookup(self):
        result = probe([sys.executable, '-c', FAKE], problem='two-sum', timeout=2)
        self.assertEqual(result['server']['name'], 'fixture')
        self.assertEqual(result['tools'][0]['name'], 'get_problem')
        self.assertEqual(result['problem']['title'], 'Two Sum')

    def test_pinned_server_wraps_problem_payload(self):
        fake = FAKE.replace("{'title':'Two Sum','titleSlug':'two-sum'}", "{'titleSlug':'two-sum','problem':{'title':'Two Sum','difficulty':'Easy'}}")
        result = probe([sys.executable, '-c', fake], problem='two-sum', timeout=2)
        self.assertEqual(result['problem']['title'], 'Two Sum')

    def test_server_exit_and_timeout_are_errors(self):
        for code in ('pass', 'import time; time.sleep(10)'):
            with self.assertRaises(ProbeError):
                probe([sys.executable, '-c', code], timeout=0.1)

    def test_mcp_tool_error_is_not_reported_as_a_successful_fetch(self):
        fake = FAKE.replace("{'title':'Two Sum','titleSlug':'two-sum'}", "{'error':'unavailable'}")
        with self.assertRaisesRegex(ProbeError, 'problem'):
            probe([sys.executable, '-c', fake], problem='two-sum', timeout=2)


if __name__ == '__main__':
    unittest.main()
