# AI — bài học dùng chung

Chỉ lưu kiến thức đã xác minh và cần cho team. Nhật ký lỗi, thử nghiệm và bàn giao từng phiên nằm trong .codex/local/ và không được track.

Chưa nâng bài học phiên nào vào file này. Khi cần bổ sung trong PR liên quan, ghi ngắn: tình huống → nguyên nhân/bằng chứng → cách khắc phục → cách kiểm tra và phạm vi áp dụng. Gộp trùng, không viết lại toàn bộ file.

## 2026-09-13 — cài project skills

- `npx skills add` tạo `.agents/skills/` và `skills-lock.json`; giữ lockfile để team khôi phục đúng nguồn/hash.
- Test AI chưa chạy được vì Python hiện tại thiếu `fastapi`, `chromadb` và `pytest`; không gọi đây là test đạt. Cần chuẩn bị môi trường theo `requirements.txt` trong một task riêng.
