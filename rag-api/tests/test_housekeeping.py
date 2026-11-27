"""Housekeeping entrypoint uses a configured store and never invents a DSN."""

from app.index import housekeeping


def test_housekeeping_requires_database_configuration(monkeypatch, capsys):
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL", raising=False)
    assert housekeeping.main([]) == 2
    assert "KNOWLEDGE_DATABASE_URL is not set" in capsys.readouterr().err


def test_housekeeping_reports_pruned_count_from_store(monkeypatch, capsys):
    seen = []

    class Store:
        def __init__(self, dsn):
            seen.append(dsn)

        def prune_ineligible(self):
            return 7

    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "postgresql://test/throwaway")
    monkeypatch.setattr(housekeeping, "PgVectorIndex", Store)
    assert housekeeping.main([]) == 0
    assert seen == ["postgresql://test/throwaway"]
    assert capsys.readouterr().out == "pruned 7 chunks\n"
