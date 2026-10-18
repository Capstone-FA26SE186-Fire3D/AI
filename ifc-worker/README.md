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

## Chạy trên server

```
cd ifc-worker
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
export BE_BASE_URL=... WORKER_KEY=... S3_BUCKET=... S3_REGION=... ENVIRONMENT=production
.venv/bin/uvicorn worker.server:app --host 0.0.0.0 --port 8080
```

- `GET /health` trả `{"status":"ok"}`; `POST /deliveries` chỉ nhận từ dispatcher của BE (header `X-Worker-Key`).
- Production bắt buộc có `S3_BUCKET`. Khi `ENVIRONMENT=development` và không có `S3_BUCKET`, worker dùng thư mục
  `WORKER_LOCAL_STORAGE` (mặc định `./data/storage`).
- Đặt sau reverse proxy HTTPS; chỉ mở inbound cho BE, outbound tới BE và S3.

## Blender (tuỳ chọn)

Đặt `BLENDER_PATH` (ví dụ `/opt/blender/blender`). Sau khi xuất `preview.glb`, worker chạy Blender nền để thêm UV map
thứ hai `UVMap_Lightmap` (không chồng, 0..1) cho mỗi mesh, giữ tên node và custom properties. Lỗi Blender làm job thất bại.
Khi `BLENDER_PATH` được đặt, chuỗi toolchain có thêm `+blender-x.y`: **phải cập nhật** `ProcessingWorker__AllowedToolchains__0`
bằng đầu ra mới của `python -m worker.config`.

## Ngoài phạm vi

- Thay asset theo bbox, NavMesh / lưới hazard, gộp nhiều IFC.

## Chạy test

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q
```
