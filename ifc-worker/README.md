# ifc-worker

Tiến trình worker xử lý IFC của Fire3D AI. Nhận delivery từ dispatcher của BE, claim job qua gate
có lease (`/internal/processing/jobs/{id}/claim|renew|outputs|complete|fail`), chạy xử lý, upload kết quả lên S3.

## Biến môi trường

| Biến | Ý nghĩa |
| --- | --- |
| `BE_BASE_URL` | URL gốc của BE (gate nội bộ) |
| `WORKER_KEY` | Khoá máy, dùng cho header `X-Worker-Key` (cả chiều nhận và gọi gate) |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | Cấu hình S3 (key trần dùng `S3_BUCKET`; key `s3://bucket/key` tự tách) |
| `BLENDER_PATH` | Tuỳ chọn, đường dẫn Blender |
| `MAX_SOURCE_BYTES` | Giới hạn file nguồn (mặc định 524288000) |
| `ENVIRONMENT` | `development` / `production` |

Xem `.env.example`.

## Cấu hình phía BE

- `ProcessingWorker__WorkerUrl=https://<host>/deliveries`
- `ProcessingWorker__MachineKey` = giá trị `WORKER_KEY`
- `ProcessingWorker__AllowedToolchains__0` phải bằng chuỗi toolchain in ra bởi:

```
python -m worker.config
```

## Chạy test

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q
```
