"""Static test inventory; a direct import is evidence of targeting, not behavioral coverage."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("rag-api", "ifc-worker")
EXCLUDE = {".venv", ".codex", ".pytest_cache", "__pycache__", "build", "dist"}


def files(directory: Path):
    return sorted(path for path in directory.rglob("*.py") if not set(path.relative_to(directory).parts) & EXCLUDE)


def imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeError):
        return set()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def public_names(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeError):
        return []
    return [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")]


def main():
    rows = []
    for service in SERVICES:
        home = ROOT / service
        tests = files(home / "tests")
        imported = {test: imported_modules(test) for test in tests}
        production = [path for path in files(home) if "tests" not in path.relative_to(home).parts]
        for source in production:
            relative = source.relative_to(home)
            if relative.parts[0] not in ("app", "worker", "evals", "scripts"):
                continue
            module = ".".join(relative.with_suffix("").parts)
            direct = [str(test.relative_to(ROOT)).replace("\\", "/") for test, imports in imported.items()
                      if module in imports or any(name.startswith(module + ".") for name in imports)]
            names = public_names(source)
            category = "legacy/eval/tooling" if relative.parts[0] in ("evals", "scripts") or "legacy" in relative.parts else "production logic/adapter"
            if direct:
                note = "Direct test import; inspect assertions and coverage for actual behavior."
            elif module == "app.v2.router":
                note = "FastAPI routes are exercised through app.main/TestClient; no direct import needed."
            elif module == "app.rag.openai_client":
                note = "Legacy OpenAI helper; current provider tests target app.llm. Add an isolated fake-SDK test if retained."
            elif module == "scripts.blender_optimize":
                note = "Standalone Blender tooling; no Blender process in unit/adapter scope. Needs separate fixture in Blender environment."
            elif names:
                note = "No direct test import; add focused behavior test or record reason."
            else:
                note = "No public class/function; inspect if side-effect behavior exists."
            rows.append({"service": service, "path": str(source.relative_to(ROOT)).replace("\\", "/"),
                         "category": category, "public_names": names, "direct_tests": direct, "note": note})
    output = ROOT / ".codex" / "local"
    output.mkdir(parents=True, exist_ok=True)
    (output / "test-module-inventory.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = [row for row in rows if row["public_names"] and not row["direct_tests"]]
    lines = ["# AI module inventory", "", f"Modules: {len(rows)}; public modules without direct test import: {len(missing)}.",
             "Direct import is not proof that all behavior is tested. See coverage and assertions.", "",
             "| Module | Public classes/functions | Direct tests | Status |", "| --- | --- | --- | --- |"]
    lines.extend(f"| {row['path']} | {', '.join(row['public_names']) or '—'} | {', '.join(row['direct_tests']) or '—'} | {row['note']} |" for row in rows)
    (output / "test-module-inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Inventory: {len(rows)} modules; {len(missing)} public modules without a direct test import.")


if __name__ == "__main__":
    main()
