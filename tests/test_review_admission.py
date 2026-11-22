from core.review.admission import plan_admission, touches_persistence
from core.review.contract import ReviewCoverage, ReviewHealth, evaluate_policy
from core.input.impact import SnapshotImpactIndex
from core.change_units import unit_kind
from tests.test_input_snapshot import repository
from core.input.snapshot import GitSnapshotProvider


def test_late_guard_removal_outranks_imports_and_limits_are_auditable():
    units = [{"id": str(i), "path": "auth.py", "kind": "source", "excerpt": "+import names"} for i in range(8)]
    units.append({"id": "guard", "path": "auth.py", "kind": "source", "excerpt": "-if not allowed:\n-    raise Denied()\n+return data"})
    chosen, records = plan_admission(units, max_units=2)
    assert chosen[0]["id"] == "guard" and len(chosen) == 2
    assert records[0]["reasons"][1] == "removed_control_or_effect"
    assert sum(r["reason"] == "unit_limit" for r in records) == 7


def test_non_executable_and_oversized_units_do_not_consume_budget():
    units = [{"id":"doc","kind":"docs","excerpt":"+read me"},
             {"id":"big","kind":"source","excerpt":"x"*2501},
             {"id":"small","kind":"source","excerpt":"+return 1"}]
    chosen, records = plan_admission(units)
    assert [u["id"] for u in chosen] == ["small"]
    assert {r["reason"] for r in records} == {"selected", "excerpt_limit", "non_executable_change"}


def test_impact_cache_reads_once_and_ignores_dirty_worktree(repository, monkeypatch):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    original = provider.read
    calls = []
    def read(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(provider, "read", read)
    (root/"app.py").write_text("injected = True")
    index = SnapshotImpactIndex(provider, snapshot, ["app.py"])
    assert index.search("limit")["matches"][0]["text"] == "limit = 2"
    assert not index.search("injected")["matches"]
    assert calls == ["app.py"]


def test_cross_language_test_paths_are_not_ranked_as_production_source():
    for path in ["crates/gateway/tests/auth.rs", "auth_test.go", "spec/auth_spec.rb"]:
        assert unit_kind(path) == "test"


def test_persistence_argument_change_gets_priority_and_requires_human_review():
    unit = {"id": "persistence", "kind": "source", "excerpt":
            "   await prisma.reminder.deleteMany({\n-    attempts: 3\n+    attempts: 1"}
    other = {"id": "value", "kind": "source", "excerpt": "-limit = 3\n+limit = 1"}
    selected, plan = plan_admission([other, unit], max_units=1)
    assert selected == [unit] and "persistence_mutation" in plan[0]["reasons"]
    assert not touches_persistence(unit | {"kind": "test"})
    assert not touches_persistence({"kind": "source", "excerpt": "+params.update(values)"})
    outcome = evaluate_policy(health=ReviewHealth(status="completed"),
        coverage=ReviewCoverage(eligible=1, packed=1, inspected=1), findings=[],
        unresolved=[], execution={}, persistence_changed=touches_persistence(unit))
    assert outcome.decision == "COMMENT" and not outcome.approval_eligible
    assert outcome.reasons == ["persistence_change_requires_review"]
