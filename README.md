# Fire3D AI

Code RAG mẫu và hướng dẫn chạy ở [rag-api/README.md](rag-api/README.md).

## Codex cho thành viên team

Sau khi checkout nhánh có bộ hướng dẫn, mở repo bằng Codex và yêu cầu:

> Đọc AGENTS.md và .codex/bootstrap.md, khởi tạo các file Codex còn thiếu; giữ nguyên file đã có, gồm bộ ở workspace cha nếu đúng cấu trúc Fire3D.

- Git pull chỉ tải hướng dẫn, không tự chạy Codex. [Quy trình bootstrap](.codex/bootstrap.md) tạo local notes bị ignore; chỉ dựng bộ workspace cha khi nhận diện đủ AI/BE/Docs/FE/Mobile và được phép ghi.
- Nếu chỉ clone repo này, Codex tạo phần local của repo, không ghi vào thư mục cha. Không ghi trong Plan Mode.
- File cá nhân không được push; quy tắc và kiến thức team nằm trong bộ hướng dẫn được track.

## Kiểm thử, eval và triển khai

- Test: `cd rag-api && python -m pytest -q` (test pgvector tự bỏ qua nếu không đặt `FIRE3D_AI_TEST_PG_DSN` (đặt `FIRE3D_AI_TEST_PG_DOCKER=1` để opt-in chạy PostgreSQL qua Docker)).
- Eval offline: `cd rag-api && python -m evals.run_eval --provider fake --out evals/reports/local` (xem [rag-api/evals/README.md](rag-api/evals/README.md)).
- CI: [.github/workflows/ci.yml](.github/workflows/ci.yml). Triển khai: [docs/deploy-azure.md](docs/deploy-azure.md) (Azure App Service, code deploy).
- Dự án không dùng Docker: không có Dockerfile hay docker-compose, và test/eval không phụ thuộc Docker.
