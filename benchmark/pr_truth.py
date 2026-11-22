"""Explicit PR labels: absence of known issues never establishes cleanliness."""
from typing import Literal

from pydantic import Field, model_validator

from core.domain.review_contracts import DomainRecord


class PRTruth(DomainRecord):
    label: Literal["defective", "reviewed_clean", "uncertain"]
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    labelers: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_provenance(self):
        if any(not item.strip() for item in (*self.labelers, *self.evidence)) or not self.rationale.strip():
            raise ValueError("PR truth needs named labelers and nonempty audit evidence")
        return self

    def check_target(self, prediction: dict) -> None:
        target = prediction.get("target") or {}
        if target.get("head_sha") != self.head_sha or target.get("base_sha") != self.base_sha:
            raise ValueError("PR truth does not match prediction BASE/HEAD")


def rate_estimate(events: int, total: int) -> dict:
    """Two-sided 95% Wilson interval; zero denominator means unmeasured."""
    if not 0 <= events <= total:
        raise ValueError("invalid rate counts")
    interval = None
    if total:
        z = 1.959963984540054
        proportion = events / total
        scale = 1 + z*z/total
        center = (proportion + z*z/(2*total))/scale
        radius = z*((proportion*(1-proportion)/total + z*z/(4*total*total))**0.5)/scale
        interval = [max(0.0, center-radius), min(1.0, center+radius)]
    return {"events": events, "total": total, "rate": events/total if total else None,
            "wilson_95": interval}


def merge_safety(evaluations: list[dict], predictions: list[dict]) -> dict:
    if len(evaluations) != len(predictions):
        return {"measured": False, "reason": "unpaired_evaluations_and_predictions"}
    defective = bad = labeled_merges = unknown_merges = merges = 0
    labels = {"defective": 0, "reviewed_clean": 0, "uncertain": 0, "unlabeled": 0}
    no_verdict = 0
    for evaluation, prediction in zip(evaluations, predictions):
        if evaluation.get("pr_url") and prediction.get("pr_url") != evaluation["pr_url"]:
            raise ValueError("evaluation/prediction PR identities differ")
        label = evaluation.get("pr_truth", "unlabeled")
        if label not in labels:
            raise ValueError("unknown PR truth label")
        labels[label] += 1
        decision = prediction.get("decision") or prediction.get("recommendation")
        is_merge = str(decision).upper() == "MERGE"
        no_verdict += int(decision not in {"MERGE", "COMMENT", "REQUEST_CHANGES"})
        defective += int(label == "defective")
        bad += int(is_merge and label == "defective")
        merges += int(is_merge)
        labeled_merges += int(is_merge and label in {"defective", "reviewed_clean"})
        unknown_merges += int(is_merge and label in {"uncertain", "unlabeled"})
    return {"measured": True, "labels": labels, "no_verdict": no_verdict,
            "false_merge_given_defective": rate_estimate(bad, defective),
            "defective_given_labeled_merge": rate_estimate(bad, labeled_merges),
            "all_merges": merges, "unlabeled_or_uncertain_merges": unknown_merges,
            "all_merge_defect_rate_label_bounds": [bad/merges, (bad+unknown_merges)/merges] if merges else None,
            "limitation": "Wilson intervals assume independent representative PRs; label bounds are not confidence intervals."}
