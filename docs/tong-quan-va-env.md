# Fire3D AI: tổng quan, kiến trúc và biến môi trường

Repo `ai` gồm hai dịch vụ Python chạy phía sau backend .NET (BE): **rag-api** trả lời câu hỏi PCCC có trích dẫn nguồn và
tạo bản nháp kịch bản; **ifc-worker** chuyển file IFC thành mô hình 3D và metadata. Client (web, mobile) không gọi thẳng
hai dịch vụ này; mọi yêu cầu đi qua BE.

Tài liệu liên quan: [huong-dan-ai.md](huong-dan-ai.md) (chạy và thử từng bước), [deploy-azure.md](deploy-azure.md)
(triển khai Azure), `rag-api/db/README.md` (cơ sở dữ liệu).

## 1. AI dùng để làm gì

| Tính năng | Ai dùng | Route (rag-api, tiền tố `/v2`) | Kết quả |
|---|---|---|---|
| Hỏi đáp cho tổ chức | Người dùng tổ chức | `POST /organization/answer` | Câu trả lời kèm citation tới đúng tài liệu/phiên bản |
| Nháp kịch bản thoát nạn | Người dùng tổ chức | `POST /organization/scenario-draft` | Bản nháp gắn với tòa nhà (BIM đã ghim), người dùng sửa tiếp |
| Hỏi đáp cho học viên | Trainee | `POST /trainee/answer` | Trả lời chỉ dựa trên bài Learn / kết quả buổi học BE cấp |
| Tra lại kết quả | BE (reconcile) | `GET /requests/{request_id}` | `200` đã xong, `202` đang xử lý, `404` chưa nhận |
| Chuyển IFC → 3D | BE dispatcher | `POST /deliveries` (ifc-worker) | `preview.glb` + metadata upload lên S3 |

Câu hỏi về chứng nhận hay sự cố thật bị safety gate chặn (`RejectedBySafetyGate`); thiếu nguồn phù hợp thì trả
`InsufficientEvidence` thay vì đoán.

## 2. Kiến trúc

```
Web / Mobile
     │  HTTPS + JWT
     ▼
BE (.NET, Azure App Service) ── PostgreSQL (Supabase): dữ liệu nghiệp vụ, quota, knowledge_chunks (pgvector)
     │  Bearer AI_API_KEY + X-Request-Id                ▲
     ▼                                                  │ đọc/ghi chunk (login riêng của AI)
rag-api (FastAPI) ──────────────────────────────────────┘
     │  gọi LLM: Gemini hoặc OpenAI
     ▼
LLM provider

BE ── POST /deliveries ──▶ ifc-worker ── claim/renew/complete job qua API nội bộ của BE (X-Worker-Key)
                                └──── tải IFC / upload GLB ──▶ AWS S3 (fire3d-bucket)
```

### Luồng một câu hỏi

1. Client gửi câu hỏi tới BE. BE kiểm tra quyền, chọn nguồn được phép, **giữ chỗ quota** rồi trả `202`.
2. Worker nền của BE (`OrganizationAiWorker`) gọi rag-api với `request_id`, `input_hash`, câu hỏi và danh sách nguồn đã ghim.
3. rag-api ghi request vào `ai_service.requests`. Cùng `request_id` và cùng input thì trả kết quả cũ, không gọi LLM lần
   nữa; khác input thì `409 AI_REQUEST_CONFLICT`.
4. rag-api chuẩn bị nguồn:
   - **KnowledgeSource** (văn bản luật, tiêu chuẩn): nếu `knowledge_chunks` chưa có bản ứng với hash và model embedding,
     AI tải `sourceUri`, kiểm tra SHA-256, cắt đoạn, tạo embedding rồi lưu. Lần sau đọc thẳng từ bảng.
   - **Learn, Library, Training, SessionResult**: BE gửi nội dung kèm request, không lưu vào vector DB.
5. Tìm tối đa 8 đoạn liên quan (vector + từ khóa), gọi LLM sinh JSON, lọc citation sai, chạy safety gate.
6. Trả kết quả kèm usage (`tokens` hoặc `requests`). BE kiểm tra kết quả rồi **chốt hoặc hoàn quota**.
7. Timeout hoặc lỗi không rõ kết quả: BE để request ở `NeedsReconcile`, không gửi lại. Vòng recovery của rag-api hoàn tất
   các request bị kẹt quá `REQUEST_STALE_SECONDS`; admin reconcile thì BE gọi `GET /v2/requests/{id}`.

### Thành phần trong code

| Thư mục | Vai trò |
|---|---|
| `rag-api/app/main.py` | Khởi tạo FastAPI, `/health`, `/ready`, vòng recovery |
| `rag-api/app/v2/` | Route v2, kiểm tra Bearer và `X-Request-Id` |
| `rag-api/app/requests/` | Lưu request, chống trùng, recovery |
| `rag-api/app/sources/` | Tải tài liệu (PDF, Markdown, HTML, TXT), kiểm hash, cắt đoạn |
| `rag-api/app/index/` | Index trong bộ nhớ (dev) hoặc pgvector (`knowledge_chunks`), housekeeping |
| `rag-api/app/answering/` | Pipeline trả lời, prompt, kịch bản, tính usage |
| `rag-api/app/llm/` | Provider `fake`, `openai`, `gemini` |
| `rag-api/app/legacy/` | Route cũ, tắt mặc định (`LEGACY_ROUTES_ENABLED=false`) |
| `ifc-worker/worker/` | Nhận delivery, xử lý IFC bằng IfcOpenShell (tùy chọn Blender), upload S3 |

### Dữ liệu

| Bảng | Ai tạo | Dùng cho |
|---|---|---|
| `ai_service.requests` | Migration repo AI: `rag-api/db/migrations/001_ai_service.sql` (admin DB chạy tay một lần) | Chống trùng và khôi phục request |
| `knowledge_chunks` | Migration BE (`KnowledgeChunks.sql`); chỉ được tạo khi Supabase đã bật pgvector | Đoạn tài liệu + vector cho RAG |
| `ai_source_states` (view) | Migration BE | Housekeeping xóa chunk của nguồn đã retire/hết hạn |

Cập nhật kiến thức: admin tạo nguồn qua `POST /api/admin/knowledge-sources` (title, versionLabel, `sourceHash` = SHA-256
của file, `sourceUri` là link https công khai) rồi `approve`. Tài liệu đổi bản thì tạo nguồn mới và `retire` bản cũ; chạy
`python -m app.index.housekeeping` hằng ngày để dọn chunk cũ.

## 3. Biến môi trường

Chạy trên máy thì đặt trong `rag-api/.env` và `ifc-worker/.env` (đã nằm trong `.gitignore`). Trên Azure thì đặt trong
App Service → Settings → Environment variables, không dùng file `.env`. Không ghi giá trị bí mật vào tài liệu hay repo.

### rag-api

| Biến | Bắt buộc | Trạng thái (27/10/2026) | Lấy ở đâu |
|---|---|---|---|
| `ENVIRONMENT` | Có | Local: `development` | `production` khi lên Azure |
| `AI_API_KEY` | Production | Local: đã sinh | Tự sinh ngẫu nhiên; trùng `OrganizationAi__ApiKey` của BE |
| `LLM_PROVIDER` | Có | `gemini` | `fake` để test không tốn tiền |
| `GEMINI_API_KEY` | Khi dùng Gemini | Đã có, **cần đổi** (đã lộ) | aistudio.google.com → Get API key |
| `OPENAI_API_KEY` | Khi dùng OpenAI | Không dùng | platform.openai.com |
| `DATABASE_URL` | Production | Local: SQLite. **Thiếu cho production** | Supabase Session pooler, login riêng `ai_login.<project-ref>` |
| `KNOWLEDGE_DATABASE_URL` | Production | Local: trống. **Thiếu cho production** | Cùng chuỗi với `DATABASE_URL` |
| Model, timeout, giới hạn nguồn | Không | Mặc định | Xem `rag-api/.env.example` |

Ngoài `development`, app từ chối khởi động nếu thiếu `AI_API_KEY` hoặc `KNOWLEDGE_DATABASE_URL`, hoặc `DATABASE_URL` là SQLite.

### ifc-worker

| Biến | Bắt buộc | Trạng thái | Lấy ở đâu |
|---|---|---|---|
| `BE_BASE_URL` | Có | Đã có (BE production) | URL App Service của BE; test an toàn thì dùng BE local |
| `WORKER_KEY` | Có, ≥ 32 ký tự | Đã có, **cần đổi** (đã lộ) | Trùng `ProcessingWorker__MachineKey` của BE |
| `S3_BUCKET`, `S3_REGION` | Có | Đã có | `fire3d-bucket`, `ap-southeast-1` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Có | Đang dùng key của BE, **cần đổi** (đã lộ) | IAM user riêng, quyền `s3:GetObject`/`s3:PutObject` trên bucket |
| `S3_ENDPOINT_URL`, `BLENDER_PATH` | Không | Trống | Chỉ cần với S3 tương thích hoặc khi cài Blender |

Chạy worker phải kèm `--env-file .env` để `boto3` đọc được key AWS:
`uvicorn worker.server:app --host 0.0.0.0 --port 8080 --env-file .env`.

### Phía BE (App Service `fire3d-api`)

| Biến | Giá trị |
|---|---|
| `OrganizationAi__Enabled` | `true` |
| `OrganizationAi__BaseUrl` | URL app rag-api, ví dụ `https://<ten-app-ai>.azurewebsites.net/` |
| `OrganizationAi__ApiKey` | Trùng `AI_API_KEY` |
| `OrganizationAi__TimeoutSeconds` / `LeaseSeconds` | `180` / `240` |
| `ProcessingWorker__WorkerUrl` | `https://<app-worker>/deliveries` |
| `ProcessingWorker__MachineKey` | Trùng `WORKER_KEY` |
| `ProcessingWorker__AllowedToolchains__0` | Kết quả lệnh `python -m worker.config` trong ifc-worker |
| `ProcessingWorker__DispatcherEnabled`, `WorkerApiEnabled` | `true` |

## 4. Còn thiếu gì để lên production

- [ ] Đổi các key đã lộ: Gemini, `WORKER_KEY`, key AWS. Tạo IAM user riêng cho worker.
- [ ] Supabase: bật extension `vector`; kiểm tra `knowledge_chunks`; chạy `001_ai_service.sql`; tạo login `ai_login`
      với `GRANT fet3d_ai_service, fet3d_ai_indexer` và `search_path = public, extensions`.
- [ ] Chuỗi kết nối production cho `DATABASE_URL` / `KNOWLEDGE_DATABASE_URL`.
- [ ] Quyền Contributor trên resource group Azure; tạo Web App Python 3.12 Linux trong plan của `fire3d-api`.
- [ ] Workflow deploy cho repo `ai` (chưa có) hoặc deploy zip thủ công.
- [ ] Đặt biến môi trường cho app AI và các biến `OrganizationAi__*` của BE; kiểm tra `/ready` của AI và mục
      `organizationAi` trong `/health/ready` của BE.
- [ ] BE: merge PR #177 sau khi chạy test Postgres; chạy migration `20261027090000_AddAiPolicyEndAndUnits`.
- [ ] Tạo AI policy cho `Answer`, `ScenarioDraft`, `TraineeAnswer` (đơn vị `tokens` hoặc `requests`); chuyển gói billing
      đang dùng `credit`; cấp quota cho tổ chức.
- [ ] Danh sách tài liệu PCCC có link https công khai; đăng ký và approve làm knowledge source.
- [ ] Lịch chạy housekeeping hằng ngày và dọn `ai_service.requests` quá 90 ngày.
- [ ] Nghiệm thu E2E theo checklist cuối [deploy-azure.md](deploy-azure.md).
