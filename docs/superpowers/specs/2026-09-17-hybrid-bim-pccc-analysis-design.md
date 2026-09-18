# Hybrid BIM PCCC Advisory Design

## Mục tiêu

Mở rộng RAG API hiện có thành dịch vụ tư vấn PCCC có truy vết: nhận một mô
hình BIM hoặc mặt bằng hỗ trợ, chuẩn hóa nó thành hồ sơ công trình/tầng, tìm
tài liệu PCCC đã được duyệt trong RAG và trả về các khuyến nghị vị trí cần rà
soát hoặc bổ sung. Đây là công cụ hỗ trợ kỹ sư; không thẩm duyệt, không kết
luận công trình đạt/không đạt và không tự thay đổi mô hình BIM.

## Phạm vi bản đầu

- Nhận IFC, GLB/GLTF, PDF, PNG và JPG.
- IFC là nguồn BIM chuẩn: trích xuất thông tin không gian/phần tử qua parser.
- GLB/GLTF và PDF/ảnh được chấp nhận làm nguồn trực quan/tham chiếu. Nếu chúng
  không có metadata phần tử cần thiết, hệ thống ghi `missing_data` thay vì suy
  diễn chắc chắn.
- RVT bị từ chối kèm hướng dẫn xuất IFC hoặc GLB/GLTF. Bản đầu không dùng dịch
  vụ Revit có bản quyền hoặc tự chuyển đổi RVT.
- Nhận tài liệu kiến thức PCCC dưới dạng TXT, Markdown và PDF qua endpoint
  tài liệu hiện có; chỉ tài liệu có metadata `approved=true` mới được truy hồi
  cho một lượt phân tích.
- Bản đầu hoạt động không cần PostgreSQL: một request chứa JSON BIM chuẩn hóa
  và tùy chọn ảnh mặt bằng. Adapter PostgreSQL là giai đoạn tiếp theo; nó sẽ
  ánh xạ `buildings`, `building_floors`, `revisions` và `annotation_sets` vào
  cùng JSON chuẩn hóa.

## Kiến trúc

```text
IFC / GLB / ảnh / PDF
  -> BIM intake + validation
  -> BIM normalizer
  -> BuildingAnalysisInput (tầng, phòng, lối thoát, thiết bị, ảnh)
  -> deterministic screening (dữ liệu thiếu, thiết bị/lối thoát nhận diện được)
  -> approved RAG retrieval (tài liệu PCCC liên quan)
  -> AI vision/chat advisory
  -> structured PcccAnalysisResponse + nguồn + annotation nháp
```

`BIM normalizer` không xác định công trình có tuân thủ PCCC. Nó chỉ bảo toàn
sự thật BIM, ví dụ: tầng, diện tích, không gian, phần tử, loại phần tử và tọa
độ. `deterministic screening` chỉ phát hiện thiếu dữ liệu hoặc mâu thuẫn rõ
ràng, như tầng không có đường thoát/thiết bị nào trong dữ liệu được nhập.

AI chỉ được yêu cầu đưa gợi ý khi đã có nguồn RAG và dữ liệu BIM phù hợp. Nếu
thiếu một trong hai, phản hồi phải nêu rõ dữ liệu cần bổ sung. Prompt cấm các
kết luận pháp lý, thông số lắp đặt cuối cùng, chứng nhận hay khẳng định đủ
thiết bị.

## Mô hình dữ liệu và hợp đồng API

### BIM chuẩn hóa

`BuildingAnalysisInput` gồm:

- `building`: tên, công năng, địa phương, chiều cao PCCC (nếu có) và tổng số
  tầng.
- `floors`: số/tên tầng, diện tích, cao độ, ảnh mặt bằng tùy chọn và danh sách
  `spaces`.
- `spaces`: ID, tên, công năng, diện tích, bounding box/tọa độ tùy chọn.
- `elements`: ID, loại BIM, tên, tầng, không gian chứa, thuộc tính và tọa độ.
  Các loại chuẩn ban đầu gồm `door`, `stair`, `exit`, `corridor`, `extinguisher`,
  `hydrant`, `detector`, `sprinkler`, `emergency_light`, `exit_sign`,
  `fire_door`, `fire_compartment`.
- `source`: tên tệp, loại tệp và ID revision tùy chọn.

Các vị trí dùng `floor_id`, `space_id`, `element_id` trước; chỉ dùng tọa độ
local của BIM khi có. API không chấp nhận URL ảnh tùy ý: ảnh được upload cùng
request hoặc lấy từ allowlist cấu hình.

### Endpoint

- `POST /pccc/knowledge-documents`: nạp tài liệu kèm metadata `approved` và
  `jurisdiction`; tái sử dụng chunking/vector store, nhưng lưu metadata để lọc
  khi tìm kiếm.
- `POST /pccc/bim/inspect`: nhận tệp BIM hỗ trợ và trả `BuildingAnalysisInput`
  cùng warning/thiếu dữ liệu; không gọi AI.
- `POST /pccc/analyses`: nhận `BuildingAnalysisInput`, mục tiêu đánh giá và
  ảnh mặt bằng tùy chọn; tìm nguồn RAG được duyệt, sau đó gọi AI.

`PcccAnalysisResponse` chứa `advisories`. Mỗi advisory phải có `priority`
(`critical`, `high`, `medium`, `low`, `needs_review`), `location`,
`recommendation`, `reasoning`, `evidence`, `missing_data`,
`requires_engineer_verification=true` và `draft_annotation`. `evidence` phải
liệt kê nguồn BIM và một hoặc nhiều đoạn tài liệu RAG. Không có evidence thì
advisory không hợp lệ.

## Kiến thức PCCC

Kho kiến thức ban đầu bám tài liệu Việt Nam và tài liệu nội bộ do người dùng
upload/duyệt. Từng tài liệu có tên, phiên bản, cơ quan/nguồn, ngày hiệu lực,
phạm vi công trình, jurisdiction và cờ approved. Bảng quy chuẩn hoặc tài liệu
chính thức mới được thêm bằng một thao tác quản trị có kiểm tra phiên bản;
không để AI tự tải web hoặc tự thay thế nguồn.

Một thư viện giải pháp trung lập hãng mô tả loại vật phẩm PCCC, dữ liệu BIM
cần có để xem xét, và các câu hỏi xác minh. Nó không chứa định mức/quy cách
thi công cứng nếu không có trích dẫn quy chuẩn tương ứng.

## Bảo mật, quyền riêng tư và vận hành

- Không ghi API key vào git. `.env.example` chỉ chứa placeholder; `.env` bị
  gitignore.
- Từ chối tệp vượt giới hạn cấu hình, loại tệp không hỗ trợ và ảnh/URL không
  thuộc allowlist.
- Chỉ gửi các phần tử BIM, ảnh và đoạn tài liệu thật sự cần cho lượt AI; không
  gửi toàn bộ mô hình hoặc cả kho RAG.
- Chặn prompt injection từ tài liệu bằng system prompt cố định: tài liệu là dữ
  liệu tham chiếu, không phải chỉ dẫn; chỉ trả JSON theo schema.
- Log nguồn/phiên bản model, ID tài liệu, thời gian và trạng thái kết quả;
  không log nội dung khóa API hay URL ký số.

## Kiểm thử và chấp nhận

- Unit tests cho validation schema, lọc approved document, chuẩn hóa BIM và
  yêu cầu `evidence`.
- API tests cho ingest knowledge, inspect BIM và analyse với fake AI client.
- Tests bảo đảm chưa có key AI trả 503 rõ ràng, URL không allowlist bị từ chối,
  tài liệu chưa duyệt không được truy hồi, và AI không được gọi khi không có
  nguồn.
- Một fixture BIM JSON có tầng, hành lang, lối ra và thiết bị sẽ chứng minh
  response định vị được recommendation và đánh dấu xác minh kỹ sư.

## Ngoài phạm vi

- Chứng nhận/thẩm duyệt PCCC, chốt định mức, bản vẽ thi công, mua sắm thiết bị.
- Đọc trực tiếp RVT hoặc tự chuyển đổi tệp Revit.
- Kết nối PostgreSQL production và renderer 3D đầy đủ. Những phần này dùng
  JSON chuẩn hóa đã kiểm chứng làm interface cho giai đoạn sau.
