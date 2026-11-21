"""V4 review runtime models. No LLM decision fields."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from core.review.contract import (
    REVIEW_RESULT_SCHEMA_VERSION,
    SUPPORTED_REVIEW_RESULT_SCHEMA_VERSIONS,
    ReviewCoverage,
    ReviewHealth,
    ReviewTarget,
)
from core.review.finding import ReviewFinding
from core.domain.observations import SourceObservation
from core.domain.finding_verification import CLAIM_FIELDS, FindingVerificationRecord
from core.domain.review_contracts import validate_investigation_evidence
from core.review.requirements import (
    EvidenceRecord,
    IntentSource,
    InvestigationRecord,
    Requirement,
    RequirementAssessment,
    RequirementCoverage,
)
from core.review.timing import TimingRecord
from core.review.trace import PipelineTrace


@dataclass
class Bundle:
    id: str
    paths: List[str] = field(default_factory=list)
    units: List[Any] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    kind: str = "source"
    risk_signals: List[Dict[str, Any]] = field(default_factory=list)
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    change_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        units = []
        for u in self.units:
            if hasattr(u, "model_dump"):
                units.append(u.model_dump())
            elif isinstance(u, dict):
                units.append(dict(u))
            else:
                units.append(u)
        return {
            "id": self.id,
            "paths": list(self.paths),
            "units": units,
            "symbols": list(self.symbols),
            "kind": self.kind,
            "risk_signals": [dict(signal) for signal in self.risk_signals],
            "requirements": [dict(requirement) for requirement in self.requirements],
            "change_context": dict(self.change_context),
        }

@dataclass
class Candidate:
    bundle_id: str
    file: str
    symbol: str = ""
    start_line: int = 0
    title: str = ""
    claim: str = ""
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    expected: str = ""
    actual: str = ""
    execution_path: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    verify_status: str = "candidate"  # candidate|verified|disproved|uncertain
    severity: str = "medium"
    confidence: float = 0.5
    source: str = "agent"  # agent | rule
    evidence_paths: List[str] = field(default_factory=list)
    kind: str = "defect"  # defect | note
    risk_signals: List[Dict[str, Any]] = field(default_factory=list)
    hypothesis_id: Optional[str] = None
    candidate_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Comment:
    bundle_id: str
    file: str
    symbol: str = ""
    start_line: int = 0
    title: str = ""
    claim: str = ""
    severity: str = "medium"
    source: str = "agent"
    evidence_paths: List[str] = field(default_factory=list)
    line: int = 0
    verification: str = "supported"
    kind: str = "defect"
    tests_run: bool = False
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    expected: str = ""
    actual: str = ""
    execution_path: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    verify_status: str = "candidate"
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def comment_from_candidate(cand: Candidate, line: int) -> Comment:
    status = str(getattr(cand, "verify_status", "") or "candidate")
    verification = {
        "verified": "supported",
        "uncertain": "uncertain",
        "disproved": "unsupported",
        "candidate": "uncertain",
    }.get(status, "uncertain")
    return Comment(
        bundle_id=cand.bundle_id,
        file=cand.file,
        symbol=cand.symbol,
        start_line=int(cand.start_line or 0),
        title=cand.title,
        claim=cand.claim,
        severity=cand.severity,
        source=cand.source,
        evidence_paths=list(cand.evidence_paths or cand.evidence or []),
        line=int(line),
        verification=verification,
        kind=str(cand.kind or "defect"),
        existing_code=str(getattr(cand, "existing_code", "") or ""),
        invariant=str(getattr(cand, "invariant", "") or ""),
        violating_condition=str(getattr(cand, "violating_condition", "") or ""),
        expected=str(getattr(cand, "expected", "") or ""),
        actual=str(getattr(cand, "actual", "") or ""),
        execution_path=list(getattr(cand, "execution_path", None) or []),
        evidence=list(getattr(cand, "evidence", None) or []),
        counter_evidence=list(getattr(cand, "counter_evidence", None) or []),
        verify_status=status,
        confidence=float(getattr(cand, "confidence", 0.5) or 0.5),
    )


def _unique_ids(values: Iterable[str], label: str) -> set[str]:
    ids: set[str] = set()
    for value in values:
        if value in ids:
            raise ValueError(f"duplicate {label}: {value}")
        ids.add(value)
    return ids


def _require_known(refs: Iterable[str], known: Iterable[str], label: str) -> None:
    missing = set(refs).difference(known)
    if missing:
        raise ValueError(f"unknown {label}: {', '.join(sorted(missing))}")


@dataclass
class ReviewResult:
    decision: Optional[str] = "COMMENT"
    policy_reason: str = ""
    comments: List[Comment] = field(default_factory=list)
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    bundles: List[Bundle] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)

    # ── New canonical fields (Sprint 1) ──────────────────────────────────────
    # findings is the authoritative list; comments is kept for backward compat.
    findings: List["ReviewFinding"] = field(default_factory=list)
    pipeline_trace: Optional[Any] = None
    timing: Optional[Any] = None
    agent_runs: List[Dict[str, Any]] = field(default_factory=list)
    pipeline_health: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = REVIEW_RESULT_SCHEMA_VERSION
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    target: ReviewTarget = field(default_factory=ReviewTarget)
    health: ReviewHealth = field(default_factory=ReviewHealth)
    inspection: ReviewCoverage = field(default_factory=ReviewCoverage)
    policy_reasons: List[str] = field(default_factory=list)
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    approval_eligible: bool = False
    provenance: Dict[str, Any] = field(default_factory=dict)
    intent_sources: list[IntentSource] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    requirement_assessments: list[RequirementAssessment] = field(default_factory=list)
    investigations: list[InvestigationRecord] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    source_observations: list[SourceObservation] = field(default_factory=list)
    finding_verifications: list[FindingVerificationRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._validate_contract_links()

    @property
    def requirement_coverage(self) -> RequirementCoverage:
        counts = Counter(assessment.status for assessment in self.requirement_assessments)
        assessed = counts["verified"] + counts["violated"] + counts["unverified"]
        return RequirementCoverage(
            total=len(self.requirements), verified=counts["verified"], violated=counts["violated"],
            unverified=counts["unverified"],
            not_assessed=len(self.requirements) - assessed - counts["not_applicable"],
            not_applicable=counts["not_applicable"],
        )

    def _validate_contract_links(self) -> None:
        source_ids = _unique_ids((source.id for source in self.intent_sources), "intent source ID")
        requirement_ids = _unique_ids((requirement.id for requirement in self.requirements), "requirement ID")
        claim_refs = _unique_ids(
            [*requirement_ids, *(finding.id for finding in self.findings),
             *(investigation.id for investigation in self.investigations)], "claim ID",
        )
        evidence_ids = _unique_ids((item.id for item in self.evidence), "evidence ID")
        investigation_ids = _unique_ids((item.id for item in self.investigations), "investigation ID")
        evidence = {item.id: item for item in self.evidence}
        _unique_ids((item.id for item in self.source_observations), "observation ID")
        observations = {item.id: SourceObservation.model_validate(item) for item in self.source_observations}
        for observation in observations.values():
            expected = self.target.head_sha if observation.revision_side == "head" else (self.target.comparison_base_sha or self.target.base_sha)
            if observation.revision_sha != expected.lower():
                raise ValueError("source observation does not match reviewed revision")
            snapshot_ids = {self.provenance.get("snapshot_id"), self.provenance.get("verification_snapshot_id")} - {None, ""}
            if snapshot_ids and observation.snapshot_id not in snapshot_ids:
                raise ValueError("source observation does not match reviewed snapshot")
        _unique_ids((item.id for item in self.finding_verifications), "finding verification ID")
        for verification in self.finding_verifications:
            checked = FindingVerificationRecord.model_validate(verification)
            checked.validate_sources(observations)
            published = [finding for finding in self.findings if self._is_product_finding(finding)
                         and finding.candidate_id == checked.candidate_id]
            if published and checked.verdict != "supported":
                raise ValueError("published finding requires supported final verification")
            # ReviewFinding carries every claim field except symbol. Bind the full
            # serialized behavior rather than accepting another claim at the same path.
            if any(any((tuple(getattr(finding, name)) if name == "execution_path" else getattr(finding, name))
                       != getattr(checked.claim, name) for name in CLAIM_FIELDS if name != "symbol")
                   for finding in published):
                raise ValueError("final verification addresses a different published claim")
        _unique_ids((item.requirement_id for item in self.requirement_assessments), "assessment")

        for requirement in self.requirements:
            _require_known(requirement.source_refs, source_ids, "intent source")
        for item in self.evidence:
            _require_known(item.observation_refs, observations, "source observation")
            for ref in item.observation_refs:
                observation = observations[ref]
                if (observation.status not in {"success", "truncated"}
                        or observation.revision_sha != item.revision_sha
                        or observation.revision_side != item.revision_side
                        or observation.excerpt_sha256 != item.content_hash):
                    raise ValueError("evidence does not match its source observation")
            _require_known((*item.supports_claim_refs, *item.contradicts_claim_refs), claim_refs, "claim")
            if item.revision_sha is not None:
                expected = self.target.head_sha if item.revision_side == "head" else (self.target.comparison_base_sha or self.target.base_sha)
                if item.revision_sha.lower() != expected.lower():
                    raise ValueError(f"evidence {item.id} does not match the reviewed {item.revision_side} revision")

        for assessment in self.requirement_assessments:
            _require_known((assessment.requirement_id,), requirement_ids, "requirement")
            _require_known(assessment.evidence_refs, evidence_ids, "evidence")
            if assessment.status not in {"verified", "violated"}:
                continue
            witnesses = [evidence[ref] for ref in assessment.evidence_refs if evidence[ref].is_head_behavior_evidence]
            if assessment.status == "verified":
                establishing = {claim for item in witnesses for claim in item.supports_claim_refs}
                direction = "supporting"
            else:
                establishing = {claim for item in witnesses for claim in item.contradicts_claim_refs}
                direction = "contradicting"
            if assessment.requirement_id not in establishing:
                raise ValueError(f"requirement {assessment.requirement_id} requires {direction} evidence for HEAD")

        verified = [finding for finding in self.findings if self._is_product_finding(finding)]
        verified_claims = {finding.id for finding in verified}
        verified_hypotheses = {finding.hypothesis_id for finding in verified}
        investigated_claims: set[str] = set()
        for investigation in self.investigations:
            _require_known(investigation.requirement_refs, requirement_ids, "requirement")
            _require_known(investigation.claim_refs, claim_refs, "claim")
            _require_known(investigation.evidence_refs, evidence_ids, "evidence")
            investigated_claims.update(investigation.claim_refs)
            has_verified_finding = (
                investigation.id in verified_hypotheses or bool(verified_claims.intersection(investigation.claim_refs))
            )
            if has_verified_finding and investigation.status != "confirmed":
                raise ValueError(f"a verified finding requires a confirmed investigation: {investigation.id}")
            validate_investigation_evidence(investigation, evidence)

        for finding in self.findings:
            _require_known(finding.evidence_ids, evidence_ids, "evidence")
        for finding in verified:
            typed_investigation = finding.id in investigated_claims or finding.hypothesis_id in investigation_ids
            if (typed_investigation or finding.evidence_ids) and not any(
                evidence[ref].is_head_behavior_evidence and finding.id in evidence[ref].supports_claim_refs
                for ref in finding.evidence_ids
            ):
                raise ValueError(f"verified finding {finding.id} requires supporting evidence for HEAD")

    @staticmethod
    def _is_product_finding(finding: ReviewFinding) -> bool:
        return finding.kind == "defect" and finding.verification_status == "verified"

    @property
    def product_findings(self) -> List[ReviewFinding]:
        self._validate_contract_links()
        return [finding for finding in self.findings if self._is_product_finding(finding)]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewResult:
        """Load a canonical or CLI-wrapped v2 result and upgrade it to the current schema."""
        raw = payload.get("result", payload)
        if not isinstance(raw, Mapping) or raw.get("schema_version") not in SUPPORTED_REVIEW_RESULT_SCHEMA_VERSIONS:
            raise ValueError("unsupported review result schema")
        if "decision" not in raw:
            raise ValueError("review result is missing decision")

        data = {item.name: raw[item.name] for item in fields(cls) if item.name in raw}
        data.update(
            schema_version=REVIEW_RESULT_SCHEMA_VERSION,
            target=ReviewTarget.model_validate(raw.get("target", {})),
            health=ReviewHealth.model_validate(raw.get("health", {})),
            inspection=ReviewCoverage.model_validate(raw.get("inspection", {})),
            comments=[Comment(**item) for item in raw.get("comments", [])],
            bundles=[Bundle(**item) for item in raw.get("bundles", [])],
            findings=[ReviewFinding.from_dict(item) for item in raw.get("findings", [])],
            pipeline_trace=PipelineTrace.from_list(raw["pipeline_trace"]) if raw.get("pipeline_trace") else None,
            timing=TimingRecord.from_dict(raw["timing"]) if raw.get("timing") else None,
            intent_sources=[IntentSource.model_validate(item) for item in raw.get("intent_sources", [])],
            requirements=[Requirement.model_validate(item) for item in raw.get("requirements", [])],
            requirement_assessments=[
                RequirementAssessment.model_validate(item) for item in raw.get("requirement_assessments", [])
            ],
            investigations=[InvestigationRecord.model_validate(item) for item in raw.get("investigations", [])],
            evidence=[EvidenceRecord.model_validate(item) for item in raw.get("evidence", [])],
            source_observations=[SourceObservation.model_validate(item) for item in raw.get("source_observations", [])],
            finding_verifications=[FindingVerificationRecord.model_validate(item) for item in raw.get("finding_verifications", [])],
        )
        result = cls(**data)
        if "requirement_coverage" in raw:
            expected = result.requirement_coverage.model_dump()
            recorded = raw["requirement_coverage"]
            if not isinstance(recorded, Mapping) or any(
                key not in expected or expected[key] != value for key, value in recorded.items()
            ) or not all(key in recorded for key in ("total", "verified", "violated", "unverified", "not_assessed")):
                raise ValueError("requirement_coverage does not match the recorded assessments")
        return result

    def to_dict(self) -> Dict[str, Any]:
        trace = self.pipeline_trace
        timing = self.timing
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "target": self.target.model_dump(),
            "health": self.health.model_dump(),
            "inspection": {**self.inspection.model_dump(), "ratio": self.inspection.inspection_ratio},
            "policy_reasons": list(self.policy_reasons),
            "unresolved": list(self.unresolved),
            "approval_eligible": self.approval_eligible,
            "provenance": dict(self.provenance),
            "product_findings": [f.to_dict() for f in self.product_findings],
            "decision": self.decision,
            "policy_reason": self.policy_reason,
            "comments": [c.to_dict() for c in self.comments],
            "dropped": list(self.dropped),
            "bundles": [b.to_dict() for b in self.bundles],
            "coverage": dict(self.coverage or {}),
            "execution": dict(self.execution or {}),
            "findings": [f.to_dict() for f in self.findings] if self.findings else [],
            "pipeline_trace": trace.to_list() if trace is not None and hasattr(trace, "to_list") else [],
            "timing": timing.to_dict() if timing is not None and hasattr(timing, "to_dict") else {},
            "agent_runs": list(self.agent_runs),
            "pipeline_health": dict(self.pipeline_health),
            "intent_sources": [source.model_dump(mode="json") for source in self.intent_sources],
            "requirements": [requirement.model_dump(mode="json") for requirement in self.requirements],
            "requirement_assessments": [
                assessment.model_dump(mode="json") for assessment in self.requirement_assessments
            ],
            "investigations": [item.model_dump(mode="json") for item in self.investigations],
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "source_observations": [item.model_dump(mode="json") for item in self.source_observations],
            "finding_verifications": [item.model_dump(mode="json") for item in self.finding_verifications],
            "requirement_coverage": self.requirement_coverage.model_dump(mode="json"),
        }
