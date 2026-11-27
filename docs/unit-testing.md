# AI test groups and inventory

Use Python 3.12 in each service environment. Install `requirements-test.txt` from the service directory; it includes the production requirements and pytest coverage tooling. Run `python -m pytest -q -rs` from `rag-api` and `ifc-worker` separately. Select `-m unit`, `-m adapter`, or `-m integration`; the RAG `pgvector` marker remains available. Coverage example: `python -m pytest -q -rs --junitxml=test-results.xml --cov=app --cov-branch --cov-report=xml:coverage.xml --cov-report=json:coverage.json` in RAG; use `--cov=worker` in IFC. CI runs Python 3.12, disposable PostgreSQL/pgvector for RAG, and fake eval. Coverage and JUnit files are uploaded even when pytest fails.

| Behavior | Evidence |
| --- | --- |
| RAG request idempotency, claim/recovery and unknown outcomes | Existing `rag-api/tests/requests/` suite |
| Source fetch, pinning, cache, retrieval and quota | Existing `sources/`, `index/`, `llm/` suites plus `test_housekeeping.py` |
| FastAPI authentication and error boundary | Existing `v2/` tests plus `v2/test_auth_boundary.py` |
| Log handler lifetime | `test_logging.py` |
| IFC pipeline, geometry, QA and metadata | Existing `ifc-worker/tests/test_*.py` suites |
| IFC storage size, stream closure, path containment and content type | `ifc-worker/tests/test_storage.py` |
| IFC job failures, stale work and callback failure | `ifc-worker/tests/test_runner.py` |

The marker classification is based on actual dependency boundaries. `unit` uses in-process data/fakes; `adapter` exercises HTTP, SDK, SQLite or local files with controlled dependencies; `integration` needs PostgreSQL/pgvector or a local embedding model. The real embedding model requires `FIRE3D_AI_TEST_LOCAL_MODEL_DIR`. PostgreSQL tests require `FIRE3D_AI_TEST_PG_DSN` or opt-in `FIRE3D_AI_TEST_PG_DOCKER=1`. No paid LLM or production service is needed for the normal suite. Run the deterministic evaluation with `python -m evals.run_eval --provider fake --out evals/reports/local` from RAG.

From the AI repo root, run `python tools/test_inventory.py` to write an ignored per-module matrix to `.codex/local/test-module-inventory.md` and JSON. It includes production, legacy, eval and tooling modules. A direct import is not proof of behavioral or branch coverage. The legacy OpenAI helper and Blender optimize script need their own isolated environments if retained; the v2 router is exercised through FastAPI's app entrypoint. RAG and IFC coverage reports are separate because their process and source roots differ.

Keep regressions with expected/actual and a reproducible command. Do not skip failing production behavior or change application code solely to make the test suite pass.
