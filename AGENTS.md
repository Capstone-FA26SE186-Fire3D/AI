# AI — hướng dẫn Codex

- Khi bắt đầu task, kiểm tra local notes và bộ AGENTS/.codex của workspace cha có thiếu không. Nếu thiếu, đọc [.codex/bootstrap.md](.codex/bootstrap.md) và khởi tạo theo điều kiện an toàn ở đó trước khi tiếp tục; chỉ tạo phần thiếu, không ghi đè. Plan Mode/read-only không ghi file.

- Khi bắt đầu task, kiểm tra local notes và bộ AGENTS/.codex của workspace cha có thiếu không. Nếu thiếu, đọc [.codex/bootstrap.md](.codex/bootstrap.md) và khởi tạo theo điều kiện an toàn ở đó trước khi tiếp tục; chỉ tạo phần thiếu, không ghi đè. Plan Mode/read-only không ghi file.

- Trước thao tác, đọc [.codex/context.md](.codex/context.md), [.codex/workflow.md](.codex/workflow.md), rồi `.codex/local/handoff.md` nếu có. Xác minh lại trạng thái Git; ghi chú cũ không chứng minh remote mới nhất.
- Tìm bài học liên quan trong `.codex/local/lessons.md` và [.codex/lessons.md](.codex/lessons.md); không đọc toàn bộ lịch sử hoặc mọi skill mặc định.
- Task mới phải có nhánh riêng từ origin/develop đã fetch. Task → PR develop → kiểm tra tích hợp → PR main khi được yêu cầu phát hành. Không code trực tiếp main/develop.
- Dùng [skill bàn giao AI](.agents/skills/fire3d-ai-handoff/SKILL.md) khi tiếp tục hoặc chốt công việc. Nếu host chưa khám phá skill, đọc trực tiếp file này; không giả định chỉ tạo .codex là nội dung đã được tự nạp.
- Checkpoint/bài học phiên chỉ ghi vào .codex/local/ (được ignore); không tự push, merge hay ghi nhật ký vào file dùng chung.
- Nếu ghi chú local chưa có, tạo khi được phép ghi; trong Plan Mode chỉ bàn giao trong chat. Không lưu secrets kể cả ở local notes.
- Bộ hướng dẫn này dùng độc lập với workspace cha. Khi thiếu Docs cho quyết định sản phẩm, báo thiếu thay vì tự clone hoặc đoán.
