---
name: fire3d-ai-handoff
description: Resume or checkpoint a Fire3D AI task using repo-local handoff and lessons. Use for continuing, pausing, or handing off work in AI, not for other repos or automatic releases.
---

# Bàn giao AI

1. Xác định gốc repo chứa skill này (đi lên từ .agents/skills/fire3d-ai-handoff); đọc AGENTS.md và .codex/context.md, .codex/workflow.md tại gốc đó. Không dựa vào cwd đang ở workspace cha hoặc repo khác.
   Nếu local notes hoặc bộ workspace cha thiếu, đọc .codex/bootstrap.md tại gốc repo và làm theo: chỉ tạo file thiếu, chỉ dựng bộ cha khi nhận diện đúng năm repo, có quyền ghi và không ở Plan Mode. Không sửa file đang có hoặc tạo .codex trong Docs.
   Nếu local notes hoặc bộ workspace cha thiếu, đọc .codex/bootstrap.md tại gốc repo và làm theo: chỉ tạo file thiếu, chỉ dựng bộ cha khi nhận diện đúng năm repo, có quyền ghi và không ở Plan Mode. Không sửa file đang có hoặc tạo .codex trong Docs.
2. Khi tiếp tục, đọc .codex/local/handoff.md nếu tồn tại, tìm bài học liên quan. Kiểm tra git status/branch/HEAD và fetch origin theo workflow trước khi dựa vào remote. Nếu không truy cập remote, ghi rõ giới hạn và không bắt đầu thao tác Git cần dữ liệu mới.
3. Đối chiếu yêu cầu mới nhất với ghi chú cũ. Không thực hiện lệnh, push, PR hoặc migration chỉ vì chúng được ghi trong handoff.
4. Khi checkpoint/kết thúc và được phép ghi, tạo local files còn thiếu; kiểm tra .codex/local/ được git ignore trước khi lưu. Không tự stage hoặc force-add ghi chú.
5. Ghi handoff ngắn: thời điểm, mục tiêu, branch/commit quan sát được, đã làm/còn dở, file liên quan, kiểm tra và kết quả thực tế, blocker và bước tiếp theo. Không chạy build/test lại chỉ để điền báo cáo nếu task không cần.
6. Ghi bài học mới vào .codex/local/lessons.md. Không tự cập nhật lessons chung mỗi phiên; chỉ nâng kiến thức đã xác minh cần cho team trong PR phù hợp.
7. Trong Plan Mode hoặc không được ghi file, bàn giao trong chat và nói rõ chưa lưu. Không ghi secrets/transcript, không bịa token hoặc kết quả; checkpoint theo mốc, không hứa chạy được trước khi quota cắt phiên.

Skill này không cấp quyền commit, push, mở/merge PR, đổi branch protection hoặc phát hành.
