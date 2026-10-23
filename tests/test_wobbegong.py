import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wobbegong_compat', APP / 'file_rag.py')
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)


def legacy_index(directory, source):
    """Version-1 layout published by File RAG 0.2.0, including its old DB name."""
    gen = directory / 'gen-legacy'
    gen.mkdir(parents=True)
    (directory / 'CURRENT').write_text(gen.name + '\n')
    (gen / 'config.json').write_text(json.dumps({'version': 1, 'exclude': []}))
    (gen / 'metadata.json').write_text(json.dumps([{
        'id': 'cache.py', 'path': 'cache.py', 'folder': '.',
        'summary': 'Previously cached summary',
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    }]))
    with sqlite3.connect(gen / 'bm25.sqlite') as db:
        db.executescript('''CREATE TABLE lengths(doc TEXT, field TEXT, length INTEGER, PRIMARY KEY(doc,field));
            CREATE TABLE postings(term TEXT, doc TEXT, field TEXT, tf INTEGER, PRIMARY KEY(term,doc,field)) WITHOUT ROWID;
            CREATE TABLE stats(term TEXT PRIMARY KEY, df INTEGER);''')
        for field, size in [('path', 2), ('folder', 0), ('summary', 3), ('content', 1)]:
            db.execute('INSERT INTO lengths VALUES(?,?,?)', ('cache.py', field, size))
        db.execute("INSERT INTO postings VALUES('legacytoken','cache.py','content',1)")
        db.execute("INSERT INTO stats VALUES('legacytoken',1)")


class WobbegongTests(unittest.TestCase):
    def cli(self, *args):
        output = subprocess.check_output([sys.executable, str(APP / 'wobbegong.py'), *map(str, args)])
        return json.loads(output)

    def test_new_command_uses_wobbegong_storage_and_skips_internal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'; root.mkdir()
            (root / 'cache.py').write_text('cache lookup works')
            self.cli('index', '--root', root, '--no-summaries')
            directory = root / '.wobbegong'
            self.assertTrue((rag.generation(directory) / 'wobbegong.db').is_file())
            self.assertEqual(self.cli('search', 'cache', '--root', root)[0]['path'], 'cache.py')
            (directory / 'private.txt').write_text('internalindexsecret')
            alternate = Path(tmp) / 'alternate'
            self.cli('index', '--root', root, '--index-dir', alternate, '--hidden', '--no-summaries')
            self.assertEqual(list(rag.metadata(rag.generation(alternate))), ['cache.py'])

    def test_legacy_standalone_cache_is_read_and_its_summary_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'cache.py'; source.write_text('legacytoken')
            directory = root / '.file-rag'; legacy_index(directory, source)
            result = self.cli('search', 'legacytoken', '--root', root)[0]
            self.assertFalse(result['stale'])
            self.assertEqual(result['summary'], 'Previously cached summary')
            self.assertEqual(self.cli('index', '--root', root, '--no-summaries')['summaries_reused'], 1)
            self.assertTrue((rag.generation(directory) / 'wobbegong.db').is_file())
            self.assertFalse((root / '.wobbegong').exists())

    def test_legacy_app_root_and_scoped_caches_keep_their_summaries(self):
        for scope in ['.', 'project']:
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp)
                root = data / 'demo' / 'sources'
                if scope != '.': root = root / scope
                root.mkdir(parents=True)
                source = root / 'cache.py'; source.write_text('legacytoken')
                base = data / 'demo'
                directory = base / 'index' if scope == '.' else base / 'scopes' / rag.sha(scope.encode())
                legacy_index(directory, source)
                # A new scoped directory must not hide an existing root cache.
                (base / '.wobbegong' / 'scopes').mkdir(parents=True)
                with patch.dict(os.environ, RHYVEN_DATA_DIR=str(data)):
                    response = rag.handle({'protocol': 'rhyven.action/1', 'category': 'rhyven/file-rag', 'function': 'action_summarize',
                                           'args': {'repository': 'demo', 'root': scope}})['result']
                self.assertEqual(response['summaries_reused'], 1)
                self.assertEqual(response['items'], [])
                self.assertTrue((rag.generation(directory) / 'wobbegong.db').is_file())


if __name__ == '__main__':
    unittest.main()
