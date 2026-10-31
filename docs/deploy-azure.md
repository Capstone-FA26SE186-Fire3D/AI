# Triển khai AI service lên Azure

Hướng dẫn này mô tả cách triển khai `rag-api` (FastAPI) cho môi trường thật. Đây là hướng dẫn thiết kế, chưa phải hạ tầng đã tạo hay đã nghiệm thu.

## Phương án mặc định: Azure App Service (Linux, code deploy)

- Runtime: Python 3.12 trên Linux, triển khai bằng code (zip/GitHub Actions), không cần image Docker.
- Startup command: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (đặt `WEBSITES_PORT=8000`). Thư mục ứng dụng là `rag-api/`; build cài `requirements.txt`.
- Bật Always On và đặt tối thiểu 1 instance: service có vòng lặp recovery (`RECOVERY_INTERVAL_SECONDS`) chạy nền, không được để ngủ hoặc scale về 0.
- Probe: `GET /health` là liveness (chỉ báo process sống, không chạm DB/provider) — đặt làm Health check path của App Service để
  instance chết bị khởi động lại. `GET /ready` là readiness: dựng service mặc định và truy vấn request store; trả 503
  `{"status":"unavailable"}` khi DB/cấu hình chưa dùng được. Dùng `/ready` cho smoke test sau deploy và cảnh báo giám sát,
  không dùng làm Health check path (DB chập chờn không phải lý do để thay instance).

Azure Container Apps vẫn khả thi, nhưng cần image build ở nơi khác; việc build image nằm ngoài phạm vi repo này.

## Bí mật và mạng

- Lưu `AI_API_KEY`, `GEMINI_API_KEY` (hoặc `OPENAI_API_KEY`), `DATABASE_URL`, `KNOWLEDGE_DATABASE_URL` trong Azure Key Vault; App Service tham chiếu bằng Key Vault reference (`@Microsoft.KeyVault(SecretUri=...)`) qua managed identity. Không đưa khoá vào repo hay FE/Mobile.
- Truy cập riêng: đặt service sau VNet integration/private endpoint (hoặc access restriction) để chỉ .NET API gọi được; client production không đi thẳng tới FastAPI.
- **Phải đặt `ENVIRONMENT=production`** (mặc định trong code là `development` để chạy local). Ngoài `development`, app từ chối
  khởi động nếu thiếu `AI_API_KEY` hoặc `KNOWLEDGE_DATABASE_URL`, hoặc `DATABASE_URL` là SQLite. BE gửi `AI_API_KEY` trong header
  theo contract v2.

## Biến môi trường

| AI service | Giá trị gợi ý |
|---|---|
| `ENVIRONMENT` | `production` |
| `AI_API_KEY` | secret (Key Vault) |
| `LLM_PROVIDER` | `gemini` hoặc `openai` (chọn sau eval) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | secret (Key Vault) |
| `DATABASE_URL` | PostgreSQL lưu request store (SQLite bị từ chối ngoài `development`) |
| `KNOWLEDGE_DATABASE_URL` | PostgreSQL có pgvector (kho chunk) |
| `LLM_TIMEOUT_SECONDS` | `45` |
| `MAX_OUTPUT_TOKENS` | `1500` |
| `SOURCE_FETCH_TIMEOUT_SECONDS` | `20` |
| `EMBED_ITEMS_PER_MINUTE` | `80` |
| `REQUEST_STALE_SECONDS` | `300` |
| `LEGACY_ROUTES_ENABLED` | `false` |

Phía BE (.NET) phải khớp: `OrganizationAi__BaseUrl` (URL nội bộ của service), `OrganizationAi__ApiKey` (cùng giá trị `AI_API_KEY`),
`OrganizationAi__TimeoutSeconds=180` và `OrganizationAi__LeaseSeconds=240` (lease phải lớn hơn timeout).

Lý do chọn 180 s: nguồn chưa index được embed ở luồng nền nên không nằm trong request; một request xấu nhất gồm embed nguồn
inline và câu hỏi, rồi một lần gọi LLM tới `LLM_TIMEOUT_SECONDS` (45 s). Timeout BE dài hơn tổng này để phần lớn request kết thúc bằng một response thật thay vì timeout.

Không có "lỗi có cấu trúc trước khi BE bỏ cuộc": theo contract của BE, khi kết quả không chắc chắn thì request ở lại
`NeedsReconcile AI_OUTCOME_UNKNOWN` (giữ reservation, **không gửi lại, không tự hoàn**). Cụ thể: BE timeout; AI trả
`500 AI_OUTCOME_UNKNOWN` (lỗi sau khi đã có thể gọi provider); AI trả `409 AI_REQUEST_IN_PROGRESS` (cùng `request_id` đang xử lý);
và khi admin reconcile, lookup `GET /v2/requests/{request_id}` trả `202` (vẫn Processing) — tất cả đều giữ request ở
`NeedsReconcile`. Chỉ `200` hợp lệ mới settle, lookup `404` mới `Failed AI_REQUEST_NOT_RECEIVED` (hoàn). Vòng recovery của AI
hoàn tất các row Processing quá `REQUEST_STALE_SECONDS`, nên lần reconcile sau sẽ nhận `200`.

## IFC worker

`ifc-worker/` chạy riêng (xem [ifc-worker/README.md](../ifc-worker/README.md)): VM hoặc App Service Linux với Python 3.12,
lệnh khởi động `uvicorn worker.server:app --host 0.0.0.0 --port 8080`. Blender (`BLENDER_PATH`) chỉ cài được trên VM.
Outbound tới BE và S3; inbound chỉ từ dispatcher của BE. Sau khi đổi toolchain (ví dụ bật Blender) cập nhật
`ProcessingWorker__AllowedToolchains__0` bằng `python -m worker.config`.

## Cơ sở dữ liệu

DB admin chạy một lần `rag-api/db/migrations/001_ai_service.sql` trên PostgreSQL. Migration này chỉ tạo schema `ai_service`, bảng
`requests` và role; **không cần pgvector**. pgvector chỉ cần cho bảng `knowledge_chunks` (`contracts/KnowledgeChunks.sql`, do BE sở
hữu migration). Tài khoản runtime của service không cần quyền DDL.

Supabase cài pgvector trong schema `extensions`; để kiểu `vector` và toán tử khoảng cách được tìm thấy, đặt search_path cho login
của AI service:

```sql
ALTER ROLE <ai_login> SET search_path = public, extensions;
```

### Retention `ai_service.requests`

Bảng request giữ payload và response của mọi request; không tự dọn. Dọn row đã `Completed` quá 90 ngày bằng job SQL định kỳ
(ví dụ `pg_cron` trên Supabase, chạy hằng ngày) với role có quyền `DELETE` (`fet3d_ai_service` có sẵn):

```sql
DELETE FROM ai_service.requests
WHERE status = 'Completed' AND completed_at < now() - interval '90 days';
```

Không xoá row `Received`/`Processing` (vòng recovery tự xử lý); chọn thời hạn không ngắn hơn khoảng thời gian admin BE có thể còn
reconcile request.

## Housekeeping định kỳ

Chạy `python -m app.index.housekeeping` (cần `KNOWLEDGE_DATABASE_URL`) để xoá chunk của nguồn BE không còn đánh dấu hợp lệ. Lịch gợi ý: mỗi ngày một lần, bằng WebJob (triggered), Azure Functions timer hoặc cron. Lệnh in `pruned N chunks` và thoát 0 khi thành công.

## Checklist nghiệm thu E2E với BE thật (chưa thực hiện)

- [ ] `GET /health` và `GET /ready` trả 200 qua mạng riêng từ BE; không truy cập được từ internet.
- [ ] BE gọi `organization/answer` với nguồn đã pin: trả `Answered` kèm citation đúng `document_id`/phiên bản.
- [ ] Nguồn sai hash hoặc không tải được: `AI_SOURCE_HASH_MISMATCH` / `AI_SOURCE_UNAVAILABLE` (422).
- [ ] Cùng `request_id`, cùng input: kết quả cũ, provider chỉ bị gọi một lần; khác input: `AI_REQUEST_CONFLICT` (409).
- [ ] Mô phỏng timeout/500: request BE chuyển `NeedsReconcile AI_OUTCOME_UNKNOWN`, không bị gửi lại; admin reconcile làm BE gọi
  `GET /v2/requests/{request_id}` của AI service và settle khi nhận `200` (`202` thì vẫn `NeedsReconcile`).
- [ ] Câu hỏi chứng nhận/sự cố thật: `RejectedBySafetyGate`; thiếu nguồn: `InsufficientEvidence`.
- [ ] `ScenarioDraft` với `bim` đã pin: `NeedsUserEdit`, anchor đúng `ifcGlobalId`.
- [ ] Trainee `TraineeAnswer` chỉ dùng nguồn Learn/SessionResult được BE cấp.
- [ ] Usage (`input_tokens`, `output_tokens`, `provider_units`) khớp bản ghi quota phía BE.
- [ ] Khởi động lại instance giữa lúc xử lý: vòng recovery hoàn tất request quá `REQUEST_STALE_SECONDS`.
- [ ] Housekeeping chạy theo lịch và ghi log `pruned N chunks`.
- [ ] `python -m evals.run_eval --provider <provider thật>` đạt ngưỡng đã thống nhất trước khi chọn provider.
