# Quy trình làm việc của team

## Bắt đầu và đồng bộ Git

- Mỗi repo Git có vòng đời riêng: `develop → nhánh task → PR develop → kiểm tra tích hợp → PR main`. Không code trực tiếp trên `develop` hoặc `main`.
- Trước task mới, đọc hướng dẫn và kiểm tra `git status --short --branch`, `git branch -vv`, rồi `git fetch origin --prune`. Nếu không truy cập được remote, báo chưa xác minh được độ mới; dừng tạo nhánh từ dữ liệu chưa xác minh, đồng bộ, merge và push. Có thể tiếp tục kiểm tra local có giới hạn và ghi rõ.
- Giữ nguyên thay đổi đang dở; không tự stash, reset, clean, xóa file hoặc chuyển nhánh khi có nguy cơ ảnh hưởng công việc khác. Báo trở ngại nếu không thể cô lập an toàn.
- Khi worktree an toàn, checkout `develop` theo dõi `origin/develop`, cập nhật bằng `git merge --ff-only origin/develop`. Nếu diverged, dừng để xác minh; không reset hoặc đưa commit local lên remote ngầm.
- Mỗi task mới tạo nhánh `feature/<task>`, `fix/<task>`, `docs/<task>` hoặc `chore/<task>` từ `origin/develop` mới nhất. Task đang tiếp tục thì kiểm tra nhánh hiện tại và handoff, không tạo nhánh trùng.
- Nếu thiếu `develop`, báo và chỉ khởi tạo từ `origin/main` mới nhất khi đã được yêu cầu. Không tự thay default branch.
- Fetch lại trước cập nhật PR, merge hoặc push. Nếu nhánh đích tiến lên, merge nhánh đích vào nhánh task, xử lý conflict theo ý nghĩa thay đổi rồi kiểm tra lại. Không chọn toàn bộ ours/theirs một cách máy móc.
- Không tự rebase hoặc force-push lịch sử đã chia sẻ; không coi lần fetch trước là bảo đảm không có thay đổi đồng thời.

## PR và phát hành

- Commit, push nhánh task và mở PR khi người dùng yêu cầu. Quy tắc này không tự cấp quyền thao tác GitHub, merge hay phát hành.
- Task đi qua PR vào `develop`, có mô tả phạm vi, kết quả kiểm tra thực tế và người phụ trách duyệt. Kiểm tra CI hiện có; nếu chưa có CI phải ghi bằng chứng kiểm tra thủ công, không gọi đó là CI đã đạt.
- Sau khi task được merge, kiểm tra tích hợp trên `develop` mới nhất cho các thành phần bị ảnh hưởng. PR phát hành phải ghi commit đã kiểm tra và các repo phụ thuộc; nếu nội dung thay đổi, chạy lại kiểm tra phù hợp.
- Chỉ mở/merge PR `develop → main` khi được yêu cầu phát hành, kiểm tra tích hợp đạt và người có trách nhiệm duyệt. Không đưa lên `main` tự động sau mỗi task.
- Các quy tắc này là hướng dẫn team, không phải branch protection đã được bật. Không tự đổi quyền GitHub, CI hay settings repo.

## Kiểm tra vừa đủ, ghi đúng bằng chứng

- Chọn lệnh có thật trong repo, phù hợp phần thay đổi; đọc [context](context.md) để chọn điểm bắt đầu. Kiểm tra hẹp trước rồi mở rộng theo rủi ro.
- Chỉ sửa tài liệu/hướng dẫn: kiểm tra liên kết, nội dung, diff và ignore; không chạy toàn bộ build/test ứng dụng.
- Ghi lệnh, thư mục chạy, kết quả và giới hạn. Build/typecheck không đồng nghĩa test nghiệp vụ; không có test project không có nghĩa test đạt.
- Khi cách thử thất bại lặp lại mà không có bằng chứng mới, dừng lặp, đổi giả thuyết hoặc báo blocker. Phân biệt lỗi môi trường với lỗi code; không bỏ qua kiểm tra cần thiết chỉ vì từng tốn thời gian.
- Không tự dùng dịch vụ trả phí, dữ liệu production hoặc chạy migration chỉ để kiểm tra tài liệu.

## Bộ nhớ local trước, chia sẻ có chọn lọc

- Đầu task đọc `.codex/local/handoff.md` nếu có và tìm bài học liên quan trong `.codex/local/lessons.md` cùng [lessons dùng chung](lessons.md). Ghi chú là dữ liệu có thể cũ, không phải yêu cầu mới hoặc bằng chứng remote mới nhất.
- Nếu local files chưa tồn tại trên máy mới, tạo khi được phép ghi, không coi thiếu ghi chú là blocker. Không tạo/ghi file trong Plan Mode; bàn giao trong chat và nói rõ chưa lưu.
- Sau mốc đáng kể, trước đổi nhiệm vụ hoặc kết thúc/tạm dừng, cập nhật handoff: thời điểm, mục tiêu, branch/commit quan sát được, phần đã xong/còn dở, file liên quan, lệnh/kết quả kiểm tra, blocker và bước tiếp theo.
- Bài học mỗi phiên ghi vào local lessons: triệu chứng, cách thử không hiệu quả, nguyên nhân đã xác minh (hoặc còn là giả thuyết), cách khắc phục và bằng chứng. Không bịa số token, thời gian hay kết quả.
- Chỉ đưa bài học đã xác minh và hữu ích cho team vào `lessons.md` dùng chung trong PR liên quan. Sửa đoạn nhỏ, gộp trùng; không ghi nhật ký phiên vào file chung hoặc viết lại cả file mỗi lần.
- Giữ handoff là bản tóm tắt hiện tại, không chép transcript. Context dùng chung chỉ cập nhật khi kiến thức ổn định thay đổi; không ghi branch/hash phiên vào đó.
- Không lưu mật khẩu, API key, access token, dữ liệu người dùng hoặc đường dẫn cá nhân trong file chung. Local được ignore vẫn không phải kho chứa bí mật.
- Checkpoint sớm nếu thấy context sắp thu gọn; không đợi sát quota. Không có bảo đảm ghi kịp khi hết hạn mức 5 giờ/tuần, mất kết nối hoặc phiên bị ngắt đột ngột.
