"""Structural comparison is deterministic and conservative about unsupported input."""
import pytest

from core.intelligence.changes import build_change_context, compare_python
from core.input.snapshot import GitSnapshotProvider
from tests.test_input_snapshot import git, repository


def test_whitespace_and_comments_are_not_semantic_symbol_changes():
    assert compare_python("app.py", b"def f(x):\n return x\n", b"# hello\ndef f(x):\n    return x\n") == ()


def test_changed_signature_and_nested_method_are_identified():
    changes = compare_python("app.py", b"class A:\n def f(self, x):\n  return x\n",
                            b"class A:\n def f(self, x, y=1):\n  return x+y\n")
    method = next(change for change in changes if change.symbol == "A.f")
    assert method.signature_changed
    assert method.status == "modified"
    assert method.base_line == method.head_line == 2


def test_added_and_removed_symbols_are_not_guessed_to_be_renames():
    changes = compare_python("app.py", b"def old():\n return 1\n", b"def new():\n return 1\n")
    assert {(change.symbol, change.status) for change in changes} == {("old", "removed"), ("new", "added")}
    assert compare_python("new.py", None, b"async def task():\n pass\n")[0].kind == "async_function"


def test_parse_error_remains_an_explicit_context_gap(repository):
    root, base = repository
    (root / "app.py").write_text("def broken(\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "invalid syntax")
    provider = GitSnapshotProvider(root)
    package = build_change_context(provider, provider.resolve(base), ["app.py"])
    assert package.changes == ()
    assert "SyntaxError" in package.unresolved_context[0]
    assert package.source_refs


def test_file_limit_cannot_silently_claim_complete_context(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    package = build_change_context(provider, provider.resolve(base), ["app.py", "extra.py"], max_files=1)
    assert package.unresolved_context


def test_module_level_behavior_is_not_lost_outside_functions():
    changes = compare_python("config.py", b"LIMIT = 1\n", b"LIMIT = 2\n")
    assert changes[0].symbol == "<module>"
    assert changes[0].kind == "module"


def test_duplicate_definitions_require_explicit_investigation():
    with pytest.raises(ValueError, match="duplicate symbol"):
        compare_python("app.py", None, b"def f():\n pass\ndef f():\n return 1\n")
