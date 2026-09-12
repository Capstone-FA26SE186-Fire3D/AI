# RAG API

Copy `.env.example` to `.env`, add `OPENAI_API_KEY`, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. Upload `.txt`, `.md` or `.pdf` to `POST /documents`, then ask with `POST /chat`.
