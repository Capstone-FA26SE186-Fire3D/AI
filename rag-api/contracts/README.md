# Contract vendored từ BE

Nguồn: repo BE, commit `c4975f1` (`origin/main`).

| File ở đây | Nguồn trong BE |
|---|---|
| `scenario-state.schema.json` | `contracts/editor/v1/scenario-state.schema.json` |
| `geometry-metadata.schema.json` | `contracts/editor/v1/geometry-metadata.schema.json` |
| `building-metadata.schema.json` | `contracts/ifc/v1/building-metadata.schema.json` |
| `fixtures/*.valid.json` | `contracts/{editor,ifc}/v1/fixtures/*.valid.json` |
| `KnowledgeChunks.sql` | `Fire3D/Fire3D.Infrastructure/Persistence/Sql/KnowledgeChunks.sql` |

Quy tắc đồng bộ: khi BE đổi bất kỳ file nguồn nào ở trên, sao chép lại nguyên văn (byte-for-byte, UTF-8),
cập nhật commit ở đầu file này và chạy `pytest tests/test_app_factory.py`. Không sửa tay các file trong thư mục này.
