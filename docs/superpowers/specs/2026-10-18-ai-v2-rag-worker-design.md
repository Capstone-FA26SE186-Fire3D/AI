# AI v2 adapter, RAG pgvector và worker IFC — Design

Ngày: 2026-10-18. Phạm vi: issue AI#1–#9 (A1–A8). Chỉ sửa repo AI; BE/Docs chỉ đọc.
Contract nguồn: BE `origin/main` `c4975f1` (`docs/organization-ai.md` mục "FastAPI adapter contract v2", `docs/processing-worker.md`,
`docs/ifc-qa-codes.md`, `docs/ifc-equipment-candidates.md`, `contracts/editor/v1`, `contracts/ifc/v1`, `Persistence/Sql/KnowledgeChunks.sql`);
Docs `origin/main` `7d9d6ba` (`ifc_ingestion_visual_interaction.md`, `fire_evacuation_bim_rag_pccc.md`). Khi contract lệch, BE là nguồn đúng.

## Mục tiêu

1. BE gọi được AI qua contract v2 và nhận response hợp lệ theo luật settlement của BE (A1).
2. Truy hồi chỉ trong các nguồn BE đã pin, trên `knowledge_chunks` (pgvector, Supabase) (A2, A3).
3. Organization nhận KnowledgeAnswer/ScenarioDraft có nguồn, neo đúng BIM pin; Trainee nhận KnowledgeAnswer theo Learn/Training/Result (A4, A5).
4. Timeout/restart không làm BE hoàn hoặc trừ quota sai (A6).
5. Một job IFC tạo `preview_glb` + `building_metadata` hợp lệ qua gate lease của BE (A7).
6. Có Docker/CI/eval để chọn provider bằng số liệu; tài liệu triển khai Azure (A8).

Không thuộc phạm vi: deploy Azure thật, nghiệm thu với BE thật, sửa BE/Docs, thay asset theo bbox, NavMesh source/hazard grid
(Unity build worker làm NavMesh), merge nhiều file IFC/revision.

## Cấu trúc

```
rag-api/
  app/
    main.py            tạo app, gắn router v2, legacy (theo cờ), health/ready, logging
    core/config.py     Settings (env/.env)
    core/logging.py    log JSON có request_id, thời gian
    v2/                schemas.py (pydantic snake_case), router.py, auth.py, errors.py
    requests/          store.py (SQLAlchemy Core), service.py (dedup/lifecycle), recovery.py
    sources/           resolver.py (pin → văn bản), fetch.py (https + SHA-256), chunking.py (locator), render.py (content inline → text)
    index/             pgvector.py (knowledge_chunks), memory.py (in-memory cho test/inline), housekeeping.py (CLI)
    llm/               base.py (Provider protocol), openai_provider.py, gemini_provider.py, fake.py, factory.py
    answering/         safety.py, retrieval.py, prompts.py, validate.py, scenario.py, pipeline.py
    legacy/            /documents, /chat, /pccc/* cũ (ChromaDB), chỉ khi LEGACY_ROUTES_ENABLED=true
  contracts/           schema vendored từ BE + README ghi commit gốc
  db/migrations/       001_ai_service.sql (schema ai_service, bảng requests, grant)
  evals/               dataset JSONL, run_eval.py, báo cáo
  tests/
ifc-worker/            process riêng, requirements riêng
  worker/              config, server (delivery), gate_client, storage (S3), pipeline/*, qa, metadata, glb, blender (tuỳ chọn)
  config/              keywords.v1.json, materials.v1.json
  scripts/blender_optimize.py
  tests/
Dockerfile ×2, docker-compose.yml, .github/workflows/ci.yml, docs/deploy-azure.md
```

Route cũ có rò rỉ phạm vi (một collection chung, không lọc) và Docs yêu cầu loại khỏi production; chúng chuyển vào `app/legacy` và chỉ
gắn khi `LEGACY_ROUTES_ENABLED=true` (mặc định false). Demo FE `/demo/rag` và Mobile chat cần bật cờ khi chạy local.

## A1 — Adapter v2

Route: `POST /v2/organization/answer`, `POST /v2/organization/scenario-draft`, `POST /v2/trainee/answer`, `GET /v2/requests/{request_id}`.

- Auth: nếu `AI_API_KEY` cấu hình thì bắt buộc `Authorization: Bearer`, so sánh `hmac.compare_digest`; sai/thiếu → 401. Không cấu hình
  chỉ cho phép khi `ENVIRONMENT=development`; ngoài dev app từ chối khởi động thiếu key. Không CORS cho route v2.
- `X-Request-Id` phải bằng `request_id` trong body, lệch → 422 `{code:"AI_REQUEST_ID_MISMATCH"}` (BE ghi là `AI_PROVIDER_REJECTED`).
- Route ↔ body phải khớp: organization/answer = (`organization`, `Answer`, `KnowledgeAnswer`); organization/scenario-draft =
  (`organization`, `ScenarioDraft`, `ScenarioDraft`, cần `bim`); trainee/answer = (`trainee`, `TraineeAnswer`, `KnowledgeAnswer`,
  `organization_id` null). Lệch → 422.
- Schema request đúng mục v2 của BE (pydantic, `extra="ignore"` để BE thêm trường không làm vỡ). Response: `request_id, response_type,
  status, recommendation, scenario_draft|null, bim_anchors[], citations[], rule_results[], confidence, assumptions[], limitations[], usage`.
- Mã lỗi theo luật BE: 400/422 = từ chối dứt khoát (body `{code, message}`, code ∈ `AI_SOURCE_HASH_MISMATCH`, `AI_SOURCE_UNAVAILABLE`,
  `AI_REVISION_NOT_PINNED`, hoặc mã khác → BE ghi `AI_PROVIDER_REJECTED`); 401/403/404/429/503 chỉ khi chưa có side-effect; 409 cho
  xung đột/đang chạy (BE coi là outcome chưa rõ → reconcile).

## A6 — Request bền và reconcile

Bảng `ai_service.requests` (Postgres, cùng DB Supabase với BE, schema riêng do AI sở hữu; SQLite cho dev/test qua cùng code SQLAlchemy Core):
`request_id PK, operation, audience, input_hash, payload JSONB, status (Received|Processing|Completed), attempts, response JSONB,
usage_total JSONB, created_at, updated_at, processing_started_at, completed_at`.

Luồng POST:
1. Tra `request_id`. `Completed` + cùng `input_hash` → 200 response đã lưu. Khác `input_hash` → 409 `AI_REQUEST_CONFLICT`.
   `Received`/`Processing` → 409 `AI_REQUEST_IN_PROGRESS`.
2. INSERT `Received` (unique PK; mất race → bước 1).
3. Resolve nguồn và BIM pin. Lỗi refusal → DELETE row, trả 422. Lỗi hạ tầng trước provider → DELETE row, trả 503.
4. UPDATE `Processing` + commit **trước** khi gọi provider.
5. Chạy pipeline; UPDATE `Completed` với response + usage. Ngoại lệ sau bước 4 → row giữ `Processing`, trả 500 (BE: outcome chưa rõ).

GET lookup: `Completed` → 200 body như POST; `Received`/`Processing` → 202 `{request_id, status:"Processing"}`; không có → 404.

Recovery: vòng lặp nền (và lúc khởi động) chọn row `Processing` có `processing_started_at` quá `REQUEST_STALE_SECONDS` (mặc định 300),
khoá bằng `UPDATE … WHERE status='Processing' AND processing_started_at < :cutoff` (compare-and-set), chạy lại pipeline từ `payload`,
cộng usage các lần chạy vào `usage_total`, ghi `Completed`. Row `Received` quá hạn (crash trước provider) bị xoá → lookup 404 đúng nghĩa.
Mỗi lần gọi provider có timeout (`LLM_TIMEOUT_SECONDS`, mặc định 45 < BE 60), SDK retry = 0.

Migration `db/migrations/001_ai_service.sql`: `CREATE SCHEMA ai_service`, bảng, index trạng thái, role `fet3d_ai_service` (NOLOGIN, quyền
CRUD trên `ai_service.requests`), hướng dẫn cấp membership cho login AI cùng `fet3d_ai_indexer`. Admin DB chạy một lần; app không tự tạo
bảng trên Postgres (SQLite dev thì tự tạo).

## A2 — pgvector

- `PgVectorIndex` (psycopg 3 + pgvector-python) trên `knowledge_chunks(source_id, chunk_index, content, locator, embedding, metadata)`.
  `source_id` = `document_id` của nguồn KnowledgeSource (mỗi row `knowledge_sources` là một version).
- Mọi truy vấn có `WHERE source_id = ANY(%(pins)s)`; không có API truy hồi không pin. Hybrid: top-k vector (`<=>` cosine) và top-k
  full-text (`to_tsvector('simple', content) @@ plainto_tsquery('simple', q)`), gộp bằng Reciprocal Rank Fusion (k=60).
- `metadata` chunk: `content_hash`, `document_version`, `embedding_model`, `embedding_dim`. Truy vấn vector chỉ dùng chunk có
  `embedding_model` trùng model hiện hành; khác model → re-index nguồn đó.
- Housekeeping: `python -m app.index.housekeeping` đọc `ai_source_states` (`kind='KnowledgeSource' AND NOT eligible`) và xoá chunk.
- Test tích hợp với container `pgvector/pgvector:pg17`, dựng `knowledge_sources` tối giản + DDL `KnowledgeChunks.sql` vendored + role;
  kiểm tra: hai tenant cùng tên tài liệu, nguồn không pin không bao giờ trả về, version cũ, housekeeping. Docker tắt → skip.

## A3 — Ingestion nguồn đã pin

- KnowledgeSource: nếu đã có chunk của `document_id` với `metadata.content_hash == content_hash` và đúng embedding model → dùng.
  Ngược lại tải `source_uri` (chỉ https, không redirect sang http, timeout 20s, tối đa `SOURCE_MAX_BYTES` 20 MB), SHA-256 ≠
  `content_hash` → 422 `AI_SOURCE_HASH_MISMATCH`; không có `source_uri`/tải lỗi/định dạng không đọc được → 422 `AI_SOURCE_UNAVAILABLE`.
  Đọc txt/md/pdf/html; chunk + embed; DELETE chunk cũ của `source_id` rồi INSERT trong một transaction.
- Chunking ~900 ký tự, overlap 150, cắt ở ranh giới đoạn khi có thể; `locator`: PDF `{page}`, Markdown `{heading, paragraph}`,
  text `{paragraph}`; `excerpt_locator` hiển thị: "Trang 3", "Mục <heading>, đoạn 2", "Đoạn 4".
- Nguồn inline (LearnPost `title/summary/blocks`, LibraryVersion `kind/code/name/payload`, TrainingSnapshot, SessionResult): render sang
  văn bản có nhãn, chunk trong bộ nhớ, embed khi cần, không ghi `knowledge_chunks`. Locator LearnPost = `{block}`; snapshot = `{field}`.
- `content_omitted: true` → bỏ nguồn, thêm `limitations`. Nội dung nguồn luôn là dữ liệu không tin cậy.

## A4/A5 — Pipeline trả lời

1. Safety gate trước (luật từ khoá VN/EN, có version): yêu cầu xác nhận tuân thủ/chứng nhận/phê duyệt, số lượng/vị trí thiết bị cuối cùng,
   chỉ dẫn ứng phó sự cố thật → `RejectedBySafetyGate`, không gọi LLM, usage 0.
2. Truy hồi trong các nguồn đã pin (top 8 sau RRF, cắt theo ngân sách token). Không có chunk → `InsufficientEvidence`.
3. Prompt: system cố định (dữ liệu nguồn không tin cậy, chỉ trả JSON theo schema, không chứng nhận); user payload JSON có câu hỏi, chunk
   kèm `chunk_id`, và (ScenarioDraft) tóm tắt BIM: floors, anchors (tối đa 300, ưu tiên cửa/cầu thang/phòng), capabilities, qualityFlags.
   Không gửi IFC thô.
4. Provider trả structured output (JSON schema nội bộ). Validator hậu kiểm:
   - citation phải trỏ tới chunk đã truy hồi; `document_id/document_version` lấy từ pin, không lấy từ model; trùng lặp gộp.
   - text thuần: chuyển markup HTML/Markdown của model thành text thuần (bỏ thẻ, `**`, `#`, backtick, link → text); recommendation cắt ≤ 8000;
     mục danh sách cắt ≤ 500 ký tự, giữ ≤ 20 mục.
   - `Answered`/`NeedsUserEdit` cần ≥ 1 citation, nếu không → `InsufficientEvidence`.
   - safety gate chạy lại trên output (cụm "đạt chuẩn PCCC", "được chứng nhận"… → `RejectedBySafetyGate`).
   - Output không parse/không hợp lệ → `InsufficientEvidence` + limitation, vẫn 200 kèm usage thật.
5. ScenarioDraft (Organization): thiếu `bim` → 422 `AI_REVISION_NOT_PINNED`. State: ép `schemaVersion="fet3d.editor/1"` và
   `geometry={artifactId, sha256Hash}` của pin; validate `scenario-state.schema.json` (jsonschema); loại object có `floorId` không thuộc pin,
   `anchorId` không thuộc anchors cùng floor, `capability.id` không có trong `runtime.capabilities` (ghi `limitations`).
   `bim_anchors`: `revision_id` = pin, `ifc_global_id` thuộc anchors/floors của pin, ≥ 1; không đạt → `InsufficientEvidence`.
   `rule_results`: luật cố định từ `qualityFlags` (vd `EXIT_MAPPING_MISSING` → flag) — không phải kết luận tuân thủ.
6. Trainee: luôn `KnowledgeAnswer`; `bim_anchors` rỗng; prompt theo `context.kind` (Learn: bám bài; Training: chỉ snapshot learner-safe;
   Result: giải thích kết quả của chính người học, không chấm lại). Không bịa citation Common.
7. Usage: `tokens` → `provider_units = input_tokens + output_tokens`; `requests` → 1; đơn vị khác → 422 `AI_QUOTA_UNIT_UNSUPPORTED`.
   Context cắt sao cho ước lượng + `max_output_tokens` ≤ `max_units`; nếu không đủ cho tối thiểu → `InsufficientEvidence` không gọi LLM.
   `confidence`: high chỉ khi mọi ý có citation và không có limitation; medium/low theo số citation/limitation.

## A8 — Provider, eval, vận hành

- `Provider` protocol: `generate(system, payload, schema, max_output_tokens) -> (dict, Usage)` và `embed(texts) -> list[list[float]]`.
  OpenAI (Responses API, `json_schema` strict, `store=False`), Gemini (`google-genai`, `response_schema`), Fake (theo kịch bản, cho test/eval).
  Chọn bằng `LLM_PROVIDER` (mặc định `openai`); không fallback tự động sang provider khác.
- `evals/`: `dataset.jsonl` (câu hỏi + nguồn + kỳ vọng: status, citation bắt buộc, phải từ chối), `run_eval.py --provider fake|openai|gemini`
  → JSON + Markdown: citation coverage, abstain đúng, injection resisted, safety refusal đúng, latency, tokens. Ngưỡng do team chốt.
- Dockerfile `rag-api` và `ifc-worker` (non-root), `docker-compose.yml` dev (api + pgvector), CI GitHub Actions (pytest hai package, service
  pgvector), log JSON, `GET /ready` (DB + cấu hình provider), `docs/deploy-azure.md` (Container Apps, Key Vault, ingress nội bộ, biến môi trường
  khớp `OrganizationAi__*`).

## A7 — Worker IFC

- Delivery: `POST /deliveries` (kiểm `X-Worker-Key` hằng thời gian) → gọi BE `claim` với `{eventKey, payloadHash, inputHash, toolchainVersion}`;
  trả `{eventKey, payloadHash, receiptId}` sau khi claim thành công; replayed → ACK, không chạy lại. Xử lý trong thread nền, thread khác `renew`
  khi còn 1/3 lease.
- Pipeline: tải `sourceKey` (S3, boto3), SHA-256 = `sourceHash`, header `ISO-10303-21;`; mở IFC; storeys/spaces/elements; geometry
  `ifcopenshell.geom` (context Body 3D, world coords, cắt opening) với iterator đa luồng; runtime filter §5.3; Z-up → Y-up (`(x,y,z)→(x,z,-y)`),
  đơn vị mét (geom đã scale theo đơn vị dự án; `coordinateTransform` ghi scale + trục).
- GLB (trimesh): node cấp cao mỗi tầng tên `storeys[].id`, node con tên GlobalId; mesh ở toạ độ GLB thế giới; UV0 box projection theo mét;
  `extras`: `ifcGlobalId`, `ifcClass`, `libraryKey`, `tint`. Không nhúng texture.
- Metadata `preview_glb` (`fet3d.editor/1`): units/upAxis/handedness, `coordinateTransform`, `floors[{id, name, elevationMeters, ifcGlobalId,
  transform}]`, `semanticMapping` phủ mọi phần tử giữ lại + spaces + mọi GlobalId trong QA và interactables.
- `building_metadata` (`fet3d.building/1`): sources, units, storeys, spaces (name/longName/category/storey/bbox), portals (cửa: fireExit,
  isExternal, exitInferred), interactables (bảng phân loại §5.2 Docs, cửa có `ifcClass` IfcDoor…, confidence 0.95 khi class chuẩn,
  0.6–0.8 khi theo từ khoá/proxy), materials, qaIssues. Từ khoá và vật liệu ở `config/*.v1.json`.
- QA: các mã §5.9; Block → `Error`, outcome `Failed`; `IFC_EXIT_UNKNOWN` = Warning; đếm tam giác mỗi tầng, > 150k → `IFC_TRIANGLE_BUDGET_EXCEEDED`.
- Upload vào `outputPrefix` (`preview.glb`, `building_metadata.json`), `outputs` × 2 với SHA-256 tự tính, `complete` với `outputHash` BE trả về.
  Lỗi bất kỳ → `fail` với lý do; lease mất → dừng, không ghi.
- Blender tuỳ chọn (`BLENDER_PATH`): `blender --background --python scripts/blender_optimize.py` unwrap UV1 lightmap; thiếu Blender → bỏ qua
  (Unity tự tạo UV2). `toolchainVersion` = `fet3d-ifc/<worker>+ifcopenshell-<ver>[+blender-<ver>]`, phải nằm trong `AllowedToolchains` của BE.
- Test: IFC fixture sinh bằng `ifcopenshell.api` (2 tầng, phòng, tường, cửa ngoài, bình chữa cháy proxy, lavabo), fake gate + fake storage;
  validate output bằng schema vendored.

## Rủi ro và giả định

- Mã "đang xử lý" chưa được BE quy định; chọn 202 cho GET và 409 cho POST trùng — cả hai đều giữ BE ở `NeedsReconcile`, không hoàn quota.
- Recovery chạy lại pipeline sau crash: usage báo về là tổng các lần chạy, có thể vượt `max_units` → BE đánh dấu
  `AI_USAGE_EXCEEDS_RESERVATION` cho admin xử lý (trung thực hơn báo thiếu).
- Embedding mặc định `text-embedding-3-small` (1536). Gemini embedding khác chiều → re-index khi đổi provider.
- Checklist mức 3–4 (tích hợp với BE thật, môi trường thật) chưa thể đạt trong phạm vi này.
