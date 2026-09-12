# Context — AI

## Hiện trạng đã kiểm tra

- Code ở [rag-api](../rag-api/README.md): Python, FastAPI, ChromaDB, OpenAI SDK; chưa phải toàn bộ BIM/IFC RAG trong thiết kế sản phẩm.
- [Điểm vào](../rag-api/app/main.py): `GET /health`, `POST /documents` (txt/md/pdf), `POST /chat`; chunking, loaders, store và client nằm trong `rag-api/app/rag/`.
- [Cấu hình](../rag-api/app/core/config.py) đọc môi trường và .env; không sao chép giá trị bí mật vào ghi chú. Requirements ở [requirements.txt](../rag-api/requirements.txt).
- Web và Mobile hiện gọi RAG API trực tiếp. Khi đổi hợp đồng upload/chat, kiểm tra tác động tới hai client; không mặc định BE đang proxy luồng này.

## Chạy và kiểm tra

Các lệnh sau chạy từ `rag-api/`, sau khi môi trường Python/phụ thuộc đã được chuẩn bị theo README:
- `python -m pytest tests/test_rag_primitives.py -q`: chunking và phần mở rộng tài liệu.
- `python -m pytest tests/test_health.py -q`: health route; TestClient/import app có phụ thuộc runtime. Nếu thiếu dependency, báo đúng lỗi, không gọi test là đạt hoặc tự sửa dependencies ngoài task.
- `python -m pytest tests -q`: toàn bộ test hiện có; không chứng minh chất lượng RAG, tenant isolation hay BIM pipeline.
- `python -m uvicorn app.main:app --reload`: chạy dev khi cần. Không gọi OpenAI thật hoặc ingest dữ liệu riêng để kiểm tra thay đổi hướng dẫn.
- Các lệnh trên là hướng dẫn từ source/test, không phải bằng chứng test đã đạt. Kết quả từng lần chạy nằm trong handoff local hoặc PR tương ứng.

## Thiết kế liên quan

Khi có checkout Docs bên cạnh, đọc `Docs/fire_evacuation_bim_rag_pccc.md` và overview cho phạm vi sản phẩm. RAG BIM là thiết kế, không được mô tả là đã triển khai ở API mẫu. Gợi ý PCCC cần chuyên gia thẩm tra, không phải chứng nhận an toàn hoặc hướng dẫn khẩn cấp thực tế. Nếu clone AI độc lập, không tự clone repo khác; yêu cầu tài liệu cần thiết khi task phụ thuộc nó.
