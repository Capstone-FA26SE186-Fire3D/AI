from io import BytesIO
from pypdf import PdfReader

def extract_text(filename: str, content: bytes) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"txt", "md"}: text = content.decode("utf-8")
    elif suffix == "pdf": text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    else: raise ValueError("Unsupported document type. Use .txt, .md, or .pdf.")
    if not text.strip(): raise ValueError("Document has no extractable text.")
    return text
