"""Final decisions survive serialization and cannot be rebound to another claim."""
import copy
import json
from types import SimpleNamespace

import pytest

from core.runtime.models import Bundle, ReviewResult
from core.runtime.review_runtime import ReviewRuntime
from core.runtime.verify_loop import verify_candidates
from core.verification.diff_index import build_diff_index
from tests.test_input_snapshot import git, repository
from tests.test_requirement_first_runtime import run_case
from tests.test_requirement_investigator import requirement_case
from tests.test_source_finding_verifier import candidate, response_for


@pytest.mark.parametrize("tamper", ["quote", "fingerprint", "claim", "outcome", "snapshot", "remove_refs"])
def test_serialized_verification_rejects_tampered_evidence_or_published_claim(requirement_case, tamper):
    result = run_case(requirement_case)
    raw = copy.deepcopy(result.to_dict())
    record = raw["finding_verifications"][0]
    if tamper == "quote":
        record["decision"]["supporting_citations"][0]["quote"] = "invented"
    elif tamper == "fingerprint":
        record["claim"]["actual"] = "different failure"
    elif tamper == "claim":
        raw["findings"][0]["expected"] = "a different contract"
    elif tamper == "outcome":
        record["verdict"] = "unresolved"
    elif tamper == "snapshot":
        record["snapshot_id"] = "a" * 64
    else:
        record["observation_refs"] = []
    with pytest.raises(ValueError):
        ReviewResult.from_dict(raw)


def test_unstructured_response_is_unresolved_and_degrades_health(requirement_case):
    result = run_case(requirement_case, verdict="DISPROVED")
    assert result.product_findings == []
    assert result.health.status == "partial"
    record = result.finding_verifications[0]
    assert record.verdict == "unresolved"
    assert record.status == "invalid_response"
    assert [attempt.response for attempt in record.attempts] == ["DISPROVED", "DISPROVED"]
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_graph_and_related_tests_are_hints_in_structured_path():
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def size(items):\n-    return 0\n+    return len(items)\n"
    graph = SimpleNamespace(get_node=lambda _: SimpleNamespace(raw_text="if items is None: raise ValueError; validate returns zero"),
                            get_neighbors=lambda _: SimpleNamespace(raw_text=""))
    bundle = Bundle(id="B1", paths=["app.py"], units=[{"path": "tests/test_size.py", "excerpt": "assert zero == 0"}])
    captured = []
    def verify(cand, context, hints):
        captured.extend(hints)
        return "VERIFIED"
    kept, dropped = verify_candidates([candidate()], index=build_diff_index(diff), bundles=[bundle],
                                     client=graph, source_verifier=verify)
    assert len(kept) == 1 and not dropped
    assert len(captured) == 2
    assert "graph" in captured[0] and "test" in captured[1]


def test_pr_source_capture_uses_merge_base_without_replacing_publication_target(requirement_case):
    provider, original, _ = requirement_case
    root = provider.root
    git(root, "checkout", "--detach", original.base_sha)
    (root / "unrelated.py").write_text("target_only = True\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "target branch advanced")
    target = git(root, "rev-parse", "HEAD")
    discovered = candidate().to_dict()
    discovered.pop("candidate_id")
    result = ReviewRuntime(llm=lambda _: json.dumps([discovered]),
        finding_verification_llm=lambda prompt: json.dumps(response_for(prompt))).run(SimpleNamespace(
            repo_dir=str(root), pr_base_sha=target, pr_head_sha=original.head_sha,
            files_changed=["app.py"], full_diff=provider.diff(original)))
    assert len(result.product_findings) == 1
    assert result.target.base_sha == target
    assert result.target.comparison_base_sha == original.base_sha
    assert {obs.revision_sha for obs in result.source_observations if obs.revision_side == "base"} == {original.base_sha}
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
