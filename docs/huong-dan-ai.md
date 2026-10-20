# Cấu trúc tính năng và hướng dẫn sử dụng AI Fire3D

*Tài liệu đọc hiểu và thực hành trên Windows*

Phiên bản tài liệu ngày 19 tháng 10 năm 2026
Mốc mã nguồn main tại commit 4930fa8

Hệ thống gồm hai dịch vụ Python: RAG API trả lời câu hỏi có nguồn và tạo bản nháp kịch bản; IFC worker chuyển mô hình IFC thành dữ liệu hình học và metadata. Muốn thử hỏi đáp nhanh, bắt đầu với test offline, sau đó thêm API key để dùng mô hình thật.

### Tài liệu giúp bạn làm gì

Bạn có thể xác định chức năng của từng thư mục, hiểu đường đi của câu hỏi và file IFC, chuẩn bị môi trường chạy thử, gọi API bằng PowerShell và đọc các trạng thái trả về. Các tính năng dưới đây là hành vi trong code; kết quả vận hành production cần nghiệm thu riêng.

## Mục lục

- [Các tính năng hiện có](#phan-1)
- [Cấu trúc thư mục và trách nhiệm](#phan-2)
- [Luồng RAG và dữ liệu](#phan-3)
- [Chuẩn bị môi trường và test offline](#phan-4)
- [Cấu hình mô hình thật và mở API](#phan-5)
- [Gửi câu hỏi bằng PowerShell](#phan-6)
- [Tạo bản nháp kịch bản](#phan-7)
- [Xử lý IFC và cách chạy worker](#phan-8)
- [Lỗi thường gặp và giới hạn](#phan-9)
- [Kiểm thử tích hợp và tài liệu tham chiếu](#phan-10)

### Thuật ngữ ngắn

RAG: tìm tài liệu liên quan rồi đưa vào mô hình để tạo câu trả lời. Embedding: biểu diễn văn bản bằng vector để tìm nội dung gần nghĩa. Chunk: một đoạn tài liệu. Citation: thông tin trích dẫn. BIM hoặc IFC: dữ liệu mô hình công trình. Backend hoặc BE: dịch vụ .NET quản lý nghiệp vụ.

<a id="phan-1"></a>

## Các tính năng hiện có

| Tính năng | Đầu vào và kết quả | Điều kiện |
| --- | --- | --- |
| Hỏi đáp cho tổ chức | Câu hỏi và nguồn được phép → KnowledgeAnswer có citation. | POST organization/answer |
| Hỏi đáp cho học viên | Nguồn Learn hoặc nội dung được BE cấp → câu trả lời dễ hiểu. | POST trainee/answer |
| Giải thích kết quả học tập | SessionResult và context Result → giải thích kết quả đã lưu. | Dùng luồng trainee; không chấm lại điểm. |
| Tạo nháp kịch bản | Nguồn kiến thức và BIM đã ghim → state cùng ghi chú chỉnh sửa. | Chỉ organization; cần BIM và capability phù hợp. |
| Tìm kiếm kiến thức | Đọc tài liệu, chia đoạn, embedding và tìm theo ngữ nghĩa lẫn từ khóa. | pgvector hoặc MemoryIndex khi development. |
| Kiểm tra câu trả lời | Kiểm tra citation, chuyển plain text và chặn một số nhóm nội dung. | Safety gate theo cụm từ và kiểm tra cấu trúc. |
| Chống request trùng | Lưu trạng thái, trả kết quả cũ và phục hồi request bị treo. | Request store SQLite hoặc PostgreSQL. |
| Xử lý mô hình IFC | IFC → preview.glb và building_metadata.json cùng QA issues. | IFC worker, gate của BE và storage. |
| Nhận diện thành phần IFC | Tầng, phòng, cửa, cầu thang, thiết bị và vật liệu. | Dựa vào thuộc tính IFC và quy tắc từ khóa. |
| Kiểm thử và đánh giá | Unit/integration tests và bộ eval 16 ca. | Fake chạy offline; model thật cần API key. |

### Những việc hệ thống không tự thực hiện

AI không quyết định quyền người dùng, trừ tiền, cấp quota, publish kịch bản hay kết luận đạt bài đánh giá. Backend giữ các quyết định đó. IFC worker không build Unity AssetBundle, NavMesh hoặc mô phỏng lửa; các công việc runtime thuộc Unity và worker riêng.

Đầu ra tư vấn hoặc bản nháp không phải chứng nhận công trình đạt chuẩn PCCC. Người dùng cần xem citation, assumptions và limitations trước khi dùng kết quả.

<a id="phan-2"></a>

## Cấu trúc thư mục và trách nhiệm

```text
ai/
  rag-api/
    app/
      main.py           Khởi tạo ứng dụng FastAPI
      core/             Settings và logging
      v2/               Routes, xác thực, schema
      requests/         Lưu request, dedup, recovery
      sources/          Tải nguồn, đọc nội dung, chia đoạn
      index/            pgvector, memory, xếp hạng tìm kiếm
      llm/              OpenAI, Gemini và fake provider
      answering/        Prompt, RAG, safety, scenario draft
      legacy/ rag/      Các phần API RAG phiên bản cũ
      pccc/ bim/        Các phần tư vấn và BIM phiên bản cũ
    contracts/          Schema trao đổi với BE
    db/                 Migration request store
    tests/ evals/       Test tự động và bộ đánh giá
  ifc-worker/
    worker/
      server.py         Nhận delivery từ backend
      runner.py         Chạy job và gia hạn lease
      gate_client.py    Gọi gate xử lý job của BE
      storage.py        S3 hoặc storage local
      pipeline/         Trích xuất, phân loại, GLB, metadata, QA
    config/             Quy tắc từ khóa và vật liệu
    scripts/            Script Blender
    tests/              Kiểm thử worker
  docs/                 Hướng dẫn triển khai
  .github/workflows/    GitHub Actions CI
```

### Nên đọc code theo thứ tự nào

Luồng hỏi đáp: app/main.py → v2/router.py → requests/service.py → sources/resolver.py → answering/pipeline.py → llm/. Nếu tìm cách tạo kịch bản, đọc tiếp answering/scenario.py và answering/prompts.py.

Luồng IFC: worker/server.py → runner.py → pipeline/process.py. Sau đó đọc extract.py, classify.py, geometry.py, glb.py, metadata.py và qa.py để hiểu từng bước biến đổi.

### Phân biệt phiên bản mới và cũ

Luồng hiện hành dùng /v2 và mặc định LEGACY_ROUTES_ENABLED=false. Các route /documents, /chat và /pccc/* chỉ có khi bật cờ legacy. Phần hướng dẫn upload/chat ở đầu README thuộc luồng cũ; không dùng nó để suy ra hành vi mặc định của v2.

<a id="phan-3"></a>

## Luồng RAG và dữ liệu

```text
Web hoặc Mobile
  → Backend .NET kiểm tra quyền và giới hạn
  → RAG API kiểm tra Bearer và request
  → Chuẩn bị nguồn và tìm các đoạn liên quan
  → OpenAI hoặc Gemini sinh JSON
  → Kiểm tra output và lưu kết quả
  → Backend trả kết quả cho người dùng
```

### Từ nguồn dữ liệu đến câu trả lời

1. Backend gửi request_id, input_hash, câu hỏi, audience, sources và limits. API yêu cầu X-Request-Id trùng request_id. Backend chịu trách nhiệm tính hash đầu vào và chọn đúng nguồn theo quyền người dùng.

2. RequestService kiểm tra trùng ID. Cùng ID và hash đã hoàn tất thì trả kết quả cũ; khác hash thì conflict. Trạng thái lưu nội bộ đi qua Received, Processing và Completed.

3. KnowledgeSource có thể tải từ HTTPS, xác minh SHA-256 rồi đọc PDF, Markdown, HTML hoặc TXT. Đoạn văn được chia khoảng 900 ký tự, chồng lặp 150 ký tự, kèm vị trí trang hoặc đoạn. PDF scan không có lớp text chưa có OCR trong luồng này.

4. Nội dung được embedding. Tài liệu KnowledgeSource được lưu vào index; các nguồn inline được chuẩn bị trong request. Truy vấn tìm kiếm giới hạn ở danh sách ID nguồn đã ghim, kết hợp vector với từ khóa và chọn tối đa 8 đoạn trước khi cắt theo ngân sách.

5. Mô hình nhận câu hỏi, ngữ cảnh và đoạn nguồn để sinh JSON. Code loại citation không thuộc các đoạn tìm được, làm sạch văn bản và kiểm tra safety. Kết quả gồm recommendation, citations, confidence, assumptions, limitations và usage.

| Loại nguồn | Vai trò |
| --- | --- |
| KnowledgeSource | Tài liệu kiến thức có URI và hash xác minh. |
| LearnPost | Tiêu đề, tóm tắt và các block bài Learn. |
| LibraryVersion | Nội dung thư viện theo phiên bản. |
| TrainingSnapshot | Snapshot nội dung huấn luyện do BE cung cấp. |
| SessionResult | Dữ liệu kết quả phiên đã được BE cấp quyền. |

Không có đoạn nguồn phù hợp hoặc thiếu citation hợp lệ thì trả InsufficientEvidence. Kho index không tự thay thế authorization; backend phải kiểm tra quyền và tình trạng nguồn mỗi lần yêu cầu mới.

<a id="phan-4"></a>

## Chuẩn bị môi trường và test offline

Các lệnh trong tài liệu dùng PowerShell trên Windows và Python 3.12. Thay `DUONG_DAN_TOI_AI` trong ví dụ bằng đường dẫn checkout repo AI trên máy của bạn. Dùng môi trường `.venv` riêng cho từng dịch vụ; chạy `pip check` để kiểm tra dependency.

### Bước 1 mở đúng thư mục

```powershell
cd 'DUONG_DAN_TOI_AI\rag-api'
```

Nếu máy đã có .venv thì dùng trực tiếp. Trên máy mới hoặc chưa có môi trường, tạo và cài dependency như sau; không cần chạy lại mỗi lần thử.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

### Bước 2 chạy bộ test

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Đọc dòng tổng kết passed, failed và skipped. Test PostgreSQL tự bỏ qua khi không đặt FIRE3D_AI_TEST_PG_DSN. Vì vậy kết quả pass có skipped không chứng minh kết nối pgvector đã chạy đúng.

### Bước 3 chạy bộ đánh giá giả lập

```powershell
.\.venv\Scripts\python.exe -m evals.run_eval `
  --provider fake --out evals/reports/local
```

Mở evals/reports/local/report.md hoặc report.json. Bộ dữ liệu có 16 ca cho trả lời có nguồn, thiếu bằng chứng, safety và các tình huống khác. Kiểm tra trường failures và từng chỉ số; chương trình eval hiện trả mã thoát 0 cả khi báo cáo có ca không đạt.

### Offline chứng minh được điều gì

Provider fake giúp thử luồng dữ liệu, citation và các cổng kiểm tra mà không cần Internet, API key, backend hay Docker. Nó không đánh giá chất lượng diễn đạt hoặc kiến thức của OpenAI/Gemini. Muốn đánh giá mô hình thật, chuyển sang phần cấu hình mô hình thật.

### Tiêu chí hoàn tất bước đầu

Python chạy được trong .venv; bộ test có kết quả rõ ràng; báo cáo eval được tạo và đã đọc failures. Nếu gặp lỗi quyền ghi cache, có thể thử pytest tests -q -p no:cacheprovider; lỗi thư mục tạm khác cần được xử lý riêng.

<a id="phan-5"></a>

## Cấu hình mô hình thật và mở API

### Bước 1 cấu hình trong file env

Tạo file .env ở DUONG_DAN_TOI_AI\rag-api. Chọn một provider. Thay phần giữ chỗ bằng key trên máy; không đưa key vào tài liệu, commit hoặc tin nhắn.

```dotenv
ENVIRONMENT=development
LLM_PROVIDER=gemini
GEMINI_API_KEY=THAY_BANG_KEY_CUA_BAN
DATABASE_URL=sqlite:///./data/ai_requests_demo.db
KNOWLEDGE_DATABASE_URL=
AI_API_KEY=local-demo-key
LEGACY_ROUTES_ENABLED=false
```

Nếu dùng OpenAI: đổi LLM_PROVIDER=openai và thêm OPENAI_API_KEY. Mặc định code dùng gpt-4.1-mini và text-embedding-3-small cho OpenAI; Gemini dùng gemini-2.5-flash và gemini-embedding-001. Các tên này là mặc định trong repo, có thể thay bằng biến cấu hình tương ứng.

AI_API_KEY là khóa nội bộ giữa BE hoặc client test với RAG API, khác OPENAI_API_KEY/GEMINI_API_KEY của nhà cung cấp. local-demo-key chỉ dùng cho thử nghiệm trên localhost.

### Bước 2 thử bộ câu hỏi bằng mô hình thật

```powershell
.\.venv\Scripts\python.exe -m evals.run_eval `
  --provider gemini --out evals/reports/gemini-local
```

Với OpenAI, thay gemini bằng openai và đổi thư mục báo cáo. Lệnh gọi API thật, cần key có quyền sử dụng và hạn mức phù hợp; có thể phát sinh chi phí. Đọc failures, citation coverage và câu trả lời thực tế thay vì chỉ nhìn mã thoát.

### Bước 3 chạy server

```powershell
New-Item -ItemType Directory -Force data | Out-Null
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Giữ cửa sổ này mở. Truy cập http://127.0.0.1:8000/docs để xem API; kiểm tra /health và /ready. /health chỉ báo tiến trình hoạt động; /ready dựng service và thăm dò request store, không chứng minh mọi phụ thuộc hoặc API mô hình đã hoạt động.

Với development và không có KNOWLEDGE_DATABASE_URL, index dùng bộ nhớ. Request store dùng SQLite trong data. Chưa cần PostgreSQL hoặc backend thật để gửi mẫu LearnPost inline ở phần gửi câu hỏi. Đổi provider hoặc sửa .env thì khởi động lại server.

<a id="phan-6"></a>

## Gửi câu hỏi bằng PowerShell

Mở PowerShell thứ hai trong rag-api, trong khi server vẫn chạy. Mẫu dưới đây dùng fixture có sẵn để giả lập nguồn Learn do backend cấp. Đây là thao tác test local, không thay thế luồng authorization production.

```powershell
cd 'DUONG_DAN_TOI_AI\rag-api'
$req = Get-Content -Raw -Encoding UTF8 `
  '.\tests\fixtures\v2\trainee-answer.json' | ConvertFrom-Json
$req.request_id = [guid]::NewGuid().ToString()
$req.limits.max_units = 6000

# Hash cho demo local; BE thật dùng canonical hash của BE.
$hashText = $req | ConvertTo-Json -Depth 30 -Compress
$sha = [System.Security.Cryptography.SHA256]::Create()
$bytes = [System.Text.Encoding]::UTF8.GetBytes($hashText)
$req.input_hash = [BitConverter]::ToString(
  $sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
$sha.Dispose()

$body = $req | ConvertTo-Json -Depth 30
$headers = @{
  'X-Request-Id' = $req.request_id
  'Authorization' = 'Bearer local-demo-key'
}
$reply = Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8000/v2/trainee/answer' `
  -Method Post -Headers $headers `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$reply | ConvertTo-Json -Depth 30
```

Fixture có câu hỏi và một đoạn Learn mẫu, đủ để thử đường đi dữ liệu. Khi đổi câu hỏi hoặc nguồn, tạo request_id mới và chạy lại phần tạo hash. Gửi lại cùng ID và hash có thể trả kết quả đã lưu, không gọi mô hình mới.

| Trạng thái | Cách đọc |
| --- | --- |
| Answered | Có câu trả lời và citation hợp lệ theo kiểm tra của pipeline. |
| InsufficientEvidence | Thiếu bằng chứng, ngân sách không đủ hoặc output không hợp lệ. |
| RejectedBySafetyGate | Câu hỏi hoặc nội dung trả về khớp quy tắc bị chặn. |
| NeedsUserEdit | Bản nháp kịch bản cần người dùng xem và sửa. |

Đọc recommendation trước, sau đó xem citations, limitations và usage. Sau timeout, tra GET /v2/requests/{request_id} với Bearer tương ứng: 200 là có kết quả, 202 là đang xử lý, 404 là không tìm thấy request.

<a id="phan-7"></a>

## Tạo bản nháp kịch bản

Endpoint POST /v2/organization/scenario-draft dành cho tổ chức. Khác hỏi đáp thông thường, request bắt buộc có BIM đã được backend ghim theo revision. Không thể chỉ gửi câu “tạo một đám cháy” mà mong nhận được cấu hình đáng tin cậy cho tòa nhà.

### Dữ liệu cần chuẩn bị

| Thành phần | Nội dung cần có |
| --- | --- |
| sources | Tài liệu hoặc thư viện được phép sử dụng, kèm phiên bản. |
| bim.revisionId | Revision cụ thể của mô hình công trình. |
| bim.geometry | artifactId, sha256Hash và schemaVersion của hình học. |
| bim.floors và anchors | Tầng và các phần tử BIM làm điểm tham chiếu. |
| bim.runtime | Phiên bản runtime, capabilities và capabilityContracts. |
| bim.qualityFlags | Cảnh báo chất lượng để AI thể hiện giới hạn. |
| limits | Giới hạn theo tokens hoặc requests do BE cấp. |

### Cách chạy thử

Dùng tests/fixtures/v2/organization-scenario-draft.json thay cho fixture trainee ở phần gửi câu hỏi, tăng max_units nếu cần, tạo ID mới và đổi URI sang /v2/organization/scenario-draft. Fixture giúp thử hợp đồng API; dữ liệu thật phải lấy từ BE để artifact, revision và capability khớp hệ thống.

### Kết quả được tạo ra

Pipeline tìm nguồn kiến thức, thêm bản tóm tắt BIM rồi yêu cầu mô hình sinh state. Các loại đối tượng hỗ trợ gồm Spawn, Hazard, Goal, Npc, BlockedElement và Equipment. Code kiểm tra tầng, anchor, capability, ID trùng, tọa độ hữu hạn và JSON schema; đối tượng lỗi bị loại và ghi lý do vào limitations.

Kết quả hợp lệ có status NeedsUserEdit, scenario_draft.state, notes, citations, bim_anchors và rule_results. AI trả dữ liệu để editor hoặc backend xử lý tiếp; API này không tự lưu bản nháp vào nghiệp vụ, phê duyệt hay publish.

### Giới hạn cần hiểu trước khi sử dụng

Bản tóm tắt BIM gửi cho mô hình không chứa toàn bộ mesh hoặc tọa độ chi tiết của anchor. Kiểm tra hiện tại không chứng minh vật thể nằm đúng trong phòng, không xuyên tường hoặc có đường đi NavMesh. Người dùng phải xem lại trong editor và dùng các bước validation của BE/Unity.

Các rule_results chủ yếu phản ánh quality flags hoặc quan sát cấu trúc BIM, không phải bộ máy thẩm định quy chuẩn PCCC. Bản nháp vẫn cần nguồn trích dẫn và anchor hợp lệ; thiếu chúng có thể trả InsufficientEvidence.

<a id="phan-8"></a>

## Xử lý IFC và cách chạy worker

IFC worker là tiến trình riêng. Backend gửi delivery, worker claim job và giữ lease, tải IFC, kiểm tra hash, trích xuất rồi đăng ký kết quả qua các gate nội bộ. Nhận diện IFC dùng thuộc tính và quy tắc từ khóa; bước này không cần LLM API key.

```text
BE dispatcher → POST /deliveries → claim job
→ tải IFC và kiểm tra SHA-256
→ đọc tầng phòng phần tử và phân loại
→ trích xuất mesh và chuẩn hóa tọa độ
→ preview.glb và building_metadata.json
→ upload storage → đăng ký output → complete
```

Hiện worker xuất một preview.glb có các node nhóm theo tầng, tên node theo IFC GlobalId. Metadata chứa tầng, phòng, bounding box khi có hình học, portals, interactables và vật liệu. Blender tùy chọn thêm UV lightmap; Unity worker riêng xử lý package runtime.

### Chạy test worker độc lập

```powershell
cd 'DUONG_DAN_TOI_AI\ifc-worker'
# Chỉ tạo và cài khi chưa có môi trường tương ứng
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

### Chạy service cần backend thật hoặc môi trường giả lập gate

Tạo .env trong ifc-worker với BE_BASE_URL và WORKER_KEY. Key tối thiểu 32 ký tự và phải khớp MachineKey bên BE. Với development có thể dùng local storage; production bắt buộc có S3_BUCKET, cấu hình vùng và quyền đọc ghi storage.

```powershell
.\.venv\Scripts\python.exe -m worker.config
.\.venv\Scripts\python.exe -m uvicorn worker.server:app `
  --host 127.0.0.1 --port 8080
```

Cấu hình BE ProcessingWorker__WorkerUrl trỏ tới /deliveries, MachineKey khớp WORKER_KEY và AllowedToolchains chứa chuỗi in từ worker.config. Nếu đặt BLENDER_PATH, chạy lại lệnh để cập nhật chuỗi toolchain. Chỉ gọi /health không chứng minh một job IFC đã chạy thành công.

Mặc định chạy một job đồng thời; hết slot trả WORKER_BUSY để dispatcher gửi lại. Delivery cần eventKey, payloadHash, job_id và input_hash hợp lệ; một file IFC đơn lẻ chưa đủ để gọi /deliveries thành công.

<a id="phan-9"></a>

## Lỗi thường gặp và giới hạn

| Biểu hiện | Kiểm tra hoặc xử lý |
| --- | --- |
| 401 AI_UNAUTHORIZED | Bearer có khớp AI_API_KEY không. Đây không phải key OpenAI/Gemini. |
| 422 AI_REQUEST_ID_MISMATCH | X-Request-Id phải trùng request_id trong JSON. |
| 422 AI_ROUTE_MISMATCH | Audience, operation và response_type phải khớp endpoint. |
| AI_REVISION_NOT_PINNED | ScenarioDraft cần bim chứa revision và geometry đã ghim. |
| 409 AI_REQUEST_CONFLICT | ID cũ bị gửi với input_hash khác. Tạo request mới nếu đổi đầu vào. |
| 409 AI_REQUEST_IN_PROGRESS | Request đang xử lý; tra GET theo request_id. |
| 503 AI_TEMPORARILY_UNAVAILABLE | Kiểm tra provider key, môi trường, request DB và log server. |
| AI_OUTCOME_UNKNOWN | Có thể đã gọi mô hình; tra trạng thái trước khi tạo yêu cầu mới. |
| AI_SOURCE_UNAVAILABLE | Kiểm tra HTTPS, hash, giới hạn kích thước, timeout và loại tài liệu. |
| InsufficientEvidence | Kiểm tra sources, citations, nội dung nguồn và limits.max_units. |
| 404 ở /chat hoặc /documents | Các route legacy mặc định tắt; dùng /v2 cho luồng hiện tại. |
| WORKER_BUSY hoặc lỗi gate | Kiểm tra slot, MachineKey, toolchain và trạng thái job bên BE. |

### Điều chưa được các kiểm tra hiện tại bảo đảm

Safety gate dựa trên cụm từ nên có thể bỏ sót cách diễn đạt khác. Citation tồn tại trong nguồn truy xuất chưa đủ chứng minh mọi nhận định của câu trả lời đều chính xác. Confidence là quy tắc gán nhãn trong code, không phải xác suất đã được hiệu chuẩn.

Truy vấn index lọc theo source ID và embedding model; quyền người dùng phụ thuộc backend chọn nguồn đúng. Cần kiểm thử riêng tình huống thu hồi quyền, đổi phiên bản và nhiều request đồng thời, thay vì xem danh sách pin là bằng chứng đã hoàn tất mọi yêu cầu bảo mật.

Usage hiện ghi nhận thông tin gọi sinh câu trả lời; embed trả vector mà không báo usage tương ứng qua cùng cơ chế. Khi đối chiếu chi phí nhà cung cấp cần tính cả embedding và các lần phục hồi/retry, không chỉ response.usage.

<a id="phan-10"></a>

## Kiểm thử tích hợp và tài liệu tham chiếu

### Lộ trình kiểm thử đề xuất

1. Chạy pytest và eval fake để kiểm tra pipeline cơ bản. Ghi rõ số ca pass, fail, skip và failures trong báo cáo eval.

2. Chạy eval với OpenAI hoặc Gemini, sau đó thử API hỏi đáp bằng nguồn inline. Kiểm tra chất lượng tiếng Việt, trích dẫn, thời gian và usage.

3. Dùng PostgreSQL có pgvector trong database test riêng. Đặt FIRE3D_AI_TEST_PG_DSN rồi chạy test. Fixture có tạo schema và dữ liệu kiểm thử nên không trỏ DSN này vào database production.

4. Ghép backend thật: kiểm tra authorization, nguồn được cấp quyền, request ID/hash, quota, timeout, tra cứu kết quả và recovery. ENVIRONMENT=production yêu cầu khóa API nội bộ, knowledge DB và request store PostgreSQL.

5. Chạy IFC qua dispatcher/gate/storage thật, xem GLB và metadata trong client. Kiểm tra liên kết GlobalId, tọa độ, tầng, cửa và khả năng nhập vào Unity trước khi đánh giá luồng hoàn chỉnh.

### Các giới hạn triển khai đã được ghi nhận

Hướng dẫn deploy trong repo ghi checklist E2E với BE thật chưa hoàn tất. README worker ghi khác biệt với Unity Tools/GeometryWorker về mã tầng, rotationY hoặc cao độ cửa và coordinateTransform trong building metadata. Đây là các hạng mục tích hợp cần đối chiếu trước khi dùng production.

### Các file tham chiếu chính

Các liên kết dưới đây trỏ tới file trong repo để đối chiếu khi code đổi phiên bản.

| Nội dung | File nguồn |
| --- | --- |
| Khởi tạo và cấu hình | [main.py](../rag-api/app/main.py), [config.py](../rag-api/app/core/config.py) |
| API và schema | [router.py](../rag-api/app/v2/router.py), [schemas.py](../rag-api/app/v2/schemas.py), [auth.py](../rag-api/app/v2/auth.py) |
| Request và recovery | [service.py](../rag-api/app/requests/service.py), [store.py](../rag-api/app/requests/store.py) |
| Chuẩn bị và tìm nguồn | [resolver.py](../rag-api/app/sources/resolver.py), [pgvector.py](../rag-api/app/index/pgvector.py) |
| Trả lời và tạo kịch bản | [pipeline.py](../rag-api/app/answering/pipeline.py), [scenario.py](../rag-api/app/answering/scenario.py), [prompts.py](../rag-api/app/answering/prompts.py) |
| Test và eval | [README RAG](../rag-api/README.md), [README eval](../rag-api/evals/README.md), [run_eval.py](../rag-api/evals/run_eval.py) |
| Worker và đầu ra IFC | [README worker](../ifc-worker/README.md), [process.py](../ifc-worker/worker/pipeline/process.py) |
| Triển khai và CI | [Triển khai](deploy-azure.md), [CI](../.github/workflows/ci.yml) |

Mốc tài liệu: main tại 4930fa8, ngày 19 tháng 10 năm 2026. Khi chuyển nhánh hoặc cập nhật code, kiểm tra lại README, Settings và schema trước khi dùng các ví dụ.
