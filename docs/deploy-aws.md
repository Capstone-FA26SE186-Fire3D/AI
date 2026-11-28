# Triển khai rag-api trên AWS EC2

Tài liệu này mô tả cách `rag-api` **đang chạy thật** từ ngày 10/11/2026. Mọi thông số được đọc trực tiếp trên máy chủ ngày 25/11/2026 (#34). Tài liệu chỉ ghi **tên** biến môi trường và giá trị không bí mật; khoá và mật khẩu không có ở đây.

Thiết kế cũ cho Azure App Service vẫn giữ ở [deploy-azure.md](deploy-azure.md) để tham khảo các thông số dùng chung: probe, contract với BE, checklist nghiệm thu.

## 1. Tổng quan

```
BE (.NET, EC2 52.221.57.57, api.fet3d.io.vn)
   │  HTTPS + Authorization: Bearer AI_API_KEY
   ▼
56-10-105-247.sslip.io ─► EC2 56.10.105.247 ─► Caddy :443 ─┬─► uvicorn 127.0.0.1:8000 (rag-api)
                                                          └─► /kb/*  file tĩnh /var/www/fire3d-kb
rag-api ─► PostgreSQL Supabase (pooler, cổng 5432): ai_service.requests + knowledge_chunks (pgvector)
rag-api ─► https://vibi.top (cổng OpenAI-compatible) để trả lời; embedding chạy tại chỗ
```

- **Máy riêng**, không chung máy với BE: EC2 Ubuntu 26.04.1 LTS, x86_64, 2 vCPU, 1,9 GB RAM, 2 GB swap.
- **Tên miền**: `56-10-105-247.sslip.io`. sslip.io là DNS miễn phí, tên chứa IP nào thì trỏ về IP đó. Có thể đổi sang `ai.fet3d.io.vn`:
  1. thêm bản ghi A `ai` → `56.10.105.247`;
  2. đổi `$Domain` trong `deploy/aws/update-ai.ps1` rồi deploy lại;
  3. đổi `OrganizationAi__BaseUrl` của BE.
- **Không dùng Docker**: một tiến trình Python chạy bằng systemd.

## 2. Tiến trình

Unit `fire3d-ai.service`, do `deploy/aws/setup-ai.sh` tạo:

```ini
[Service]
User=fire3d
WorkingDirectory=/opt/fire3d-ai
EnvironmentFile=/opt/fire3d-ai/.env
ExecStart=/opt/fire3d-ai/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
```

- Thư mục:
  - `/opt/fire3d-ai/app`: mã nguồn;
  - `/opt/fire3d-ai/.venv`: Python 3.12.16, cài bằng `uv`;
  - `/opt/fire3d-ai/data/models`: model embedding `multilingual-e5-small`, bản int8 ONNX;
  - `/opt/fire3d-ai/.env`: biến môi trường, chỉ root đọc được.
- User hệ thống `fire3d`, không đăng nhập được.
- Lệnh thường dùng:

```bash
sudo systemctl restart fire3d-ai             # khởi động lại (khoảng 5–10 giây, BE tự gửi lại yêu cầu đang dở)
systemctl is-active fire3d-ai
curl -s http://127.0.0.1:8000/health         # sống
curl -s http://127.0.0.1:8000/ready          # sẵn sàng (DB, index)
sudo journalctl -u fire3d-ai -n 100 --no-pager
sudo journalctl -u caddy -n 50 --no-pager
```

Log là JSON từng dòng, có `request_id` và `duration_ms`. Không log nội dung khoá.

## 3. TLS, proxy và mạng

Caddy tự xin và gia hạn chứng chỉ Let's Encrypt. `/etc/caddy/Caddyfile`:

```
56-10-105-247.sslip.io {
    handle_path /kb/* {
        root * /var/www/fire3d-kb
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
```

- Cổng đang nghe: 22 (SSH), 80 và 443 (Caddy). uvicorn chỉ nghe ở `127.0.0.1:8000`, nên Internet không gọi thẳng vào được. `ufw` đang tắt; luật vào do security group của AWS quyết định (xem trên AWS console).
- **Bảo vệ hiện tại là bearer token**: mọi route `/v2/*` cần `Authorization: Bearer <AI_API_KEY>` (BE gửi). `/health` và `/ready` mở công khai và không trả dữ liệu.
- `/kb/*` phục vụ các tệp nguồn tri thức tự lưu trữ (tệp tĩnh, bytes cố định nên hash khớp). Chính service tải lại chúng qua địa chỉ công khai, nên nếu giới hạn cổng 443 chỉ cho IP của BE thì phải cho cả IP của chính máy AI.

## 4. Biến môi trường

File `/opt/fire3d-ai/.env` được chép từ bản ở máy người deploy (`rag-api-server.env`, nằm ngoài repo) mỗi lần chạy `update-ai.ps1`. Sửa giá trị thì sửa ở cả hai nơi, nếu không lần deploy sau sẽ đè lại.

| Biến | Giá trị đang dùng (không bí mật) | Ý nghĩa |
|---|---|---|
| `ENVIRONMENT` | `production` | Bắt buộc. Thiếu `AI_API_KEY`/DB thì app từ chối khởi động |
| `AI_API_KEY` | *(bí mật)* | Bearer BE gửi; phải trùng `OrganizationAi__ApiKey` của BE |
| `DATABASE_URL` | *(bí mật)*, Supabase pooler cổng 5432, role `ai_login` | Bảng `ai_service.requests` |
| `KNOWLEDGE_DATABASE_URL` | *(bí mật)*, cùng database | Bảng `knowledge_chunks` (pgvector) |
| `CHAT_PROVIDER` | `openai_compat` | Trả lời qua cổng OpenAI-compatible |
| `CHAT_BASE_URL` | `https://vibi.top…` | Cổng vibi |
| `CHAT_API_KEY` | *(bí mật)* | Khoá vibi (tính phí) |
| `CHAT_MODEL` | `gemini-3.6-flash` | Model trả lời |
| `CHAT_REASONING_EFFORT` | `low` | Mức "suy nghĩ" của model. `CHAT_ANSWER_REASONING_EFFORT` (tuỳ chọn) không đặt |
| `EMBED_PROVIDER` | `local` | Embedding tại chỗ, không gửi dữ liệu ra ngoài |
| `LOCAL_MODEL_DIR` | `/opt/fire3d-ai/data/models` | Thư mục model embedding |
| `LOCAL_EMBED_THREADS` | `2` | Bằng số vCPU |
| `EMBED_BATCH_SIZE` | `4` | Số đoạn mỗi lần embed |
| `EMBED_ITEMS_PER_MINUTE`, `EMBED_TOKENS_PER_MINUTE` | `100000`, `100000000` | Đặt rất cao vì embedding tại chỗ không có quota |
| `GENERAL_ANSWERS` | `true` | Trả lời câu thông thường khi không có nguồn phù hợp |
| `MAX_OUTPUT_TOKENS` | `4096` | Trần token đầu ra |
| `INLINE_CACHE_PATH` | `/opt/fire3d-ai/data/inline-embeddings.npz` | Giữ vector của bài Learn qua các lần khởi động lại và deploy (AI#43); để trống thì chỉ giữ trong RAM |
| `LEGACY_ROUTES_ENABLED` | `false` | Tắt route demo cũ |
| `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_CHAT_MODEL` | còn trong file, **không được dùng** khi đã có `CHAT_PROVIDER` + `EMBED_PROVIDER=local` | Có thể xoá |

Phía BE (`be-server.env`):

| Biến | Giá trị |
|---|---|
| `OrganizationAi__Enabled` | bật |
| `OrganizationAi__BaseUrl` | `https://56-10-105-247.sslip.io` |
| `OrganizationAi__ApiKey` | *(bí mật, trùng `AI_API_KEY`)* |
| `OrganizationAi__TimeoutSeconds` | `180` |
| `OrganizationAi__LeaseSeconds` | `240` (BE#205: đề xuất kịch bản được chờ tới `LeaseSeconds − 30`) |

## 5. Cơ sở dữ liệu

- Supabase, project mới từ 23/11/2026. Kết nối qua pooler, cổng 5432 (session mode) và `sslmode=require`.
- `ai_service.requests` do `rag-api/db/migrations/001_ai_service.sql` tạo. `knowledge_chunks` do BE sở hữu migration.
- Trên Supabase, pgvector nằm ở schema `extensions`. Role của AI cần **cả hai** lệnh sau, nếu không sẽ lỗi `vector type not found in the database` (đã gặp khi chuyển database ngày 25/11/2026):

```sql
GRANT USAGE ON SCHEMA extensions TO ai_login;
ALTER ROLE ai_login SET search_path = public, extensions;
```

## 6. Việc chạy định kỳ

**Housekeeping chunk**: `fire3d-ai-housekeeping.timer` chạy `python -m app.index.housekeeping` lúc **03:00 UTC** (10:00 giờ Việt Nam) mỗi ngày, với `Persistent=true` (máy tắt lúc 03:00 thì chạy bù khi bật). Job xoá chunk của các nguồn BE không còn đánh dấu hợp lệ, in `pruned N chunks` và thoát 0. Kiểm tra:

```bash
systemctl list-timers fire3d-ai-housekeeping.timer --no-pager
sudo journalctl -u fire3d-ai-housekeeping -n 20 --no-pager
```

Ngày 24 và 25/11/2026 job lỗi `vector type not found` do thiếu quyền ở mục 5; quyền đã được cấp ngày 25/11/2026.

**Dọn `ai_service.requests` sau 90 ngày: CHƯA có lịch trên EC2.** Housekeeping ở trên không dọn bảng này. Câu lệnh cần chạy định kỳ, bằng `pg_cron` trên Supabase hoặc thêm vào timer:

```sql
DELETE FROM ai_service.requests
WHERE status = 'Completed' AND completed_at < now() - interval '90 days';
```

## 7. Triển khai

CI (`.github/workflows/ci.yml`) chỉ chạy test, **không deploy**. Deploy chạy bằng tay từ máy của người giữ khoá SSH, dùng hai script trong `deploy/aws/`:

1. `git pull` repo AI. Đặt env production `rag-api-server.env` ở **thư mục chứa repo**, ví dụ `C:\do an\rag-api-server.env` khi repo ở `C:\do an\ai`. Để chỗ khác thì đặt biến `FIRE3D_AI_ENV`. Khoá SSH mặc định là `%USERPROFILE%\Downloads\fire3d-be.pem`, đổi bằng `FIRE3D_SSH_KEY`.
2. Chạy:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\aws\update-ai.ps1
   ```

   Các bước script làm:
   - nén `rag-api/app`, `contracts`, `requirements.txt`;
   - `scp` gói nén, `setup-ai.sh` và env lên máy;
   - chạy `setup-ai.sh`, gồm 6 bước: gói hệ thống và `uv`, Caddy, chép code và env, cài thư viện và tải model embedding, tạo service và timer và Caddyfile, kiểm tra `/health` và `/ready`;
   - cuối cùng **xoá bản env và gói nén** khỏi thư mục home trên máy chủ.

3. Kiểm tra từ ngoài: `https://56-10-105-247.sslip.io/ready` trả `{"status":"ready"}`. Thử thêm một câu hỏi thật qua web.

**Lùi bản**: máy chủ không giữ bản cũ. Checkout commit trước đó của repo AI rồi chạy lại `update-ai.ps1`. Env trên máy chủ có bản sao lưu `.env.bak` nếu từng được tạo khi sửa tay.

Thư viện đang chạy (`uv pip freeze`, 25/11/2026): [deploy-aws-pip-freeze.txt](deploy-aws-pip-freeze.txt). Các bản chính:
- `fastapi 0.162.0`, `uvicorn 0.54.0`, `pydantic 2.14.1`;
- `openai 1.109.1`, `fastembed 0.9.1`, `onnxruntime 1.31.1`;
- `psycopg 3.3.6`, `pgvector 0.4.2`.

## 8. Dung lượng và dọn dẹp

Ngày 25/11/2026 đĩa dùng 31% của 19 GB. Có thể xoá an toàn: cache `uv` (`/root/.cache/uv`, tải lại khi deploy) và `apt-get clean`. **Không xoá** `/opt/fire3d-ai/data/models`: đó là model embedding, xoá thì phải tải lại.
