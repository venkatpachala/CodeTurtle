import hashlib
import json
from pathlib import Path

import pytest

from benchmark.pilot import PilotCase, register, load_inputs, seal, score
from core.review.contract import ReviewTarget, ReviewHealth
from core.runtime.models import ReviewResult


def test_related_families_follow_transitive_aliases_and_patch_identity(tmp_path):
    from benchmark.pilot import related_families

    _, rows = make_pilot(tmp_path / "pilot")
    samples = [PilotCase.model_validate({k: v for k, v in row.items() if k != "split"}) for row in rows[:3]]
    samples[1] = samples[1].model_copy(update={"original_url": samples[0].pr_url.upper() + "/"})
    samples[2] = samples[2].model_copy(update={"family_id": samples[1].family_id, "previously_exposed": True})
    for ordered in (samples, list(reversed(samples))):
        groups = related_families(ordered)
        assert len(groups) == 1 and len(groups[0]) == 3


def test_static_and_native_predictions_cannot_share_a_pilot_seal(tmp_path):
    root = tmp_path / "pilot"
    _, cases = make_pilot(root)
    rows = predictions(cases)
    rows[0]["result"]["provenance"]["analysis_mode"] = "static_only"
    with pytest.raises(ValueError, match="mix reviewer/model profiles"):
        seal(root, rows, tmp_path / "mixed.json")


def make_pilot(root):
    patch=b"frozen public patch\n"
    cases=[PilotCase(case_id=f"case-{i}",pr_url=f"https://github.com/a/b/pull/{i+1}",
        original_url=f"https://github.com/a/b/pull/{i+1}",base_sha="a"*40,head_sha="b"*40,
        comparison_base_sha="a"*40,patch_sha256=hashlib.sha256(patch).hexdigest(),family_id=f"family-{i}",
        stratum="source_issue_candidate" if i<40 else "unreviewed_control",previously_exposed=i==0) for i in range(60)]
    manifest=register(cases,root)
    (root/"patches").mkdir()
    for case in cases: (root/"patches"/(case.case_id+".diff")).write_bytes(patch)
    return manifest,load_inputs(root)[1]


def predictions(cases):
    result=ReviewResult(decision="COMMENT",target=ReviewTarget(base_sha="a"*40,head_sha="b"*40),
        health=ReviewHealth(status="partial"),provenance={"reviewer_commit":"c"*40,"dirty":False,
            "provider":"fixture","model":"fixture","prompt_version":"v1"}).to_dict()
    return [{"pr_url":case["pr_url"],"result":json.loads(json.dumps(result))} for case in cases if case["split"]=="test"]


def test_real_registry_has_60_distinct_pinned_candidates_and_pending_truth():
    root=Path(__file__).resolve().parents[1]/"benchmark/datasets/real_pilot_v1"
    manifest,cases=load_inputs(root)
    assert manifest["split_counts"]=={"development":20,"validation":10,"test":30}
    assert len(cases)==len({c["family_id"] for c in cases})==60
    assert not manifest["eligible_for_headline_metrics"] and manifest["adjudication"]=="pending"


def test_exposed_families_are_development_only_and_truth_is_separate(tmp_path):
    manifest,cases=make_pilot(tmp_path/"pilot")
    assert next(c for c in cases if c["case_id"]=="case-0")["split"]=="development"
    assert all("truth" not in c for c in cases)
    assert not manifest["eligible_for_headline_metrics"]


def test_sealing_requires_every_attempt_and_refuses_overwrite_or_tampering(tmp_path):
    root=tmp_path/"pilot";_,cases=make_pilot(root);preds=predictions(cases);output=tmp_path/"sealed.json"
    with pytest.raises(ValueError,match="every selected"): seal(root,preds[:-1],output)
    seal(root,preds,output)
    with pytest.raises(FileExistsError): seal(root,preds,output)
    report=score(root,output,root/"annotations.pending.json")
    assert report["merge_safety"]["labels"]["unlabeled"]==30 and not report["labels_complete"]
    output.write_text("[]")
    with pytest.raises(ValueError,match="changed"): score(root,output,root/"annotations.pending.json")


def test_wrong_revision_and_mixed_profiles_cannot_be_sealed(tmp_path):
    root=tmp_path/"pilot";_,cases=make_pilot(root);preds=predictions(cases)
    preds[0]["result"]["target"]["head_sha"]="d"*40
    with pytest.raises(ValueError,match="target"): seal(root,preds,tmp_path/"one.json")
    preds=predictions(cases);preds[0]["result"]["provenance"]["model"]="different"
    with pytest.raises(ValueError,match="mix"): seal(root,preds,tmp_path/"two.json")


def test_failed_attempt_is_retained_without_claiming_its_source_was_reviewed(tmp_path):
    root=tmp_path/"pilot";_,cases=make_pilot(root);preds=predictions(cases)
    failed=preds[0]["result"];failed["health"]["status"]="failed";failed["decision"]=None
    preds[0]["attempted_target"]={"base_sha":"a"*40,"head_sha":"b"*40,"comparison_base_sha":"a"*40}
    failed["target"]={"repo":"","number":0,"base_sha":"","head_sha":"","comparison_base_sha":"","diff_sha256":""}
    output=tmp_path/"sealed.json";seal(root,preds,output)
    assert score(root,output,root/"annotations.pending.json")["merge_safety"]["no_verdict"]==1


def test_operational_report_counts_attempts_and_missing_reference_matches(tmp_path):
    root = tmp_path / "pilot"
    _, cases = make_pilot(root)
    rows = predictions(cases)
    for i, row in enumerate(rows, 1):
        row["elapsed_seconds"] = i
    output = tmp_path / "sealed.json"
    seal(root, rows, output)
    annotations = root / "annotations.pending.json"
    labels = json.loads(annotations.read_text())
    labels[rows[0]["pr_url"]].update(reference_status="exact_base_and_head_trees", issue_labels=[{}, {}])
    annotations.write_text(json.dumps(labels))
    report = score(root, output, annotations)
    assert report["operations"]["decisions"] == {"COMMENT": 30}
    assert report["operations"]["latency_seconds"]["p95_nearest_rank"] == 29
    assert report["findings"]["published_reference_issues_on_prs_with_zero_findings"] == 2
