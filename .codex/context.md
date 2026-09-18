# Context — AI

## Hiện trạng đã kiểm tra

- Code ở [rag-api](../rag-api/README.md): Python, FastAPI, ChromaDB, OpenAI SDK; đây là trạng thái prototype hiện có, không phải storage/provider production đã chốt.
- [Điểm vào](../rag-api/app/main.py): `GET /health`, `POST /documents` (txt/md/pdf), `POST /chat`; chunking, loaders, store và client nằm trong `rag-api/app/rag/`.
- [Cấu hình](../rag-api/app/core/config.py) đọc môi trường và .env; không sao chép giá trị bí mật vào ghi chú. Requirements ở [requirements.txt](../rag-api/requirements.txt).
- Web và Mobile hiện gọi RAG API trực tiếp trong prototype. Kiến trúc đích dùng Nginx trước .NET API; production client không đi thẳng tới FastAPI. Khi đổi hợp đồng upload/chat, kiểm tra tác động tới hai client.

## Kiến trúc đích đã thống nhất — 2026-09-17

- AI/RAG và IFC processing dùng Python + FastAPI; IFC extraction dùng IfcOpenShell khi phù hợp.
- Vector store production là `pgvector` trong Supabase PostgreSQL. ChromaDB chỉ còn là implementation prototype cần migration có kế hoạch; không thêm dữ liệu production mới dựa trên ChromaDB.
- LLM sẽ chọn một trong OpenAI API hoặc Google Gemini API (khóa/cấu hình qua Google AI Studio). Giữ provider adapter, output schema, safety gate và evaluation dùng chung; chưa được mô tả cả hai là production provider.
- RAG data access phải tenant-scoped trên cả metadata filter và vector query. Không đưa Supabase service-role key hoặc LLM key vào FE/Mobile; không gửi raw IFC hay dữ liệu thừa sang LLM.
- Raw IFC/package dùng AWS S3 theo signed URL do backend cấp. Supabase Auth không nằm trong stack; identity dùng Firebase Authentication và quyền nghiệp vụ do BE/PostgreSQL quyết định.
- IFC pipeline dùng lại cho nhiều Building: IfcOpenShell/IfcConvert trích geometry, tầng/phòng/cửa/cầu thang/GlobalId và quality issues; Blender chạy script tối ưu; Unity Editor build worker tạo collider/NavMesh/runtime package. Python không tự biến GLB thành Unity AssetBundle nếu thiếu Unity Editor worker.
- Artifact/facts phải immutable theo revision, giữ units/coordinate system/GlobalId, checksum và S3 key. Thiếu semantic hoặc connectivity tạo issue để OrganizationUser sửa/xác nhận; thay IFC tạo revision mới, còn thay scenario dùng lại geometry tương thích.
- RAG có hai audience: `organization` (giải thích BIM/PCCC, gợi ý scenario draft có nguồn) và `trainee` (hỏi đáp kiến thức, Learn, debrief cá nhân). AI chỉ trả draft/evidence; không tự sửa editor, publish, route hoặc scoring. Kho common và organization phải tenant/scope-filter riêng.
- Output phải phân biệt `KnowledgeAnswer` (câu trả lời kiến thức cho OrganizationUser/Trainee, citation nguồn chung bắt buộc) và `ScenarioDraft` (chỉ khi OrganizationUser yêu cầu tạo cấu hình scenario, trạng thái `NeedsUserEdit`). `InsufficientEvidence` và `RejectedBySafetyGate` là trạng thái riêng; `NeedsUserEdit` không áp dụng cho KnowledgeAnswer. BIM anchor chỉ bắt buộc khi output dùng BIM facts. Kiểm tra chuyên môn nếu cần là policy/assignment, không tạo thêm system role.
- AI/RAG là service Python/FastAPI triển khai riêng trên Azure; Container Apps là phương án triển khai đề xuất, chưa phải SKU/hạ tầng đã tạo. Production client gọi `.NET API`; BE gửi request/idempotency ID, canonical input hash, audience, allowed scope và source/revision version rồi gọi AI nội bộ. AI trả `request_id`, response status/type, citations/source version, BIM anchors khi có, model/version và usage kỹ thuật; AI không trả overage/đơn giá và không sở hữu billing.
- Nginx là reverse proxy ở trước .NET API trong kiến trúc đích; AI service chỉ nhận request nội bộ từ backend sau khi backend kiểm tra identity, tenant, scope và quota.
- Timeout phải tra cứu `GET /api/ai/requests/{requestId}` trước retry; cùng idempotency key/cùng input trả kết quả cũ, khác input bị từ chối. ChromaDB/OpenAI vẫn là prototype; production dùng pgvector và một provider LLM sau evaluation.
- IFC processing và playtest orchestration phải trả logical job/attempt/lease/toolchain/artifact/hash/QA provenance. Artifact/validation pin attempt hiện hành; kết quả hết lease không được ghi đè. Organization playtest dùng draft/version package đã verify; start chỉ được phép với Trial còn quota thử hoặc Building entitlement Active, không tạo learner session và không mở bằng QR Trainee. ValidationRun/ValidationIssue là bằng chứng gate trước publish/playtest.
- AI service phải trả usage metadata/request id cho BE; quota, pooled reservation allocation, overage, consent, policy/đơn giá snapshot và idempotency thuộc backend, không tự tính ở AI/FE/Mobile. AI không gọi reserve/settle/close billing và không có quyền accounting DML. BE ghi result qua contract có kiểm tra trạng thái/evidence; cùng request ID cùng evidence replay là no-op, evidence khác là conflict. Chuyển ChromaDB → pgvector là công việc triển khai tiếp theo, chưa hoàn tất trong API prototype.
- IFC/Blender worker và Unity Editor build worker chạy độc lập với interactive RAG, nhận job qua outbox/queue có lease, attempt, input hash, artifact/hash và validation provenance. Worker không ghi payment, entitlement hoặc publish trực tiếp.

## Chạy và kiểm tra

Các lệnh sau chạy từ `rag-api/`, sau khi môi trường Python/phụ thuộc đã được chuẩn bị theo README:
- `python -m pytest tests/test_rag_primitives.py -q`: chunking và phần mở rộng tài liệu.
- `python -m pytest tests/test_health.py -q`: health route; TestClient/import app có phụ thuộc runtime. Nếu thiếu dependency, báo đúng lỗi, không gọi test là đạt hoặc tự sửa dependencies ngoài task.
- `python -m pytest tests -q`: toàn bộ test hiện có; không chứng minh chất lượng RAG, tenant isolation hay BIM pipeline.
- `python -m uvicorn app.main:app --reload`: chạy dev khi cần. Không gọi OpenAI thật hoặc ingest dữ liệu riêng để kiểm tra thay đổi hướng dẫn.
- Các lệnh trên là hướng dẫn từ source/test, không phải bằng chứng test đã đạt. Kết quả từng lần chạy nằm trong handoff local hoặc PR tương ứng.

## Thiết kế liên quan

Khi có checkout Docs bên cạnh, đọc `Docs/fire_evacuation_bim_rag_pccc.md` và overview cho phạm vi sản phẩm. RAG BIM là thiết kế, không được mô tả là đã triển khai ở API mẫu. Gợi ý PCCC cần chuyên gia thẩm tra, không phải chứng nhận an toàn hoặc hướng dẫn khẩn cấp thực tế. Nếu clone AI độc lập, không tự clone repo khác; yêu cầu tài liệu cần thiết khi task phụ thuộc nó.

## Invariant bổ sung sau review — 2026-09-18

- AI request được backend authorize ngay khi INSERT theo audience, user, tenant, Building và policy version; request mới vào `Accepted` không có result. Policy, identity và canonical input hash bất biến sau tiếp nhận. User bị khóa sau đó không chặn reconcile.
- FastAPI chỉ trả request/result/citations/model và usage kỹ thuật. Backend sở hữu quota, consent, overage, đơn giá và settlement; timeout phải tra `GET /api/ai/requests/{requestId}` trước retry.
- IFC/Blender/Unity worker dùng logical job `input_hash`; claim lease hiện hành trả Busy, job thành công replay được, attempt hết lease bị fencing. Kết quả phải khớp attempt/artifact/validation hiện hành; worker không publish.

## Contract hardening — 2026-09-18

- AI request chỉ tạo ở `Accepted` sau khi BE kiểm tra audience/tenant/Building/policy; AI không ghi sẵn result/citation/model/usage và không sửa terminal result. AI trả usage kỹ thuật, request ID, citations/model/version; BE sở hữu quota, overage, consent và amount.
- Timeout dùng request-status/reconcile, không hoàn reservation rồi chạy lại mù. Policy version và source/version đã áp dụng là immutable history.
- Worker claim/renew/accept/fail/requeue khóa logical job trước attempt. Claim trả `Claimed`, `Busy`, `AlreadyCompleted`, `NotClaimable` hoặc `Conflict`; chỉ `Claimed` cấp lease token mới. Requeue `Failed` idempotent qua outbox; `Cancelled` terminal.
- Artifact manifest do worker tạo phải có manifest hash và build target; package provenance phải khớp artifact/validation pin trước khi BE cho publish hoặc playtest.
- Capability manifest phải là array mà mọi phần tử là chuỗi không rỗng; artifact/validation provenance phải đúng attempt/job/revision/scenario/hash. Đây là thiết kế target, chưa chạy concurrency/database test.
