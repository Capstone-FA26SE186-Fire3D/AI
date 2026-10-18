# Triển khai AI service lên Azure

Hướng dẫn này mô tả cách triển khai `rag-api` (FastAPI) cho môi trường thật. Đây là hướng dẫn thiết kế, chưa phải hạ tầng đã tạo hay đã nghiệm thu.

## Phương án mặc định: Azure App Service (Linux, code deploy)

- Runtime: Python 3.12 trên Linux, triển khai bằng code (zip/GitHub Actions), không cần image Docker.
- Startup command: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (đặt `WEBSITES_PORT=8000`). Thư mục ứng dụng là `rag-api/`; build cài `requirements.txt`.
- Bật Always On và đặt tối thiểu 1 instance: service có vòng lặp recovery (`RECOVERY_INTERVAL_SECONDS`) chạy nền, không được để ngủ hoặc scale về 0.
- Health check: `/health`.

Azure Container Apps vẫn khả thi, nhưng cần image build ở nơi khác; việc build image nằm ngoài phạm vi repo này.

## Bí mật và mạng

- Lưu `AI_API_KEY`, `GEMINI_API_KEY` (hoặc `OPENAI_API_KEY`), `DATABASE_URL`, `KNOWLEDGE_DATABASE_URL` trong Azure Key Vault; App Service tham chiếu bằng Key Vault reference (`@Microsoft.KeyVault(SecretUri=...)`) qua managed identity. Không đưa khoá vào repo hay FE/Mobile.
- Truy cập riêng: đặt service sau VNet integration/private endpoint (hoặc access restriction) để chỉ .NET API gọi được; client production không đi thẳng tới FastAPI.
- `ENVIRONMENT=production` bắt buộc `AI_API_KEY`; BE gửi khoá này trong header theo contract v2.

## Biến môi trường

| AI service | Giá trị gợi ý |
|---|---|
| `ENVIRONMENT` | `production` |
| `AI_API_KEY` | secret (Key Vault) |
| `LLM_PROVIDER` | `gemini` hoặc `openai` (chọn sau eval) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | secret (Key Vault) |
| `DATABASE_URL` | PostgreSQL lưu request store |
| `KNOWLEDGE_DATABASE_URL` | PostgreSQL có pgvector (kho chunk) |
| `LLM_TIMEOUT_SECONDS` | `45` |
| `REQUEST_STALE_SECONDS` | `300` |
| `LEGACY_ROUTES_ENABLED` | `false` |

Phía BE (.NET) phải khớp: `OrganizationAi__BaseUrl` (URL nội bộ của service), `OrganizationAi__ApiKey` (cùng giá trị `AI_API_KEY`), `OrganizationAi__TimeoutSeconds=60`. Timeout BE (60 s) phải lớn hơn `LLM_TIMEOUT_SECONDS` (45 s) để AI trả lỗi có cấu trúc trước khi BE bỏ cuộc.

## Cơ sở dữ liệu

DB admin chạy một lần `rag-api/db/migrations/001_ai_service.sql` trên PostgreSQL (cần extension `pgvector`; `contracts/KnowledgeChunks.sql` do BE sở hữu bảng nguồn). Tài khoản runtime của service không cần quyền DDL.

## Housekeeping định kỳ

Chạy `python -m app.index.housekeeping` (cần `KNOWLEDGE_DATABASE_URL`) để xoá chunk của nguồn BE không còn đánh dấu hợp lệ. Lịch gợi ý: mỗi ngày một lần, bằng WebJob (triggered), Azure Functions timer hoặc cron. Lệnh in `pruned N chunks` và thoát 0 khi thành công.

## Checklist nghiệm thu E2E với BE thật (chưa thực hiện)

- [ ] `GET /health` trả 200 qua mạng riêng từ BE; không truy cập được từ internet.
- [ ] BE gọi `organization/answer` với nguồn đã pin: trả `Answered` kèm citation đúng `document_id`/phiên bản.
- [ ] Nguồn sai hash hoặc không tải được: `AI_SOURCE_HASH_MISMATCH` / `AI_SOURCE_UNAVAILABLE` (422).
- [ ] Cùng `request_id`, cùng input: kết quả cũ, provider chỉ bị gọi một lần; khác input: `AI_REQUEST_CONFLICT` (409).
- [ ] Mô phỏng timeout: BE tra `GET /api/ai/requests/{requestId}` trước khi retry.
- [ ] Câu hỏi chứng nhận/sự cố thật: `RejectedBySafetyGate`; thiếu nguồn: `InsufficientEvidence`.
- [ ] `ScenarioDraft` với `bim` đã pin: `NeedsUserEdit`, anchor đúng `ifcGlobalId`.
- [ ] Trainee `TraineeAnswer` chỉ dùng nguồn Learn/SessionResult được BE cấp.
- [ ] Usage (`input_tokens`, `output_tokens`, `provider_units`) khớp bản ghi quota phía BE.
- [ ] Khởi động lại instance giữa lúc xử lý: vòng recovery hoàn tất request quá `REQUEST_STALE_SECONDS`.
- [ ] Housekeeping chạy theo lịch và ghi log `pruned N chunks`.
- [ ] `python -m evals.run_eval --provider <provider thật>` đạt ngưỡng đã thống nhất trước khi chọn provider.
