from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

SymbolExpectation = Tuple[str, str, str]


@dataclass
class EvalResult:
    name: str
    passed: bool
    score: float
    details: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    repo_name: str
    results: List[EvalResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)

    def add(self, result: EvalResult):
        self.results.append(result)

    @property
    def overall_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)


class RepositoryIntelligenceEvaluator:
    def __init__(self, repo_name: str, force_reindex: bool = False):
        self.repo_name = repo_name
        self.force_reindex = force_reindex
        self.report = EvaluationReport(repo_name=repo_name)

        from core.repository_intelligence import RepositoryIntelligence
        from core.repository_persistence import RepositoryPersistence
        from core.knowledge_base import KnowledgeBase

        self.RepositoryIntelligence = RepositoryIntelligence
        self.RepositoryPersistence = RepositoryPersistence
        self.KnowledgeBase = KnowledgeBase

    def run(self) -> EvaluationReport:
        console.print(
            Panel.fit(
                f"[bold cyan]Repository Intelligence Structural Evaluation[/bold cyan]\n"
                f"Repository: {self.repo_name}",
                title="CodeTurtle"
            )
        )

        from tests.evaluation.golden_datasets import get_golden
        golden = get_golden(self.repo_name)

        model, kb_stats = self._ensure_indexed()

        # Recommended order
        self._eval_directory_discovery(model, golden)
        self._eval_file_presence(model, golden)
        self._eval_negative_paths(model, golden)
        self._eval_symbol_locations(model, golden)
        self._eval_content_contains_symbols(model, golden)
        self._eval_symbol_index_accuracy(model, golden)
        self._eval_negative_symbols(model, golden)
        self._eval_content_integrity(model)
        self._eval_basic_stats(model, kb_stats, golden)

        self._print_report()
        return self.report

    # ---------------------------------------------------------------
    def _ensure_indexed(self):
        console.print("\n[bold]Ensuring repository is indexed...[/bold]")

        # First try loading an existing RepositoryModel
        persistence = self.RepositoryPersistence(self.repo_name)
        model = persistence.load_repository_model()

        if model is None or self.force_reindex:
            console.print("  RepositoryModel not found. Re-indexing...")

            repo_root = Path("repos") / self.repo_name

            if not repo_root.exists():
                raise FileNotFoundError(
                    f"Repository not found locally: {repo_root}\n"
                    f"Run:\n"
                    f"python -m cli.main add-repo {self.repo_name}"
                )

            intelligence = self.RepositoryIntelligence(
                repo_path=str(repo_root),
                repo_name=self.repo_name,
            )

            intelligence.index_repository(force=True)
            model = intelligence.repository_model

        else:
            console.print("  Loaded existing RepositoryModel.")

        collection_name = self.repo_name.replace("/", "_")
        kb = self.KnowledgeBase(collection_name)

        try:
            points_count = kb.client.get_collection(collection_name).points_count
        except Exception:
            points_count = 0

        return model, {
            "points_count": points_count,
            "collection": collection_name,
        }

    # ---------------------------------------------------------------
    # 1. Directory discovery
    # ---------------------------------------------------------------
    def _eval_directory_discovery(self, model, golden):
        must_dirs = golden.get("must_exist_directories", [])
        if not must_dirs:
            self.report.add(EvalResult(
                name="Directory Discovery",
                passed=True,
                score=0.6,
                details="No must_exist_directories defined (skipped)"
            ))
            return

        model_dirs = set()
        for fm in model.files:
            p = Path(fm.path)
            for parent in p.parents:
                if str(parent) != ".":
                    model_dirs.add(str(parent).replace("\\", "/"))

        missing = [d for d in must_dirs if d not in model_dirs]
        found = len(must_dirs) - len(missing)
        score = found / len(must_dirs)
        passed = len(missing) == 0

        self.report.add(EvalResult(
            name="Directory Discovery",
            passed=passed,
            score=score,
            details=f"Found {found}/{len(must_dirs)} required directories. Missing: {missing or 'None'}",
            metrics={"missing_dirs": missing}
        ))

    # ---------------------------------------------------------------
    # 2. File presence
    # ---------------------------------------------------------------
    def _eval_file_presence(self, model, golden):
        file_map = {fm.path: fm for fm in model.files}
        must_exist = golden.get("must_exist_files", [])

        if not must_exist:
            self.report.add(EvalResult(
                name="File Presence",
                passed=True,
                score=0.6,
                details="No must_exist_files defined (skipped)"
            ))
            return

        missing = [f for f in must_exist if f not in file_map]
        found = len(must_exist) - len(missing)
        score = found / len(must_exist)
        passed = len(missing) == 0

        self.report.add(EvalResult(
            name="File Presence",
            passed=passed,
            score=score,
            details=f"Found {found}/{len(must_exist)} required files. Missing: {missing or 'None'}",
            metrics={"missing_files": missing}
        ))

    # ---------------------------------------------------------------
    # 3. Negative path checks
    # ---------------------------------------------------------------
    def _eval_negative_paths(self, model, golden):
        forbidden_substrings = golden.get("forbidden_path_substrings", [])
        must_not_exist = golden.get("must_not_exist_files", [])

        all_paths = [fm.path for fm in model.files]

        violations = []
        for path in all_paths:
            if any(bad in path for bad in forbidden_substrings):
                violations.append(path)

        for f in must_not_exist:
            if f in all_paths:
                violations.append(f)

        passed = len(violations) == 0
        score = 1.0 if passed else max(0.0, 1.0 - len(violations) / max(1, len(all_paths)))

        self.report.add(EvalResult(
            name="Negative Path Checks",
            passed=passed,
            score=score,
            details=f"Violations: {violations[:10] or 'None'}",
            metrics={"violations": violations}
        ))

    # ---------------------------------------------------------------
    # 4. Symbol locations
    # ---------------------------------------------------------------
    def _eval_symbol_locations(self, model, golden):
        expected: List[SymbolExpectation] = golden.get("expected_symbols", [])
        if not expected:
            self.report.add(EvalResult(
                name="Symbol Locations",
                passed=True,
                score=0.6,
                details="No expected_symbols defined (skipped)"
            ))
            return

        file_map = {fm.path: fm for fm in model.files}
        correct = 0
        failures = []

        for file_path, symbol_name, symbol_type in expected:
            fm = file_map.get(file_path)
            if fm is None:
                failures.append(f"{symbol_name} → file '{file_path}' not found")
                continue

            symbols = getattr(fm, "symbols", []) or []
            match = next(
                (s for s in symbols
                 if s.name == symbol_name and (not symbol_type or s.type == symbol_type)),
                None
            )

            if match:
                correct += 1
            else:
                failures.append(f"{symbol_name} ({symbol_type}) not found inside {file_path}")

        score = correct / len(expected)
        passed = score >= 0.9

        self.report.add(EvalResult(
            name="Symbol Locations",
            passed=passed,
            score=score,
            details=f"{correct}/{len(expected)} symbols in correct files. Failures: {failures[:5]}",
            metrics={"correct": correct, "total": len(expected), "failures": failures}
        ))

    # ---------------------------------------------------------------
    # 5. Content contains symbol definitions
    # ---------------------------------------------------------------
    def _eval_content_contains_symbols(self, model, golden):
        expected = golden.get("expected_symbols", [])
        if not expected:
            self.report.add(EvalResult(
                name="Content Contains Symbols",
                passed=True,
                score=0.6,
                details="No expected_symbols defined (skipped)"
            ))
            return

        file_map = {fm.path: fm for fm in model.files}
        correct = 0
        failures = []

        for file_path, symbol_name, symbol_type in expected:
            fm = file_map.get(file_path)
            if fm is None:
                failures.append(f"File missing: {file_path}")
                continue

            content = getattr(fm, "content", "") or ""
            if not content.strip():
                failures.append(f"Empty content: {file_path}")
                continue

            if symbol_type == "class":
                pattern_found = f"class {symbol_name}" in content
            else:
                pattern_found = f"def {symbol_name}" in content

            if not pattern_found and file_path.endswith(".py"):
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.name == symbol_name:
                                pattern_found = True
                                break
                except Exception:
                    pass

            if pattern_found:
                correct += 1
            else:
                failures.append(f"'{symbol_name}' definition not found in content of {file_path}")

        score = correct / len(expected)
        passed = score >= 0.9

        self.report.add(EvalResult(
            name="Content Contains Symbol Definitions",
            passed=passed,
            score=score,
            details=f"{correct}/{len(expected)} definitions found in stored content. Failures: {failures[:5]}",
            metrics={"correct": correct, "failures": failures}
        ))

    # ---------------------------------------------------------------
    # 6. Symbol index accuracy
    # ---------------------------------------------------------------
    def _eval_symbol_index_accuracy(self, model, golden):
        expected = golden.get("expected_symbols", [])
        index = getattr(model, "symbol_index", {}) or {}

        if not expected:
            self.report.add(EvalResult(
                name="Symbol Index Accuracy",
                passed=True,
                score=0.6,
                details="No expected_symbols defined (skipped)"
            ))
            return

        correct = 0
        failures = []

        for file_path, symbol_name, symbol_type in expected:
            possible_keys = [
                f"{file_path}::{symbol_name}",
                f"{file_path}:{symbol_name}",
                symbol_name,
            ]

            found = any(key in index for key in possible_keys)
            if found:
                correct += 1
            else:
                failures.append(f"Index missing: {file_path}::{symbol_name}")

        score = correct / len(expected)
        passed = score >= 0.85

        self.report.add(EvalResult(
            name="Symbol Index Accuracy",
            passed=passed,
            score=score,
            details=f"{correct}/{len(expected)} expected symbols present in symbol_index",
            metrics={"correct": correct, "failures": failures}
        ))

    # ---------------------------------------------------------------
    # 7. Negative symbol checks
    # ---------------------------------------------------------------
    def _eval_negative_symbols(self, model, golden):
        forbidden = golden.get("must_not_contain_symbols", [])
        if not forbidden:
            self.report.add(EvalResult(
                name="Negative Symbol Checks",
                passed=True,
                score=0.6,
                details="No must_not_contain_symbols defined (skipped)"
            ))
            return

        file_map = {fm.path: fm for fm in model.files}
        violations = []

        for file_path, symbol_name, symbol_type in forbidden:
            fm = file_map.get(file_path)
            if fm is None:
                continue
            symbols = getattr(fm, "symbols", []) or []
            for s in symbols:
                if s.name == symbol_name and (not symbol_type or s.type == symbol_type):
                    violations.append(f"{file_path}::{symbol_name}")
                    break

        passed = len(violations) == 0
        score = 1.0 if passed else max(0.0, 1.0 - len(violations) / max(1, len(forbidden)))

        self.report.add(EvalResult(
            name="Negative Symbol Checks",
            passed=passed,
            score=score,
            details=f"Violations: {violations[:10] or 'None'}",
            metrics={"violations": violations}
        ))

    # ---------------------------------------------------------------
    # 8. Content non-empty
    # ---------------------------------------------------------------
    def _eval_content_integrity(self, model):
        empty = sum(1 for fm in model.files if not (getattr(fm, "content", "") or "").strip())
        total = len(model.files)
        ratio = empty / total if total else 1.0
        passed = ratio < 0.05
        score = 1.0 - ratio

        self.report.add(EvalResult(
            name="Content Non-Empty",
            passed=passed,
            score=score,
            details=f"{empty}/{total} files have empty content"
        ))

    # ---------------------------------------------------------------
    # 9. Volume bounds
    # ---------------------------------------------------------------
    def _eval_basic_stats(self, model, kb_stats, golden):
        total_files = len(model.files)
        total_symbols = sum(len(getattr(fm, "symbols", []) or []) for fm in model.files)
        points = kb_stats.get("points_count", 0)

        checks = [
            ("files", total_files, golden.get("min_files", 0), golden.get("max_files", 999999)),
            ("symbols", total_symbols, golden.get("min_symbols", 0), golden.get("max_symbols", 999999)),
            ("chunks", points, golden.get("min_chunks", 0), golden.get("max_chunks", 999999)),
        ]

        for name, value, min_v, max_v in checks:
            passed = min_v <= value <= max_v
            score = 1.0 if passed else 0.4
            self.report.add(EvalResult(
                name=f"Volume: {name}",
                passed=passed,
                score=score,
                details=f"{value} (expected {min_v}–{max_v})"
            ))

    # ---------------------------------------------------------------
    def _print_report(self):
        console.print("\n")
        table = Table(title=f"Structural Evaluation — {self.repo_name}")
        table.add_column("Check", style="cyan", width=40)
        table.add_column("Status", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Details")

        for r in self.report.results:
            status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
            table.add_row(r.name, status, f"{r.score:.2f}", r.details[:80])

        console.print(table)

        overall = self.report.overall_score
        color = "green" if overall >= 0.85 else "yellow" if overall >= 0.65 else "red"
        console.print(f"\n[bold {color}]Overall Score: {overall:.1%}[/bold {color}]")