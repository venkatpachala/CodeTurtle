"""Project structured requirement runs into canonical evidence after finding gates."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from core.domain.observations import SourceObservation
from core.domain.review_contracts import EvidenceRecord, InvestigationRecord, RequirementAssessment
from core.intent.investigator import RequirementRun
from core.review.finding import ReviewFinding


@dataclass
class RequirementOutcome:
    assessments: list[RequirementAssessment] = field(default_factory=list)
    investigations: list[InvestigationRecord] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    observations: list[SourceObservation] = field(default_factory=list)


def adjudicate_requirements(runs: list[RequirementRun], findings: list[ReviewFinding]) -> RequirementOutcome:
    outcome = RequirementOutcome()
    observation_index = {obs.id: obs for run in runs for obs in run.observations}
    outcome.observations = list(observation_index.values())
    for run in runs:
        decision = run.verification
        linked = [finding for finding in findings if finding.hypothesis_id == run.id
                  and finding.kind == "defect" and finding.verification_status == "verified"]
        violated = run.status == "proposed_violation" and bool(linked)
        satisfied = run.status == "supported"
        if run.status == "proposed_violation" and not linked:
            run.status, run.reason = "unresolved", "proposed defect did not pass the existing finding gates"
        evidence_ids = []
        if violated or satisfied:
            for citation in decision.citations:
                observation = observation_index[citation.observation_id]
                eid = "ER-" + hashlib.sha256(f"{run.id}:{observation.id}".encode()).hexdigest()[:24]
                if eid in evidence_ids:
                    continue
                supports = (run.id, *(finding.id for finding in linked)) if violated else (run.requirement.id,)
                contradicts = (run.requirement.id,) if violated else (run.id,)
                outcome.evidence.append(EvidenceRecord(
                    id=eid, kind="contract", source_ref=f"{observation.path}:{observation.start_line}-{observation.end_line}",
                    content_hash=observation.excerpt_sha256, revision_sha=observation.revision_sha,
                    revision_side=observation.revision_side, observation_refs=(observation.id,),
                    supports_claim_refs=supports, contradicts_claim_refs=contradicts,
                    limitations=("Bounded source-level model assessment; no execution or formal proof.",
                                 f"Checked scope: {decision.checked_scope}"),
                ))
                evidence_ids.append(eid)
            for finding in linked:
                finding.evidence_ids.extend(eid for eid in evidence_ids if eid not in finding.evidence_ids)
            run.status = "confirmed" if violated else "supported"
        status = "violated" if violated else "verified" if satisfied else "unverified" if run.attempted else "not_assessed"
        reason = f"Bounded source assessment: {decision.checked_scope}; {decision.rationale}" if violated or satisfied else run.reason
        outcome.assessments.append(RequirementAssessment(
            requirement_id=run.requirement.id, status=status, evidence_refs=tuple(evidence_ids), reason=reason,
        ))
        outcome.investigations.append(InvestigationRecord(
            id=run.id, hypothesis=f"The change violates: {run.requirement.acceptance_criterion}",
            status="confirmed" if violated else "disproved" if satisfied else "error" if run.status == "error"
                   else "unresolved" if run.attempted else "planned",
            requirement_refs=(run.requirement.id,), claim_refs=tuple(finding.id for finding in linked),
            evidence_refs=tuple(evidence_ids), reason=reason,
        ))
    return outcome
