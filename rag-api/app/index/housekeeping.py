"""Drop chunks of sources BE no longer marks eligible: python -m app.index.housekeeping."""
from __future__ import annotations

import os
import sys

from app.index.pgvector import PgVectorIndex


def main(argv: list[str] | None = None) -> int:
    dsn = os.environ.get("KNOWLEDGE_DATABASE_URL")
    if not dsn:
        print("KNOWLEDGE_DATABASE_URL is not set", file=sys.stderr)
        return 2
    removed = PgVectorIndex(dsn).prune_ineligible()
    print(f"pruned {removed} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
