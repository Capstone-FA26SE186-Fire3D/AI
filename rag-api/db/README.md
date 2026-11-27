# Cơ sở dữ liệu AI service

Migration `migrations/001_ai_service.sql` tạo schema `ai_service`, bảng `requests`
(dedupe theo `request_id`) và role `fet3d_ai_service` (NOLOGIN).

## Ai chạy migration

Admin của Supabase/Postgres (role có quyền tạo schema và role) chạy một lần:

```
psql "$ADMIN_DATABASE_URL" -f db/migrations/001_ai_service.sql
```

Service AI không tự tạo bảng trên Postgres.
Migration này không cần extension pgvector (chỉ `knowledge_chunks` của BE cần). Trên Supabase, pgvector nằm trong
schema `extensions`; đặt `ALTER ROLE <ai_login> SET search_path = public, extensions;` cho login của AI. Retention của
`ai_service.requests` (xoá row `Completed` quá 90 ngày): xem `../../docs/deploy-aws.md` (mục 6; chưa có lịch chạy trên EC2).

## Cấp quyền cho login của AI

Login mà service AI dùng phải được gán cả hai role (`fet3d_ai_indexer` do migration của
pipeline RAG tạo):

```
GRANT fet3d_ai_service, fet3d_ai_indexer TO <ai_login>;
```

## Chuỗi kết nối

```
DATABASE_URL=postgresql://<ai_login>:<mat_khau>@<host>:5432/postgres
```

Code tự chuyển sang driver `postgresql+psycopg` và dùng schema `ai_service`.
Dùng `sqlite:///duong/dan.db` cho dev/test (bảng tự tạo, không có schema).

## Cột vector và chỉ mục (hiện trạng 15/11/2026)

Cột `embedding` để kiểu `vector` không khai số chiều; số chiều lưu theo từng dòng và mỗi lần tìm chỉ lấy các dòng có đúng `embedding_model` đang dùng. Tìm kiếm quét chính xác (cosine) trong các nguồn đã được ghim cho câu hỏi, không dùng chỉ mục gần đúng (HNSW/IVFFlat). Lý do giữ như vậy: kho tri thức chỉ vài nghìn đoạn nên quét chính xác đủ nhanh, và khai cứng `vector(384)` kèm chỉ mục sẽ chặn việc đổi mô hình embedding nếu không có migration ở BE. `contracts/KnowledgeChunks.sql` lấy từ BE, không sửa tay ở đây.
