"""Compatibility imports for canonical intent-aware domain records.

Legacy v2.1 *_ids input names are accepted; new records use *_refs.
"""
from core.domain.review_contracts import (
    EvidenceRecord,
    IntentSource,
    InvestigationRecord,
    Requirement,
    RequirementAssessment,
    RequirementCoverage,
)

__all__ = [
    "EvidenceRecord", "IntentSource", "InvestigationRecord", "Requirement",
    "RequirementAssessment", "RequirementCoverage",
]
