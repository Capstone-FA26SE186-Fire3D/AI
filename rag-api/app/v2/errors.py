"""Adapter errors for the BE->AI contract v2."""


class AdapterRefusal(Exception):
    """Refusal with an HTTP status and a stable code; body is {"code","message"}."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


def refuse(code: str, message: str, status: int = 422) -> AdapterRefusal:
    """Build (do NOT raise) an AdapterRefusal; the caller must `raise refuse(...)`."""
    return AdapterRefusal(status, code, message)
