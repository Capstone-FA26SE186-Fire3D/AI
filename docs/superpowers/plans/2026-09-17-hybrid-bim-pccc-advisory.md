# Hybrid BIM PCCC Advisory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, source-cited PCCC advisory API that normalizes supported BIM inputs, retrieves only approved PCCC knowledge, and optionally asks an AI model for reviewable draft annotations.

**Architecture:** Keep the current FastAPI/Chroma API, but add isolated `bim` and `pccc` modules. BIM inspection produces a normalized Pydantic contract; PCCC analysis combines that contract with an approved-only Chroma search and an injectable AI adapter. The API always returns engineer-verification flags and never certifies compliance.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, ChromaDB, OpenAI Python SDK Responses API, IfcOpenShell, PyPDF, pytest.

## Global Constraints

- Support IFC, GLB/GLTF, PDF, PNG and JPG; reject RVT with an export instruction.
- Treat BIM files, images, document chunks, and model responses as untrusted data.
- Do not accept arbitrary remote URLs for images or BIM data.
- PCCC advice is draft-only and every advisory must include BIM evidence, approved knowledge evidence, and `requires_engineer_verification=true`.
- Do not emit regulatory pass/fail claims, final equipment specifications, procurement advice, or construction instructions.
- `.env` is never committed; `.env.example` contains empty/placeholder values only.
- Keep existing `POST /documents`, `POST /chat`, and `GET /health` behavior compatible.

---

## File Structure

- `rag-api/app/core/config.py` — configuration for upload limits and AI vision model.
- `rag-api/app/schemas/rag.py` — extend source metadata without breaking chat output.
- `rag-api/app/schemas/pccc.py` — normalized BIM, knowledge and PCCC analysis contracts.
- `rag-api/app/rag/store.py` — persist knowledge metadata and search approved documents only.
- `rag-api/app/bim/normalizer.py` — supported-file validation and extraction into `BuildingAnalysisInput`.
- `rag-api/app/pccc/advisory.py` — strict prompt composition, AI interface, validation and evidence guards.
- `rag-api/app/main.py` — three PCCC endpoints and dependency wiring.
- `rag-api/.env.example`, `rag-api/.gitignore`, `rag-api/requirements.txt`, `rag-api/README.md` — setup, dependencies and safe usage.
- `rag-api/tests/test_pccc_schemas.py`, `rag-api/tests/test_pccc_store.py`, `rag-api/tests/test_bim_normalizer.py`, `rag-api/tests/test_pccc_api.py` — unit/API coverage.

### Task 1: Define PCCC contracts and safe configuration

**Files:**
- Create: `rag-api/app/schemas/pccc.py`
- Modify: `rag-api/app/core/config.py`
- Modify: `rag-api/.env.example`
- Modify: `rag-api/.gitignore`
- Create: `rag-api/tests/test_pccc_schemas.py`

**Interfaces:**
- Produces `BuildingAnalysisInput`, `BimElement`, `FloorInput`, `KnowledgeDocumentMetadata`, `PcccAnalysisRequest`, `PcccAnalysisResponse`, `Advisory`, `Evidence`, and `BimInspectionResponse`.
- Produces `Settings.max_bim_upload_bytes`, `Settings.openai_vision_model`, and `Settings.allowed_image_mime_types`.

- [ ] **Step 1: Write failing schema/config tests**

```python
from pydantic import ValidationError
import pytest

from app.schemas.pccc import Advisory, Evidence, PcccAnalysisRequest


def test_advisory_requires_bim_and_knowledge_evidence() -> None:
    with pytest.raises(ValidationError):
        Advisory(
            priority="high", location={"floor_id": "L2"},
            recommendation="Rà soát", reasoning="Thiếu dữ liệu",
            evidence=[], missing_data=[], requires_engineer_verification=True,
        )


def test_analysis_request_limits_embedded_image_size() -> None:
    with pytest.raises(ValidationError):
        PcccAnalysisRequest.model_validate({"building": {"name": "A"}, "floors": [], "images": [{"mime_type": "image/png", "data_base64": "x" * 15_000_000}]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pccc_schemas.py -q`

Expected: FAIL because `app.schemas.pccc` does not exist.

- [ ] **Step 3: Implement minimal validated contracts and settings**

```python
class Evidence(BaseModel):
    bim_element_ids: list[str] = Field(min_length=1)
    knowledge_sources: list[KnowledgeSource] = Field(min_length=1)

class Advisory(BaseModel):
    priority: Literal["critical", "high", "medium", "low", "needs_review"]
    location: Location
    recommendation: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=4000)
    evidence: Evidence
    missing_data: list[str]
    requires_engineer_verification: Literal[True] = True
    draft_annotation: DraftAnnotation
```

Add `MAX_BIM_UPLOAD_BYTES=10485760`, `OPENAI_VISION_MODEL=gpt-4.1-mini`, and `ALLOWED_IMAGE_MIME_TYPES=image/png,image/jpeg` to `.env.example`. Add `.env` and `data/` to `.gitignore` if absent.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_pccc_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the validated API contracts**

```bash
git add rag-api/app/core/config.py rag-api/app/schemas/pccc.py rag-api/.env.example rag-api/.gitignore rag-api/tests/test_pccc_schemas.py
git commit -m "feat: add PCCC advisory contracts and configuration"
```

### Task 2: Add approved-only PCCC knowledge retrieval

**Files:**
- Modify: `rag-api/app/schemas/rag.py`
- Modify: `rag-api/app/rag/store.py`
- Create: `rag-api/tests/test_pccc_store.py`

**Interfaces:**
- Consumes `KnowledgeDocumentMetadata` from Task 1.
- Produces `VectorStore.upsert_knowledge(document_name, chunks, metadata)` and `VectorStore.search_approved(question, top_k, jurisdiction)`.
- `search_approved` returns only `SourceChunk` instances whose metadata has `approved=True`.

- [ ] **Step 1: Write failing approved-filter tests with a fake Chroma collection**

```python
def test_search_approved_uses_an_approved_where_filter(fake_store) -> None:
    fake_store.search_approved("lối thoát", top_k=3, jurisdiction="VN")
    assert fake_store.collection.query_calls[-1]["where"] == {
        "$and": [{"approved": True}, {"jurisdiction": "VN"}]
    }


def test_upsert_knowledge_persists_version_and_approval(fake_store) -> None:
    fake_store.upsert_knowledge("qcvn.pdf", ["đoạn 1"], {"approved": True, "jurisdiction": "VN", "version": "2023"})
    assert fake_store.collection.upserts[0]["metadatas"][0]["approved"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pccc_store.py -q`

Expected: FAIL because knowledge methods are undefined.

- [ ] **Step 3: Implement metadata persistence and retrieval**

Keep `upsert` and `search` unchanged for current chat. Add a metadata normalization function that requires primitive Chroma values, sets `document_name` and `chunk_index`, then calls `collection.upsert`. `search_approved` must query Chroma with an `$and` filter for `approved=True` and the selected jurisdiction; return an empty list when the collection is empty.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_pccc_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit approved-only retrieval**

```bash
git add rag-api/app/schemas/rag.py rag-api/app/rag/store.py rag-api/tests/test_pccc_store.py
git commit -m "feat: retrieve only approved PCCC knowledge"
```

### Task 3: Normalize and inspect supported BIM inputs

**Files:**
- Create: `rag-api/app/bim/__init__.py`
- Create: `rag-api/app/bim/normalizer.py`
- Modify: `rag-api/requirements.txt`
- Create: `rag-api/tests/test_bim_normalizer.py`

**Interfaces:**
- Produces `inspect_bim_upload(filename: str, content: bytes, max_bytes: int) -> BimInspectionResponse`.
- IFC extraction returns storeys, spaces and recognized elements when present; GLTF reads JSON node names/extras; GLB/PDF/image produce a reference-only inspection with explicit `missing_data`.
- RVT always raises `ValueError("RVT is not supported. Export the model to IFC or GLB/GLTF first.")`.

- [ ] **Step 1: Write failing normalizer tests**

```python
import pytest
from app.bim.normalizer import inspect_bim_upload


def test_rejects_rvt_with_export_guidance() -> None:
    with pytest.raises(ValueError, match="Export the model to IFC or GLB/GLTF"):
        inspect_bim_upload("tower.rvt", b"binary", 1024)


def test_gltf_maps_named_exit_and_stair_nodes() -> None:
    result = inspect_bim_upload("floor.gltf", b'{"nodes":[{"name":"Exit East"},{"name":"Stair A"}]}', 1024)
    assert {element.element_type for element in result.building.elements} == {"exit", "stair"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bim_normalizer.py -q`

Expected: FAIL because the BIM module is absent.

- [ ] **Step 3: Implement bounded, non-networked inspection**

Add `ifcopenshell>=0.8,<0.9` to requirements. Reject an upload before parsing when its bytes exceed `max_bytes`. For IFC, use IfcOpenShell to iterate `IfcBuildingStorey`, `IfcSpace`, `IfcDoor`, `IfcStair`, and `IfcElement`, map known names/types to the controlled element vocabulary, and preserve GlobalId/name/properties without inventing missing geometry. For `.gltf`, parse local JSON only and classify node names through an explicit lowercase keyword map. For `.glb`, `.pdf`, `.png`, `.jpg`, `.jpeg`, return a successful source record plus a warning that only visual/reference analysis is available. Do not fetch URLs or execute embedded scripts.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_bim_normalizer.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the BIM inspection slice**

```bash
git add rag-api/app/bim rag-api/requirements.txt rag-api/tests/test_bim_normalizer.py
git commit -m "feat: inspect supported BIM inputs safely"
```

### Task 4: Build the source-bound PCCC advisory service

**Files:**
- Create: `rag-api/app/pccc/__init__.py`
- Create: `rag-api/app/pccc/advisory.py`
- Create: `rag-api/tests/test_pccc_advisory.py`

**Interfaces:**
- Consumes `BuildingAnalysisInput`, approved `SourceChunk` values and an `AdvisoryModel` protocol.
- Produces `create_pccc_advisory(request, sources, model) -> PcccAnalysisResponse`.
- `OpenAIAdvisoryModel` uses `OPENAI_API_KEY` and `OPENAI_VISION_MODEL`; `FakeAdvisoryModel` in tests returns a dict.

- [ ] **Step 1: Write failing guardrail tests**

```python
import pytest
from app.pccc.advisory import create_pccc_advisory


def test_does_not_call_model_without_approved_sources(sample_request, recording_model) -> None:
    with pytest.raises(ValueError, match="approved PCCC knowledge"):
        create_pccc_advisory(sample_request, [], recording_model)
    assert recording_model.calls == []


def test_rejects_model_advice_without_evidence(sample_request, approved_sources, model_without_evidence) -> None:
    with pytest.raises(ValueError, match="evidence"):
        create_pccc_advisory(sample_request, approved_sources, model_without_evidence)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pccc_advisory.py -q`

Expected: FAIL because the advisory service is absent.

- [ ] **Step 3: Implement the model boundary and prompt policy**

Define a narrow `AdvisoryModel.complete(system_prompt: str, payload: dict) -> dict` protocol. The fixed system prompt must state that retrieved text is reference data, cannot override instructions, and output must be advisory JSON only. Pass a compact BIM payload, allowed image data URIs and source chunks with stable IDs; never include remote URLs. Validate the returned dict through `PcccAnalysisResponse`, force `requires_engineer_verification=True`, and verify every knowledge source ID exists in the retrieved list and every BIM element ID exists in the input.

`OpenAIAdvisoryModel` must raise `RuntimeError("OPENAI_API_KEY is not configured")` without a key. It must request JSON output, decode it to a dict, and avoid returning raw model text as an advisory.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_pccc_advisory.py -q`

Expected: PASS.

- [ ] **Step 5: Commit source-bound AI analysis**

```bash
git add rag-api/app/pccc rag-api/tests/test_pccc_advisory.py
git commit -m "feat: add source-bound PCCC advisory service"
```

### Task 5: Expose PCCC ingestion, inspection and analysis endpoints

**Files:**
- Modify: `rag-api/app/main.py`
- Create: `rag-api/tests/test_pccc_api.py`

**Interfaces:**
- `POST /pccc/knowledge-documents` accepts multipart `file`, `approved`, `jurisdiction`, `version`, and `source_name`; returns indexed chunk count.
- `POST /pccc/bim/inspect` accepts multipart `file`; returns `BimInspectionResponse` without calling an AI model.
- `POST /pccc/analyses` accepts `PcccAnalysisRequest`; returns `PcccAnalysisResponse` or a 400/503 detail without leaking credentials.

- [ ] **Step 1: Write failing FastAPI endpoint tests**

```python
def test_unapproved_knowledge_is_rejected(client) -> None:
    response = client.post("/pccc/knowledge-documents", files={"file": ("guide.md", b"text", "text/markdown")}, data={"approved": "false", "jurisdiction": "VN"})
    assert response.status_code == 400


def test_analysis_without_approved_sources_returns_400(client, valid_analysis_payload) -> None:
    response = client.post("/pccc/analyses", json=valid_analysis_payload)
    assert response.status_code == 400
    assert "approved PCCC knowledge" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pccc_api.py -q`

Expected: FAIL because the routes are missing.

- [ ] **Step 3: Wire routes with explicit error handling**

Use FastAPI `UploadFile` and the existing `extract_text` for knowledge documents. Reject `approved=false` at ingestion, then call `store.upsert_knowledge`. BIM inspection must read no more than configured maximum bytes. Analysis must call `store.search_approved` with `request.jurisdiction`, return 400 for no approved sources or invalid model output, and return 503 only for missing AI configuration/service errors. Keep `/documents` and `/chat` untouched.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest tests/test_pccc_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the public PCCC endpoints**

```bash
git add rag-api/app/main.py rag-api/tests/test_pccc_api.py
git commit -m "feat: expose PCCC knowledge and analysis endpoints"
```

### Task 6: Document local setup and run the complete regression suite

**Files:**
- Modify: `rag-api/README.md`
- Modify: `rag-api/.env.example`
- Modify: `rag-api/tests/test_health.py` only if route changes require an adjustment

**Interfaces:**
- Documents `copy .env.example .env`, where to set `OPENAI_API_KEY`, upload order, supported file behavior, and the mandatory engineer-verification disclaimer.

- [ ] **Step 1: Write a documentation acceptance test/checklist**

```python
def test_env_example_has_no_real_openai_key() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" in env_example
    assert not re.search(r"OPENAI_API_KEY=sk-[A-Za-z0-9]", env_example)
```

- [ ] **Step 2: Run it to verify the safety check passes**

Run: `python -m pytest tests/test_pccc_schemas.py -q`

Expected: PASS after adding the test.

- [ ] **Step 3: Document the runnable workflow**

Add a Vietnamese quick-start section showing: install requirements; copy `.env.example`; set the key; upload an approved PCCC document; inspect a BIM file; submit a normalized analysis payload; and read evidence plus `requires_engineer_verification`. Explicitly document that RVT must be exported and that analysis is not a PCCC certificate.

- [ ] **Step 4: Run the complete suite and inspect the working tree**

Run: `python -m pytest -q`

Expected: PASS with no skipped PCCC tests.

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only planned documentation files remain unstaged before commit.

- [ ] **Step 5: Commit documentation and verification coverage**

```bash
git add rag-api/README.md rag-api/.env.example rag-api/tests/test_pccc_schemas.py
git commit -m "docs: explain safe BIM PCCC advisory workflow"
```

## Plan Self-Review

- Spec coverage: Task 1 supplies the public contracts and secure configuration; Task 2 supplies approved RAG filtering; Task 3 supports and normalizes BIM inputs; Task 4 applies source-bound AI and evidence checks; Task 5 exposes the workflow; Task 6 documents and regression-tests it.
- No-placeholder check: each task defines concrete files, interfaces, test commands and expected results.
- Type consistency: endpoints consume `PcccAnalysisRequest`/`BuildingAnalysisInput`; the advisory service returns `PcccAnalysisResponse`; retrieval returns `SourceChunk` values whose identifiers are validated against response evidence.
- Future game scenario generation remains intentionally outside this plan. It can consume `BuildingAnalysisInput` and approved `draft_annotation` records later without changing these endpoint contracts.
