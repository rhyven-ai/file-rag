import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rag', APP / 'file_rag.py')
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)


class RagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'src'
        self.root.mkdir()
        self.index = self.base / 'index'
        self.index.mkdir()
        (self.root / 'cache.py').write_text('def cacheRouter():\n    return "cache routing"\n')
        (self.root / 'other.txt').write_text('unrelated bananas')

    def build(self, *options, supplied=None):
        args = rag.parser().parse_args(['index', *options])
        with rag.lock(self.index):
            return rag.build(self.root, self.index, args, supplied)

    def search(self, *options):
        args = rag.parser().parse_args(['search', 'cache', *options])
        with rag.lock(self.index, False):
            return rag.search(self.root, self.index, args)

    def test_llm_cache_changed_deleted_and_metadata(self):
        with patch.object(rag, 'llm_summary', return_value='Request routing') as model:
            self.assertEqual(self.build()['summaries_updated'], 2)
            self.assertEqual(self.build()['summaries_reused'], 2)
            self.assertEqual(model.call_count, 2)
            (self.root / 'cache.py').write_text('cache changed')
            (self.root / 'other.txt').unlink()
            result = self.build()
            self.assertEqual(result['summaries_updated'], 1)
            self.assertEqual(result['removed'], 1)
        docs = rag.metadata(rag.generation(self.index))
        self.assertEqual(set(docs['cache.py']), {'id','path','folder','summary','sha256'})
        self.assertEqual(len(self.search()), 1)
        self.assertNotIn('content', self.search()[0])

    def test_offline_can_later_fill_summaries(self):
        self.assertEqual(self.build('--no-summaries')['summaries_missing'], 2)
        with patch.object(rag, 'llm_summary', return_value='Summary') as model:
            self.assertEqual(self.build()['summaries_updated'], 2)
            self.assertEqual(model.call_count, 2)

    def test_failure_preserves_generation(self):
        self.build('--no-summaries')
        old = rag.generation(self.index)
        with self.assertRaises(ValueError):
            self.build(supplied={'cache.py': {'sha256': 'wrong', 'summary': 'Cache'}})
        self.assertEqual(rag.generation(self.index), old)
        self.assertEqual(len(list(self.index.glob('gen-*'))), 1)
        self.assertEqual(self.search()[0]['id'], 'cache.py')

    def test_stale_missing_and_symlink(self):
        self.build('--no-summaries')
        (self.root / 'cache.py').write_text('new content')
        result = self.search('--content')[0]
        self.assertTrue(result['stale'])
        self.assertEqual(result['content'], 'new content')
        (self.root / 'cache.py').unlink()
        (self.root / 'cache.py').symlink_to(self.root / 'other.txt')
        self.assertEqual(self.search(), [])
        with self.assertRaises(ValueError):
            rag.read_source(self.root, '../outside', 100)

    def test_filter_order_dedup_and_validation(self):
        (self.root / 'other.txt').write_text('cache bananas')
        self.build('--no-summaries')
        with patch.object(rag, 'relevance_filter', side_effect=lambda q,c: [c[-1],c[-1],c[0]]):
            result = self.search('--top-k', '1')
            self.assertEqual(result[0]['id'], 'other.txt')
        with patch.object(rag, 'relevance_filter', return_value=[{'id':'invented'}]):
            with self.assertRaises(ValueError): self.search()
        with patch.object(rag, 'relevance_filter', side_effect=lambda q,c: [dict(c[0], score=float('nan'))]):
            with self.assertRaises(ValueError): self.search()

    def test_weights_and_binary_skips(self):
        (self.root / 'binary').write_bytes(b'cache\0')
        (self.root / 'bad').write_bytes(b'\xffcache')
        (self.root / 'target').mkdir()
        (self.root / 'target' / 'generated').write_text('cache')
        self.assertEqual(self.build('--no-summaries')['files'], 2)
        self.assertEqual(self.search('--weight','path=0','--weight','folder=0','--weight','summary=0','--weight','content=0'), [])

    def test_real_http_chunking_and_reuse(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'choices':[{'message':{'content':'cache summary'}}]}).encode())
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (self.root / 'cache.py').write_text('cache ' * 800)
            opts = ['--base-url',f'http://127.0.0.1:{server.server_port}/v1','--model','test','--chunk-chars','2000']
            self.build(*opts)
            count = len(requests)
            self.assertGreater(count, 3)
            self.build(*opts)
            self.assertEqual(len(requests), count)
            self.assertTrue(all(p == '/v1/chat/completions' for p,b in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_gitignore_nested_negation_directories_and_extra_excludes(self):
        entries = {
            '.gitignore': '*.log\n!keep.log\n/root-only.txt\nignored/\n!ignored/keep.txt\n**/generated/**\n\\#literal\n',
            'drop.log': 'cache', 'keep.log': 'cache', 'root-only.txt': 'cache',
            'nested/root-only.txt': 'cache', 'nested/.gitignore': '!local.log\nprivate.txt\n',
            'nested/local.log': 'cache', 'nested/drop.log': 'cache', 'nested/private.txt': 'cache',
            'ignored/keep.txt': 'cache', 'nested/generated/a.txt': 'cache', '#literal': 'cache',
            'drafts/skip.txt': 'cache', 'deep/drafts/skip.txt': 'cache',
            'auto.generated.py': 'cache', 'deep/auto.generated.py': 'cache',
            '.venvs/env/lib.py': 'cache', 'custom-env/pyvenv.cfg': 'home = /usr/bin',
            'custom-env/lib.py': 'cache', 'nested/good.py': 'cache',
        }
        for name, content in entries.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.build('--no-summaries', '--hidden', '--exclude', '**/drafts/**',
                   '--exclude', '**/*.generated.py')
        names = set(rag.metadata(rag.generation(self.index)))
        self.assertEqual(names, {'cache.py', 'other.txt', '.gitignore', 'keep.log',
                                'nested/root-only.txt', 'nested/.gitignore',
                                'nested/local.log', 'nested/good.py'})
        # Caller exclusions always win, even when .gitignore reincludes a file.
        self.build('--no-summaries', '--exclude', '*.log')
        self.assertNotIn('keep.log', rag.metadata(rag.generation(self.index)))

    def test_cli_summarize_positional_root(self):
        proc = subprocess.run([sys.executable, str(APP / 'file_rag.py'), 'summarize',
                               str(self.root), '--no-summaries', '--exclude', 'other.txt'],
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['files'], 1)

    def test_rhyven_scoped_summarize_workflow(self):
        files = [{'path': p, 'content': c} for p, c in {
            'project/cache.py': 'cache routing', 'project/skip.py': 'cache skip',
            'project/.gitignore': '*.log\n', 'project/private.log': 'cache private',
            'other/keep.py': 'cache sibling'}.items()]
        self.assertIn('result', self.call('put_files', files=files))
        response = self.call('summarize', root='project/', exclude=['skip.py', '.gitignore'])['result']
        self.assertEqual(response['root'], 'project')
        self.assertEqual(response['files'], 1)
        self.assertEqual([d['id'] for d in response['items']], ['cache.py'])
        item = response['items'][0]
        self.assertEqual(self.call('read_file', root='project/', path=item['id'])['result']['content'], 'cache routing')
        result = self.call('index', root='project', summaries=[dict(item, summary='Cache routing')])['result']
        self.assertEqual(result['files'], 1)  # Saved exclusions survive follow-up calls.
        self.assertEqual(self.call('summarize', root='project')['result']['items'], [])
        self.assertEqual(self.call('search',root='project',query='cache')['result']['results'][0]['id'], 'cache.py')
        self.call('summarize',root='other')
        self.assertEqual(self.call('summary_queue',root='project')['result']['items'], [])
        self.assertEqual(self.call('search',root='other',query='cache')['result']['results'][0]['id'], 'keep.py')
        self.call('put_files',files=[{'path':'project/cache.py','content':'cache changed'}])
        self.assertEqual(len(self.call('summarize', root='project')['result']['items']), 1)
        self.assertEqual(self.call('summarize', root='project', exclude=[])['result']['files'], 3)
        for root in ['../escape', '/', '/project', 'missing']:
            self.assertIn('error', self.call('summarize',root=root))
        self.assertIn('error', self.call('summarize',root='project',exclude=['!secret']))

    def call(self, action, **args):
        env = dict(os.environ, RHYVEN_DATA_DIR=str(self.base / 'data'))
        request = dict(protocol='rhyven.container/1', category='rhyven/file-rag',
                       function='action_' + action, args=dict(repository='test', **args))
        proc = subprocess.run([sys.executable, str(APP / 'file_rag.py'), 'rhyven'],
                              input=json.dumps(request)+'\n', text=True, capture_output=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        response = json.loads(proc.stdout)
        if 'result' in response:
            manifest = json.loads((APP / 'app.json').read_text())
            rag.validate_input(response['result'], manifest['actions'][action]['output'])
        return response

    def test_rhyven_roundtrip_and_stale_summary(self):
        self.assertEqual(self.call('put_files', files=[{'path':'src/cache.py','content':'cache routing'}])['result']['files'],1)
        queued = self.call('summary_queue')['result']['items']
        self.assertEqual(len(queued), 1)
        self.assertEqual(self.call('read_file',path='src/cache.py')['result']['content'], 'cache routing')
        summary = dict(queued[0],summary='Request routing cache')
        self.assertEqual(self.call('index', summaries=[summary])['result']['summaries_updated'],1)
        self.assertEqual(self.call('summary_queue')['result']['items'],[])
        results = self.call('search',query='cache',content=True)['result']['results']
        self.assertEqual(len(results),1)
        self.assertEqual(self.call('search',query='--help')['result']['results'], [])
        self.assertFalse(results[0]['stale'])
        self.call('put_files', files=[{'path':'src/cache.py','content':'cache changed'}])
        self.assertIn('error',self.call('index',summaries=[summary]))
        self.assertTrue(self.call('search',query='cache')['result']['results'][0]['stale'])
        self.assertEqual(self.call('index')['result']['summaries_missing'],1)
        self.call('put_files', files=[],delete=['src/cache.py'])
        self.assertEqual(self.call('index')['result']['removed'],1)

    def test_rhyven_rejects_paths_and_untrusted_options(self):
        for path in ['../escape','/absolute','a/../b','a//b']:
            self.assertIn('error',self.call('put_files',files=[{'path':path,'content':'x'}]))
        self.assertIn('error',self.call('search',query='x',filter='/tmp/evil.py:f'))
        self.assertIn('error',self.call('put_files',files=[{'path':'a','content':'x'},{'path':'a/b','content':'y'}]))
        self.assertEqual(self.call('summary_queue')['result']['items'],[])


if __name__ == '__main__':
    unittest.main()
