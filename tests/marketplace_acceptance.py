"""Exercise installed native File RAG through the real three-tool MCP interface."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
source = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix='file-rag-market-') as temp:
    home = Path(temp)
    def cli(*args, collection='global', ok=True):
        result = subprocess.run([binary,'--home',str(home),'--collection',collection,*map(str,args)],text=True,capture_output=True,timeout=60)
        assert (result.returncode == 0) == ok, result.stderr
        return json.loads(result.stdout if ok else result.stderr)
    bundle=home/'file-rag.rhyven.json'
    cli('app','package',source,'--out',bundle)
    assert cli('install',bundle,ok=False)['code']=='permission_review_required'
    cli('install',bundle,'--accept-permissions')
    process=subprocess.Popen([binary,'--home',str(home),'mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    counter=0
    def rpc(method,params):
        global counter
        counter+=1
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n');process.stdin.flush()
        response=json.loads(process.stdout.readline());assert 'error' not in response,response
        return response['result']
    def call(action,**args):
        result=rpc('tools/call',{'name':'rhyven_call','arguments':{'category':'rhyven/file-rag','function':'action_'+action,'args':dict(repository='demo',**args)}})
        assert not result.get('isError'),result
        return json.loads(result['content'][0]['text'])
    try:
        rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'file-rag-test','version':'1'}})
        process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');process.stdin.flush()
        assert len(rpc('tools/list',{})['tools'])==3
        call('put_files',files=[{'path':'src/cache.py','content':'def cacheLookup(key): return key\n'},{'path':'.gitignore','content':'drafts/\n'},{'path':'drafts/hidden.py','content':'cache secret draft'},{'path':'other.txt','content':'unrelated bananas'}])
        work=call('summarize')
        assert all(not item['id'].startswith('drafts/') for item in work['items'])
        summary=[]
        for item in work['items']:
            data=call('read_file',path=item['id'])
            summary.append(dict(item,summary='Cache lookup function' if item['id'].endswith('cache.py') else 'Other project text'))
            assert data['sha256']==item['sha256']
        call('index',summaries=summary)
        assert call('summary_queue')['items']==[]
        results=call('search',query='cache lookup',content=True)['results']
        assert results[0]['path']=='src/cache.py' and not results[0]['stale']
        assert 'def cacheLookup' in results[0]['content']
        call('put_files',files=[{'path':'src/cache.py','content':'def cacheLookup(key): return key.upper()\n'}])
        assert call('search',query='cache')['results'][0]['stale']
        assert call('summarize')['items'][0]['id']=='src/cache.py'
        backup=home/'state.rhyven';cli('backup','global','--out',backup)
        cli('restore',backup,'--accept-permissions',collection='restored')
        cli('remove','rhyven/file-rag',collection='restored')
        cli('install',bundle,'--accept-permissions',collection='restored')
        args=json.dumps({'category':'rhyven/file-rag','function':'action_search','args':{'repository':'demo','query':'cache'}})
        assert cli('call','rhyven_call',args,collection='restored')['results'][0]['path']=='src/cache.py'
        cli('install',bundle,'--accept-permissions',collection='isolated')
        assert cli('call','rhyven_call',args,collection='isolated',ok=False)['code']=='app_error'
        print('PASS native Wobbegong: consent, MCP, ignore rules, caller summaries, BM25, stale hashes, recovery, retained state and collection isolation')
    finally:
        process.stdin.close();process.wait(timeout=5)
