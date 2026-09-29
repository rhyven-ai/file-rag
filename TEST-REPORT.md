# Local verification — 2026-09-28

- `python3 -m unittest discover -s file-rag/tests -v`: **12 tests passed**.
  Includes real localhost HTTP transport against a deterministic mock model,
  summary reuse and invalidation, chunk reduction, rollback, filtering, stale
  source handling, symlink/path rejection, and Rhyven subprocess protocol calls.
  Added coverage for scoped summarization through MCP, saved exclusions and
  independent root indexes, positional CLI roots, nested Git ignore patterns and
  negation, additive exclusion patterns, and virtual-environment directories.
  Successful action responses are checked against their manifest output schemas.
- `python3 -m py_compile file-rag/file_rag.py`: passed.
- Existing sibling Rhyven binary, `app validate file-rag`: **valid: true**.
  Runtime state for validation was isolated under `/tmp/file-rag-rhyven-home`.
- No writes were made to the sibling Rhyven project. No Razorback source or
  architecture changes were made. Cargo checks do not apply to this Python app.
- No real external LLM was contacted. Model quality remains provider-dependent.
- Docker build, image packaging, and Rhyven's container-executed app tests were
  **not run**: no running Docker socket was available in this workspace.
  The README supplies those commands; protocol/manifest checks do not establish
  full Docker runtime acceptance.
- No repository remote, publication, push, or app installation was performed.

## Native marketplace release — September 28, 2026

The Rhyven package now uses the rc.9 Python script backend. No Docker image is
required. All 12 standalone/protocol unit tests passed. Real installed-app
conformance passed all three cases, followed by a three-tool MCP acceptance test:
permission review, source import, Git ignore rules, caller-written summaries,
BM25 ranking, stale hashes, backup/restore, retained-state reinstall and collection
isolation. Python uses only its standard library; Git must be on PATH.

Native host.execute grants OS-user access, not a sandbox. The Rhyven action
interface operates on explicit imported snapshots. Standalone model calls remain
optional; the marketplace app delegates summary writing to the calling agent.
