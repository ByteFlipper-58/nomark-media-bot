"""Architectural boundary tests enforcing Clean Architecture dependency rules via AST."""

from __future__ import annotations

import ast
import builtins
import inspect
import string
import unittest
from pathlib import Path

from nomark.infrastructure import pipelines
from nomark.presentation.i18n import TRANSLATIONS

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

    def test_no_undefined_names_in_project_modules(self) -> None:
        """Catch missing imports (e.g. NameError inside Modal worker methods) statically via AST."""
        builtin_names = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__package__"}
        targets = [ROOT / "modal_app.py", *sorted(NOMARK_DIR.rglob("*.py"))]
        for py in targets:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            # Collect module-level & nested defined names (imports, defs, classes, targets, params, comprehensions)
            defined = set(builtin_names)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(node.name)
                elif isinstance(node, ast.arg):
                    defined.add(node.arg)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        defined.add(alias.asname or alias.name.split(".", 1)[0])
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name != "*":
                            defined.add(alias.asname or alias.name)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    defined.add(node.id)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    defined.add(node.name)
                elif isinstance(node, ast.Global):
                    defined.update(node.names)
                elif isinstance(node, ast.Nonlocal):
                    defined.update(node.names)

            # Skip stringified type annotations (from __future__ import annotations)
            annotation_ids: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns is not None:
                        annotation_ids.update(id(n) for n in ast.walk(node.returns))
                    for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                        if a.annotation is not None:
                            annotation_ids.update(id(n) for n in ast.walk(a.annotation))
                    if node.args.vararg and node.args.vararg.annotation:
                        annotation_ids.update(id(n) for n in ast.walk(node.args.vararg.annotation))
                    if node.args.kwarg and node.args.kwarg.annotation:
                        annotation_ids.update(id(n) for n in ast.walk(node.args.kwarg.annotation))
                elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
                    annotation_ids.update(id(n) for n in ast.walk(node.annotation))

            undefined: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if id(node) in annotation_ids:
                        continue
                    if node.id not in defined:
                        undefined.append(f"{node.id} (line {node.lineno})")
            self.assertEqual(undefined, [], f"Undefined names in {py.relative_to(ROOT)}: {undefined}")

    def test_all_i18n_callsites_and_pipeline_kwargs_match(self) -> None:
        """Verify every t(...) call uses valid keys/placeholders and modal_app matches pipeline signatures."""
        formatter = string.Formatter()
        for py in [ROOT / "modal_app.py", *sorted(NOMARK_DIR.rglob("*.py"))]:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        key = node.args[0].value
                        self.assertIn(key, TRANSLATIONS["ru"], f"{py}:{node.lineno} unknown key {key!r}")
                        self.assertIn(key, TRANSLATIONS["en"], f"{py}:{node.lineno} unknown key {key!r}")
                        expected = {f for _, f, _, _ in formatter.parse(TRANSLATIONS["ru"][key]) if f is not None} - {"bot"}
                        passed = {kw.arg for kw in node.keywords if kw.arg is not None}
                        if not any(kw.arg is None for kw in node.keywords):
                            self.assertEqual(
                                passed,
                                expected,
                                f"{py}:{node.lineno} t({key!r}) kwargs mismatch: passed={passed} expected={expected}",
                            )

        modal_tree = ast.parse((ROOT / "modal_app.py").read_text(encoding="utf-8"))
        pipe_sigs = {name: inspect.signature(fn) for name, fn in inspect.getmembers(pipelines, inspect.isfunction)}
        for node in ast.walk(modal_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in pipe_sigs:
                sig = pipe_sigs[node.func.id]
                params = sig.parameters
                passed_kw = {kw.arg for kw in node.keywords if kw.arg is not None}
                self.assertEqual(passed_kw - set(params.keys()), set(), f"Unknown kwargs to {node.func.id}")
                pos_names = set(list(params.keys())[: len(node.args)])
                required = {
                    n
                    for n, p in params.items()
                    if p.default is inspect.Parameter.empty
                    and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                }
                self.assertEqual(required - passed_kw - pos_names, set(), f"Missing kwargs to {node.func.id}")


if __name__ == "__main__":
    unittest.main()
