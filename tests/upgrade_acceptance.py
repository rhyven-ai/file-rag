"""Upgrade a checksum-verified 0.2.0 package to the current native app in temporary state.

Usage: python3 tests/upgrade_acceptance.py RHYVEN PREVIOUS_PACKAGE
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
previous = Path(sys.argv[2]).resolve()
source = Path(__file__).resolve().parents[1]
old = json.loads(previous.read_text())
assert old['name'] == 'rhyven/file-rag' and old['version'] == '0.2.0'

with tempfile.TemporaryDirectory(prefix='wobbegong-upgrade-') as tmp:
    home = Path(tmp)
    def cli(*args):
        return json.loads(subprocess.check_output([binary, '--home', str(home), *map(str, args)]))

    def call(action, **args):
        return cli('call', 'rhyven_call', json.dumps({'category': 'rhyven/file-rag',
            'function': 'action_' + action, 'args': {'repository': 'demo', **args}}))

    cli('install', previous, '--accept-permissions')
    call('put_files', files=[{'path': 'cache.py', 'content': 'cacheTokenUnique root'},
                             {'path': 'project/cache.py', 'content': 'cacheTokenUnique scoped'}])
    for root in ['.', 'project']:
        queued = call('summarize', root=root)
        call('index', root=root, summaries=[{**item, 'summary': 'Cached before rename'} for item in queued['items']])
        assert call('summary_queue', root=root)['items'] == []

    package = home / 'wobbegong.rhyven.json'
    cli('app', 'package', source, '--out', package)
    updated = cli('update', package, '--accept-permissions')
    assert Path(updated['recovery_backup']).is_file()
    description = cli('call', 'describe_app', json.dumps({'app': 'rhyven/file-rag'}))
    assert description['display_name'] == 'Wobbegong' and description['version'] == '0.3.0'
    for root, count in [('.', 2), ('project', 1)]:
        results = call('search', root=root, query='cacheTokenUnique')['results']
        assert len(results) == count and all(item['summary'] == 'Cached before rename' for item in results)
        assert not any(item['stale'] for item in results)
        assert call('summary_queue', root=root)['items'] == []
        assert call('summarize', root=root)['summaries_reused'] == count
    print('PASS: published 0.2.0 to Wobbegong 0.3.0 staged upgrade preserves root/scoped indexes, sources and cached summaries.')
