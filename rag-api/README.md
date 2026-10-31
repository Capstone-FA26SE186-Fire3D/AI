# RAG API

Copy `.env.example` to `.env`, add `OPENAI_API_KEY`, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. Upload `.txt`, `.md` or `.pdf` to `POST /documents`, then ask with `POST /chat`.

## Phân tích BIM/PCCC có dẫn nguồn

1. Sao chép `.env.example` thành `.env`, sau đó điền `OPENAI_API_KEY` của bạn.
2. Nạp tài liệu PCCC đã được người có thẩm quyền duyệt vào `POST /pccc/knowledge-documents`, kèm `approved=true`, `jurisdiction`, `version` và `source_name`.
3. Tải mô hình vào `POST /pccc/bim/inspect`. API nhận IFC, GLB/GLTF, PDF, PNG và JPG; tệp RVT cần xuất sang IFC hoặc GLB/GLTF trước.
4. Gửi hồ sơ BIM chuẩn hóa trả về từ bước trước tới `POST /pccc/analyses`. Kết quả chứa vị trí, annotation nháp, bằng chứng BIM/tài liệu và cờ `requires_engineer_verification`.

Hệ thống chỉ hỗ trợ rà soát: không thẩm duyệt PCCC, không xác nhận công trình đạt/không đạt, và không tự chốt số lượng, thông số hoặc vị trí thi công thiết bị. Mọi khuyến nghị cần kỹ sư PCCC có thẩm quyền xác minh.

## Cấu hình v2 (adapter cho BE)

Các biến môi trường mới (xem `.env.example`): `ENVIRONMENT`, `AI_API_KEY` (bắt buộc khi `ENVIRONMENT=production`), `DATABASE_URL`,
`KNOWLEDGE_DATABASE_URL`, `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_CHAT_MODEL`, `GEMINI_EMBEDDING_MODEL`, `LLM_TIMEOUT_SECONDS`,
`MAX_OUTPUT_TOKENS`, `REQUEST_STALE_SECONDS`, `RECOVERY_INTERVAL_SECONDS`, `SOURCE_MAX_BYTES`, `SOURCE_FETCH_TIMEOUT_SECONDS`,
`EMBED_ITEMS_PER_MINUTE` (mặc định 80), `EMBED_BATCH_SIZE` (20), `SOURCE_RETRY_SECONDS` (300).

### Chuẩn bị knowledge source (embed chạy nền)

Câu hỏi không chờ embed. Nguồn `KnowledgeSource` đã embed đủ thì dùng ngay; nguồn chưa có thì bị bỏ qua cho câu đó (ghi
`limitations` "Nguồn X đang được chuẩn bị…") và được xếp vào hàng đợi. Một luồng nền tải, cắt đoạn và embed theo lô
`EMBED_BATCH_SIZE`, không quá `EMBED_ITEMS_PER_MINUTE` đoạn mỗi phút (Gemini gói miễn phí cho 100; phần còn lại để dành cho
câu hỏi). Gặp 429, luồng nền chờ đúng `retryDelay` Gemini trả về rồi chạy tiếp. Lô nào embed xong thì lưu ngay vào
`knowledge_chunks`; khởi động lại, nguồn đang dở được xếp hàng lại và chỉ embed các đoạn còn thiếu.

- Câu hỏi chỉ thất bại khi không còn nguồn nào dùng được (kể cả nguồn inline): `503 AI_SOURCES_PREPARING` khi còn nguồn đang
  chuẩn bị (BE tự gửi lại theo `OrganizationAi__MaxAttempts`/`BackoffSeconds`), hoặc lỗi của nguồn hỏng (`422
  AI_SOURCE_UNAVAILABLE`, `AI_SOURCE_HASH_MISMATCH`). Nguồn lỗi được thử lại sau `SOURCE_RETRY_SECONDS`.
- `POST /v2/sources/warm` (Bearer `AI_API_KEY`), body `{"sources": [SourcePin, ...]}` (1–100): xếp hàng embed trước khi có
  câu hỏi, trả `202 {"sources": [{"document_id", "state": "ready" | "queued" | "failed", "code"?}]}`. Gọi lại để xem tiến độ.
- Index chỉ bền khi `KNOWLEDGE_DATABASE_URL` trỏ tới PostgreSQL có pgvector; index trong bộ nhớ (chỉ `development`) mất khi
  khởi động lại.
Schema và fixture hợp đồng với BE nằm trong `contracts/` (xem `contracts/README.md`).

`ENVIRONMENT` mặc định là `development` để chạy local tiện (SQLite, index trong bộ nhớ). **Production phải đặt
`ENVIRONMENT=production`.** Ngoài `development`, app từ chối khởi động nếu thiếu `AI_API_KEY`, thiếu `KNOWLEDGE_DATABASE_URL`
hoặc `DATABASE_URL` vẫn là SQLite (request store phải là PostgreSQL).

### Hạn mức token (`quota_unit=tokens`)

Service ước lượng token input bảo thủ: `ceil(số ký tự / 2.5) + 300` (tiếng Việt ~2,5 ký tự/token; 300 token cố định cho system
prompt/schema structured output), và chỉ dùng 85% phần còn lại sau output: ngân sách input =
`floor((max_units − MAX_OUTPUT_TOKENS) × 0.85)`; chunk ít liên quan bị cắt bớt cho tới khi vừa. Nếu không còn chỗ, trả
`InsufficientEvidence` mà không gọi provider. Vì vậy `reserveUnits` phía BE nên tối thiểu `MAX_OUTPUT_TOKENS + 1000`
(mặc định 1500 → ≥ 2500); thấp hơn thì hầu hết câu hỏi sẽ bị từ chối vì hạn mức. Tỉ lệ này là ước lượng: trước khi chốt
provider, đo `input_tokens`/`output_tokens` thật bằng `python -m evals.run_eval --provider openai|gemini` và chỉnh nếu cần.

## Route legacy (demo FE/Mobile)

Các route cũ `/documents`, `/chat`, `/pccc/*` và CORS mặc định TẮT. Đặt `LEGACY_ROUTES_ENABLED=true` để bật cho demo FE/Mobile;
`VectorStore` (Chroma) chỉ được khởi tạo khi route legacy được gọi lần đầu. `/health` luôn có.

## Test và eval

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evals.run_eval --provider fake --out evals/reports/local
```

Test pgvector chỉ chạy khi đặt `FIRE3D_AI_TEST_PG_DSN` tới một PostgreSQL có pgvector; nếu không, chúng tự bỏ qua, kể cả khi máy có Docker; chỉ đặt `FIRE3D_AI_TEST_PG_DOCKER=1` khi muốn tự khởi chạy container pgvector. Eval `fake` chạy hoàn toàn offline (xem `evals/README.md`); `--provider openai|gemini` cần khoá API tương ứng (`OPENAI_API_KEY`, `GEMINI_API_KEY`).

Biến môi trường chính: xem mục "Cấu hình v2" và `.env.example`. Dự án không dùng Docker; hướng dẫn triển khai Azure App Service ở `../docs/deploy-azure.md`.
