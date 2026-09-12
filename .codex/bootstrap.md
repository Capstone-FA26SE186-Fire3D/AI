# Khởi tạo Codex sau clone/pull

## Cách kích hoạt

AGENTS.md yêu cầu kiểm tra phần thiếu khi bắt đầu task trong repo. Đây là hướng dẫn cho Codex, không phải Git hook: git pull không tự chạy AI hoặc tạo ghi chú.

Lần đầu, mở một repo code đã có bộ hướng dẫn bằng Codex và yêu cầu: "Đọc AGENTS.md và .codex/bootstrap.md, khởi tạo các file Codex còn thiếu; giữ nguyên file đã có, gồm bộ ở workspace cha nếu đúng cấu trúc Fire3D."

Nếu mở thư mục tổng chưa có AGENTS.md, yêu cầu đọc trực tiếp `AI/AGENTS.md` (hoặc BE/FE/Mobile đã có bộ này) trước. Khi đã tạo AGENTS.md gốc, các phiên sau có điểm vào ở workspace.

## Nguyên tắc an toàn

- Xác định gốc repo thật bằng Git, không suy ra từ cwd hoặc đường dẫn hardcode của người khác. Không sửa cấu hình global, không init Git, không clone repo khác.
- Chỉ tạo từng file chưa có. Giữ nguyên nội dung/timestamp file đã tồn tại; không reset handoff, copy nhật ký người khác hoặc đồng bộ template đè ghi chú. Nếu đường dẫn bị chiếm bởi file/thư mục sai loại, báo vướng mắc, không xóa/thay thế.
- Kiểm tra đường dẫn tuyệt đối và symlink/junction trước khi ghi; không đi theo liên kết ra ngoài phạm vi cho phép. Nếu workspace cha nằm ngoài quyền ghi, yêu cầu mở đúng workspace hoặc cấp quyền, không vượt sandbox.
- Plan Mode/read-only: chỉ liệt kê phần thiếu và bàn giao trong chat, không ghi file. Bootstrap không cấp quyền commit, push, PR, merge hoặc chạy build/test.
- Nếu nhiều phiên cùng khởi tạo, kiểm tra lại sự tồn tại ngay trước khi tạo; nếu file vừa được tạo bởi phiên khác thì giữ nguyên.

## Phần local của repo hiện tại

1. Đọc [context](context.md), [workflow](workflow.md) và [skills inventory](skills-inventory.md) nếu có. Kiểm tra AGENTS.md, context/workflow/lessons và SKILL.md dùng chung có trong checkout; nếu thiếu tracked guidance, báo checkout chưa đầy đủ và kiểm tra nhánh/remote theo workflow, không tự bịa hoặc khôi phục thay đổi người khác.
2. Trước khi tạo ghi chú, dùng `git check-ignore` xác nhận `.codex/local/` được ignore, đồng thời `git ls-files -- .codex/local/` không có file đã track. Nếu không đạt, báo cấu hình chưa đúng; không tự ghi thông tin phiên vào đường dẫn có thể lên Git.
3. Tạo `.codex/local/handoff.md` nếu thiếu: tên repo, thời điểm thực tế, "khởi tạo trên máy này, chưa có lịch sử bàn giao", branch/HEAD quan sát được, task hiện tại nếu biết, trạng thái kiểm tra "chưa chạy" và bước tiếp theo. Không coi HEAD local là remote mới nhất.
4. Tạo `.codex/local/lessons.md` nếu thiếu: tiêu đề và "chưa có bài học được ghi nhận trên máy này"; không dựng lại lỗi/test từ máy người khác.
5. Các lần sau chỉ bổ sung file thiếu; cập nhật nội dung handoff đang có theo workflow của task, không dùng bootstrap để ghi đè.

## Nhận diện workspace cha

Chỉ xem thư mục cha trực tiếp của repo hiện tại là workspace Fire3D khi tất cả điều kiện sau đúng:

- Có đủ năm thư mục con AI, BE, Docs, FE, Mobile; từng thư mục là Git root độc lập (đối chiếu `git rev-parse --show-toplevel` với đường dẫn đã resolve).
- Origin từng repo trỏ tới GitHub tổ chức `Capstone-FA26SE186-Fire3D` và tên repo tương ứng; chấp nhận HTTPS/SSH và hậu tố .git. Nếu remote bị đổi tên/fork hoặc cấu trúc khác, không đoán workspace: chỉ làm local của repo hiện tại, giải thích phần workspace bị bỏ qua.
- Thư mục cha không nằm trong Git repo khác, không phải gốc ổ đĩa hay thư mục home; đường dẫn đích thuộc đúng workspace và được phép ghi.
- Không ghi gì trong Docs hoặc local của repo anh em; mỗi repo tự khởi tạo phần riêng khi Codex làm việc ở đó.

Nếu thiếu điều kiện (ví dụ chỉ clone BE), vẫn hoàn thành local của repo hiện tại; không tự tạo bốn repo còn thiếu. Khi người dùng bổ sung đủ repo, kiểm tra lại ở task sau.

## Tạo bộ ở workspace cha — chỉ các file thiếu

| Đường dẫn từ workspace | Nội dung khi khởi tạo |
| --- | --- |
| `AGENTS.md` | Đọc .codex/context.md, .codex/workflow.md, local/handoff.md nếu có; trước thao tác repo con đọc AGENTS.md của repo đó; Docs đọc README, không tạo bộ Codex trong Docs; gốc không phải Git repo; local-first, không ghi trong Plan Mode. |
| `.codex/context.md` | Bản đồ năm repo với đường dẫn tương đối; dẫn đến context từng repo có sẵn và Docs/README.md. Nêu context chi tiết ở repo con, không copy toàn bộ thiết kế hoặc coi implementation là hoàn thành. Nếu repo anh em chưa có hướng dẫn, ghi rõ chưa có, không tạo link hỏng. |
| `.codex/workflow.md` | Dùng nội dung workflow của repo đang bootstrap làm điểm xuất phát (liên kết context.md/lessons.md vẫn là nội bộ .codex). Bổ sung: áp dụng Git riêng từng repo, task liên repo cần theo dõi phụ thuộc, ghi chú phiên Docs nằm tại local workspace. Không tạo root Git hoặc mặc định được phép phát hành. |
| `.codex/lessons.md` | Bài học liên repo dùng chung có chọn lọc; chưa có bài học trên workspace này. Không copy local lessons từ repo khác. |
| `.codex/.gitignore` | Một dòng `/local/`; phòng trường hợp sau này được đặt trong repo, không phải yêu cầu init Git. |
| `.codex/local/handoff.md` | Thời điểm tạo, workspace đã nhận diện, task hiện tại nếu biết, "chưa có lịch sử bàn giao", kiểm tra thực tế và bước tiếp theo; không chép handoff cá nhân từ repo. |
| `.codex/local/lessons.md` | Tiêu đề và trạng thái chưa ghi nhận bài học trên workspace này. |

Bộ cha chỉ lưu trên máy đồng đội, không push. File bootstrap này được track trong mỗi repo code để vẫn có hướng dẫn tái tạo khi bộ cha không tồn tại. Nếu bản hướng dẫn giữa các repo không khớp, không dùng thứ tự chạy để ghi đè; báo khác biệt và giữ file cha hiện có.

## Xác nhận sau khởi tạo

- Đối chiếu danh sách file đã tạo/đã có/bị bỏ qua và lý do; báo rõ nếu không thể tạo phần workspace.
- Xác minh các liên kết tạo mới trỏ tới file thật; local notes của repo được ignore và không track.
- Kiểm tra Git: bootstrap chỉ tạo local notes, không thêm thay đổi tracked, không stage gì. Không chạy build/test ứng dụng.
- Khi tất cả file đã có, không ghi gì: khởi tạo lặp lại phải giữ nguyên ghi chú người dùng.
