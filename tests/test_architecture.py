"""Architectural boundary tests enforcing Clean Architecture dependency rules via AST."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOMARK_DIR = ROOT / "nomark"


def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _violates(imported: set[str], forbidden_prefixes: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for mod in sorted(imported):
        for prefix in forbidden_prefixes:
            if mod == prefix or mod.startswith(f"{prefix}."):
                hits.append(mod)
    return hits


class CleanArchitectureBoundaryTests(unittest.TestCase):
    def test_domain_layer_is_pure(self) -> None:
        forbidden = (
            "nomark.application",
            "nomark.presentation",
            "nomark.infrastructure",
            "modal",
            "modal_app",
            "fastapi",
            "httpx",
            "PIL",
            "piexif",
            "torch",
            "diffusers",
            "remove_ai_watermarks",
        )
        for py in (NOMARK_DIR / "domain").glob("*.py"):
            hits = _violates(_imported_modules(py), forbidden)
            self.assertEqual(hits, [], f"Domain layer {py.name} must not import {hits}")

    def test_presentation_layer_has_no_app_or_infra_imports(self) -> None:
        forbidden = (
            "nomark.application",
            "nomark.infrastructure",
            "modal",
            "modal_app",
            "fastapi",
            "httpx",
        )
        for py in (NOMARK_DIR / "presentation").glob("*.py"):
            hits = _violates(_imported_modules(py), forbidden)
            self.assertEqual(hits, [], f"Presentation layer {py.name} must not import {hits}")

    def test_application_layer_depends_only_on_domain_and_presentation(self) -> None:
        forbidden = (
            "nomark.infrastructure",
            "modal",
            "modal_app",
            "fastapi",
            "httpx",
            "torch",
            "diffusers",
            "remove_ai_watermarks",
        )
        for py in (NOMARK_DIR / "application").glob("*.py"):
            hits = _violates(_imported_modules(py), forbidden)
            self.assertEqual(hits, [], f"Application layer {py.name} must not import {hits}")

    def test_nomark_never_imports_composition_root(self) -> None:
        for py in NOMARK_DIR.rglob("*.py"):
            hits = _violates(_imported_modules(py), ("modal_app",))
            self.assertEqual(hits, [], f"{py} must never import modal_app")

    def test_pipelines_do_not_import_modal(self) -> None:
        py = NOMARK_DIR / "infrastructure" / "pipelines.py"
        hits = _violates(_imported_modules(py), ("modal", "modal_app"))
        self.assertEqual(hits, [], f"pipelines.py must stay decoupled from Modal: {hits}")


if __name__ == "__main__":
    unittest.main()
