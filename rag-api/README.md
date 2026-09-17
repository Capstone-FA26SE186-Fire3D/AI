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
