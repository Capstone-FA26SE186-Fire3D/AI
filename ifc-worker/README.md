# ifc-worker

Tiến trình worker xử lý IFC của Fire3D AI. Nhận delivery từ dispatcher của BE, claim job qua gate
có lease (`/internal/processing/jobs/{id}/claim|renew|outputs|complete|fail`), chạy xử lý, upload kết quả lên S3.

## Biến môi trường

| Biến | Ý nghĩa |
| --- | --- |
| `BE_BASE_URL` | URL gốc của BE (gate nội bộ) |
| `WORKER_KEY` | Khoá máy, dùng cho header `X-Worker-Key` (cả chiều nhận và gọi gate); tối thiểu 32 ký tự (khớp `MachineKey` 32–512 của BE), ngắn hơn thì worker không khởi động |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | Cấu hình S3 (key trần dùng `S3_BUCKET`; key `s3://bucket/key` tự tách) |
| `BLENDER_PATH` | Tuỳ chọn, đường dẫn Blender |
| `MAX_SOURCE_BYTES` | Giới hạn file nguồn (mặc định 524288000) |
| `ENVIRONMENT` | `development` / `production` |
| `MAX_CONCURRENT_JOBS` | Số job chạy đồng thời (mặc định 1); khi hết slot, `POST /deliveries` trả 503 `WORKER_BUSY` trước khi claim để dispatcher gửi lại |

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
- Job package (claim có `scenarioVersionId`) không thuộc worker này: worker ACK delivery (claim đã commit) rồi gọi `fail`
  ngay với lý do "Package jobs are handled by the Unity package worker".
- Đặt sau reverse proxy HTTPS; chỉ mở inbound cho BE, outbound tới BE và S3.

## Blender (tuỳ chọn)

Đặt `BLENDER_PATH` (ví dụ `/opt/blender/blender`). Sau khi xuất `preview.glb`, worker chạy Blender nền để thêm UV map
thứ hai `UVMap_Lightmap` (không chồng, 0..1) cho mỗi mesh, giữ tên node và custom properties. Lỗi Blender làm job thất bại.
Khi `BLENDER_PATH` được đặt, chuỗi toolchain có thêm `+blender-x.y`: **phải cập nhật** `ProcessingWorker__AllowedToolchains__0`
bằng đầu ra mới của `python -m worker.config`.

## Metadata cho Unity

`building_metadata.json` dùng cùng hệ tọa độ với GLB (mét, Y-up, tay phải, đã trừ cùng độ dịch gốc median như mesh; Unity tự lật X).

- `spaces[].bbox = [[minX, minY, minZ], [maxX, maxY, maxZ]]` lấy từ hình học `IfcSpace`. Phòng không có hình học hợp lệ không có `bbox` và được báo `IFC_NO_BODY_GEOMETRY` (Warning); không tạo bbox giả. Unity dùng bbox để dựng vùng phòng và đèn phòng.
- `portals[]` có thêm `{"type": "stair", "ifcGlobalId", "ifcClass", "floor"}` cho `IfcStair`, `IfcStairFlight`, `IfcRamp`, `IfcRampFlight` có node GLB đặt tên đúng GlobalId; Unity nhận diện cầu thang theo tên node để NPC/người chơi đi giữa các tầng.

Còn khác Unity `Tools/GeometryWorker` (cần xử lý trước khi chuyển production sang worker này): mã tầng (`B1, L1…` so với `L1…Ln`), quy ước `rotationY`/độ cao `y` của cửa trong `interactables`, và `coordinateTransform` chưa có trong `building_metadata.json`.

## Ngoài phạm vi

- Thay asset theo bbox, NavMesh / lưới hazard, gộp nhiều IFC.

## Chạy test

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q
```
