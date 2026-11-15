"""Adapter errors for the BE->AI contract v2."""


class AdapterRefusal(Exception):
    """Refusal with an HTTP status and a stable code; body is {"code","message"}, plus "document_id" when one
    knowledge source caused it (the BE shows which source to fix)."""

    def __init__(self, status_code: int, code: str, message: str, document_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.document_id = document_id


def refuse(code: str, message: str, status: int = 422, document_id: str | None = None) -> AdapterRefusal:
    """Build (do NOT raise) an AdapterRefusal; the caller must `raise refuse(...)`."""
    return AdapterRefusal(status, code, message, document_id)
