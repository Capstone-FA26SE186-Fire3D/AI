# Installed project skills — AI

Updated: 2026-09-13

All skills in this file are copied project-local under `.agents/skills/`. The
generated `skills-lock.json` records the source paths and content hashes.

## AI/API skills

- `fastapi-patterns` — `affaan-m/ecc`; FastAPI structure, Pydantic, DI and tests.
- `python-patterns` — `affaan-m/ecc`; Python structure and maintainability.
- `backend-patterns` — `affaan-m/ecc`; backend layering and service boundaries.
- `fastapi-templates` — `wshobson/agents`; FastAPI scaffolding patterns.
- `rag-implementation` — `wshobson/agents`; RAG/vector-search implementation, including Chroma-oriented patterns.

`rag-implementation` là tài liệu tham khảo, không quyết định storage. Kiến trúc production của FET3D dùng Supabase PostgreSQL + `pgvector`; mọi pattern Chroma phải được chuyển nghĩa và review trước khi áp dụng.

## IFC và ranh giới artifact

- `IfcOpenShell`/`IfcConvert` — extraction/normalization của IFC, không phải game runtime.
- Blender chạy script — tối ưu mesh/material/LOD theo quy tắc nhóm; không thay thế Unity build.
- Unity Editor build worker — import asset đã QA, tạo collider/NavMesh/Addressables hoặc package runtime; cần môi trường Editor/configuration riêng.
- RAG service — facts/chunks/embeddings, common-vs-organization scope và hai audience; AI chỉ tạo answer/draft có citation, không mutate scenario hoặc publish.

## Cross-cutting review skills

- `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`,
  `ponytail-gain`, `ponytail-help` — `DietrichGebert/ponytail`.
- Use the narrowest Ponytail skill for the task; these are instructions only.
  No Ponytail plugin manifest or global hook was installed.

## Priority and safety

For AI API work, start with `fastapi-patterns` + `python-patterns`; add
`rag-implementation` for retrieval/indexing changes. Do not claim BIM/PCCC
production behavior from these skills alone. Review every skill's `SKILL.md`
before following scripts and never place secrets in notes.

## Explicitly excluded

- `compose-multiplatform-patterns` (Kotlin Compose; Mobile is Expo/RN).
- Flutter agent plugins and Dart skills (no Flutter/Dart app in this checkout).
