# Repository File Ingestion

Repository File Ingestion collects selected UTF-8 files for a Rhyven collection. The app keeps its install ID `rhyven/file-rag`. In Rhyven 0.9.5, feed its snapshots to **Wobbegong Collection Search** for cited passages in manual queries and automatic prompt enrichment.

1. Install the 0.4.0 app in the same collection and call `action_put_files` with the repository name and selected files. Include the applicable `.gitignore` files.
2. Run `rhyven --collection demo wobbegong ingest-repository demo`. Use `--root src` or repeat `--exclude GLOB` to narrow the selection.
3. Run `rhyven --collection demo wobbegong query "cache lookup"`. Connections with enrichment enabled can use the same passages immediately.

Repeat the import after changing or deleting a file. Each successful import replaces the selected source. The app also supports optional file summaries and independent file-level search through its own `index` and `search` actions. Building that index is optional for collection search.

The standalone CLI works with Python 3.10+ and Git on Linux/macOS. Its index stores path, folder, SHA-256, optional summary and BM25 statistics. It reads matched content from the original files.

## Standalone

```sh
# Summarize a selected folder; skip .gitignore matches and additional exclusions.
# Requires the model configuration shown below.
python3 file_rag.py summarize project/ --exclude 'docs/drafts/**' --exclude '**/*.generated.py'

# Model-free BM25; summaries remain explicitly empty.
python3 file_rag.py index --root /path/to/project --no-summaries
python3 file_rag.py search 'cache aware routing' --root /path/to/project
python3 file_rag.py search 'cache' --root /path/to/project --content --top-k 5

# Generate summaries through your chosen Chat Completions-compatible endpoint.
export RAG_BASE_URL=http://localhost:8000/v1
export RAG_MODEL=your-model
# Optional: RAG_API_KEY; SSL_CERT_FILE for a custom CA.
python3 file_rag.py index --root /path/to/project
```

Only changed/new files or files still missing summaries require model calls.
Unchanged SHA-256 hashes reuse summaries. Changing the model does not invalidate
cached summaries. Chunked files are summarized and reduced; all file content is
used for retrieval. The configured endpoint receives the selected source text.
Search never calls a model. `--no-summaries` preserves fresh existing summaries
and leaves new/changed files without summaries; a later normal index fills them.

Every index run rereads sources and rebuilds postings; summary generation alone
is incremental. Deleted files disappear on reindex. Renames are delete + add.
A lock protects generation publication and readers. A failed index preserves the
previous generation; unpublished summaries may need regeneration on retry.
The index is not a snapshot of concurrently edited source files. Searches read
current sources, mark hash mismatches `stale`, skip missing/non-text/symlink or
oversized files, and retain the last indexed ranking until reindexing.

Default storage: `ROOT/.wobbegong`. Each immutable generation contains
`wobbegong.db`; `CURRENT` selects the published generation. Existing
`ROOT/.file-rag` caches are reused when a new cache has not been published.
Legacy `bm25.sqlite` generations remain readable. `--index-dir` overrides it (relative to cwd).
Move source and index together to relocate. Index directories are trusted local
state. UTF-8 text only; default file limit 10 MiB. Symlinks, hidden paths and
common build/cache directories are skipped, including `.venv`, `.venvs`, `venv`,
`venvs`, `.tox`, `.nox`, and directories containing `pyvenv.cfg`. `--hidden` permits
hidden paths except excluded directories.

`.gitignore` is respected by default, including nested files, negations, anchored
patterns, escaped characters and `**`. Git's own matcher runs against a temporary
isolated repository; the source tree is never initialized or modified. Rules
apply from the selected root downward. Parent rules outside that root, personal
Git ignores, and `.git/info/exclude` do not apply. Ignored parent directories are
pruned, just as in Git. Even Git-tracked files are excluded if their paths match
these rules; this is a file scan, not a Git tracked-file listing.

Add repeatable `--exclude` Git-style patterns relative to the selected root:
`--exclude 'docs/drafts/' --exclude '**/*.generated.py'`. They are additive,
cannot reinclude files, and override `.gitignore` negations. Default directory
exclusions cannot be undone. `--include` still uses case-sensitive `fnmatch`
(`*` matches `/`) and never overrides exclusions. Exclude credentials and
generated files before indexing. `summarize project/` is an alias for
`index --root project/`; both generate missing/changed summaries and rebuild BM25.

## Ranking and optional filters

Weighted sum of independently length-normalized BM25 fields: path=3,
summary=2, content=1, folder=0.5. Document frequency uses the union of fields.
This is field-weighted BM25, not BM25F. Identifier tokenization splits camel case
and underscores; no stemming or stop words. Distinct query terms OR-match.
Ties use relative path order. Override weights with `--weight path=4`.

```text
query → BM25 → unique file candidates → optional filter → top-k files
```

`--candidates 20 --top-k 5` applies top-k after filtering. Default
`relevance_filter(query, candidates)` returns candidates unchanged. Standalone
`--filter /absolute/path/filter.py:function` loads explicitly trusted Python code:

```python
def relevance_filter(query, candidates):
    # Each candidate has id/path/folder/summary/sha256, content, stale,
    # score and bm25_score. Plug a reranker/classifier in here later.
    return candidates
```

Return a subset/reordering of candidates. IDs must belong to the supplied set;
duplicates collapse; optional replacement scores must be finite. Returned order
is respected. Content/metadata modifications are ignored. Filters receive current
full content even without `--content`; that flag controls final output only.
No dependency on Laya, OpenJev, an embedding model or a reranker is installed.

## Rhyven — no Docker

The 0.4.0 source package uses the display name **Repository File Ingestion**. Previously published packages can display **Wobbegong** under the same install ID. The host needs Python 3.10+ and Git. Rhyven prepares the Python environment.

```sh
rhyven registry-sync rhyven-ai/registry --anonymous
rhyven --collection demo install rhyven/file-rag
```

Review and accept `host.execute` before installation. Native code runs as your
OS user; its environment isolates dependencies, not host access.

Both `file_rag.py` and the earlier `wobbegong.py` entry point work with existing indexes and scoped summary caches. New app indexes use each repository’s `.wobbegong` directory.

The action interface works on imported snapshots under the collection's app data
directory. Reimport changed files and deletions before indexing. The host checkout
remains authoritative. Index metadata stores paths, summaries and hashes; imported
source is stored separately as ordinary files.

```sh
rhyven --collection demo call rhyven_call '{"category":"rhyven/file-rag","function":"action_put_files","args":{"repository":"demo","files":[{"path":"src/cache.py","content":"def cache_lookup(key): return key\n"}]}}'
rhyven --collection demo call rhyven_call '{"category":"rhyven/file-rag","function":"action_index","args":{"repository":"demo"}}'
rhyven --collection demo call rhyven_call '{"category":"rhyven/file-rag","function":"action_search","args":{"repository":"demo","query":"cache lookup","content":true}}'
```

To build from source: `rhyven app validate .`, `rhyven app test . --allow-host`,
then `rhyven app package . --out repository-file-ingestion.rhyven.json`. The package embeds the script
and action schema. Publishing does not require a container image.

Actions:

| Action | Inputs beyond `repository` | Result |
| --- | --- | --- |
| `export_documents` | Optional `root`, `exclude`, `offset` | Selected documents, snapshot digest and next offset for collection ingestion |
| `put_files` | `files: [{path, content}]`, optional `delete: [path]` | Import counts |
| `index` | Optional `root`, `exclude`, `summaries: [{id, sha256, summary}]` | Build/cache counts |
| `summarize` | Optional `root`, `exclude` | Build/cache counts, pending IDs/hashes and agent instructions |
| `summary_queue` | Optional `root`, `exclude` | IDs/hashes needing summaries |
| `read_file` | `path`, optional `root`, character `offset` | 10,000 characters, hash, `next_offset` |
| `search` | `query`, optional `root`, `top_k`, `candidates`, `content` | Ranked unique files |

To start scoped summarization through MCP, call Rhyven's `rhyven_call` tool:

```json
{
  "category": "rhyven/file-rag",
  "function": "action_summarize",
  "args": {
    "repository": "demo",
    "root": "project/",
    "exclude": ["docs/drafts/**", "**/*.generated.py"]
  }
}
```

Import `project/.gitignore` and any nested `.gitignore` files along with sources
so their rules are available. `root` defaults to `.` (all imported sources).
Each selected root has an independent index and root-relative IDs. Use the same
`root` for subsequent `read_file`, `index`, `summary_queue`, and `search` calls.
For example, `project/src/cache.py` has ID `src/cache.py` within `project/`.

`summarize` scans the folder, reuses fresh summaries, refreshes BM25, and returns
pending IDs/hashes plus instructions for the calling agent. The agent reads those
files, generates summaries with its selected model, and submits them via `index`.
It does not itself invoke a model or launch an autonomous background agent.
Repeat `summarize` after source changes; unchanged summarized files are not queued.

`index` and `summarize` save the exclusion list for that root when they succeed.
Omit `exclude` to reuse it in later requests; use `exclude: []` to clear extra
exclusions. `summary_queue` can preview another exclusion list without saving it.
The standalone CLI uses the exclusions supplied for each invocation.

For LLM summaries, the calling agent gets `summary_queue`, reads all pages of each
file with `read_file`, generates a short summary, then calls `index` with the
matching SHA-256. Changed hashes fail without replacing the index. Existing
fresh summaries are reused. BM25 remains available with no summaries. Agent
summary generation uses the agent's already selected model; this app never
borrows credentials or treats retrieved source text as instructions.

Limits per repository: 100 files, 200,000 UTF-8 bytes/file, 5 MB total. Batch
requests must fit 1 MB. Build/cache directory paths are rejected on import.
Search permits 1–20 results and up to 100 candidates; returned content is capped
at 10,000 characters with `content_truncated`. Use `read_file` for the rest.
Request/response size is bounded below Rhyven's 1 MiB output limit. Imports
validate a batch before writing and replace each file atomically; a disk failure
can leave a partially applied batch. Reimport to reconcile it before reindexing.
Use Rhyven request IDs for retry tracking. Runtime state directories must be
private/trusted. Arbitrary filter modules and model URLs are deliberately not
exposed as remote action inputs; package a reviewed filter to add one later.

## Verification

```sh
python3 -m unittest discover -s tests -v
rhyven app validate .
```

Tests cover scoped MCP summarization and cache reuse, nested Git ignore rules,
negations, additive exclusions, virtual environments, positional root CLI, summary caching, a localhost mock model endpoint and chunk reduction,
metadata shape, changed/deleted files, failed-build rollback, weights, filters,
path/symlink rejection, and subprocess Rhyven protocol round trips. The HTTP test
requires permission to bind a localhost socket. See `TEST-REPORT.md` for what was
actually run in this workspace.

## Download and license

Download source or the standalone archive from [Releases](https://github.com/rhyven-ai/file-rag/releases).
Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). No third-party Python packages
are bundled. Git is supplied by the host. Support: support@rhyvenai.com.
