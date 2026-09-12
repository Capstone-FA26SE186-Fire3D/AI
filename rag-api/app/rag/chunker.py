def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())
    if not text: return []
    if overlap >= chunk_size: raise ValueError("overlap must be smaller than chunk_size")
    return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size - overlap)]
