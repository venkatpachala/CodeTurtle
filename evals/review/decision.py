"""evals/review/decision.py — Final review decision evaluation.

Measures MERGE / COMMENT / REQUEST_CHANGES quality vs golden expected decisions.
Computes confusion matrix, per-class P/R/F1, Macro-F1.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DECISION_CLASSES = ["MERGE", "COMMENT", "REQUEST_CHANGES"]

# Map legacy decision strings to canonical
_CANON = {
    "MERGE": "MERGE",
    "APPROVE": "MERGE",
    "COMMENT": "COMMENT",
    "REQUEST_CHANGES": "REQUEST_CHANGES",
    "BLOCK": "REQUEST_CHANGES",
    "REJECT": "REQUEST_CHANGES",
}


def _canon(d: str) -> str:
    return _CANON.get((d or "").strip().upper(), "COMMENT")


@dataclass
class DecisionMetrics:
    """Aggregated decision quality metrics."""
    prs_evaluated: int = 0

    # Confusion matrix [gold_class][pred_class] = count
    confusion: Dict[str, Dict[str, int]] = field(
        default_factory=lambda: {c: defaultdict(int) for c in DECISION_CLASSES}
    )

    # Per-class precision/recall/F1
    per_class: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Macro-averaged F1
    macro_f1: float = 0.0

    # Accuracy
    accuracy: float = 0.0

    # Over-blocking rate: predicted REQUEST_CHANGES when gold was MERGE
    over_blocking_rate: float = 0.0

    # Under-blocking rate: predicted MERGE when gold was REQUEST_CHANGES
    under_blocking_rate: float = 0.0


def compute_decision_metrics(
    predictions: List[str],          # predicted decisions
    golden: List[str],               # gold decisions
) -> DecisionMetrics:
    """
    Compute decision quality metrics.

    Args:
        predictions: list of predicted decisions (MERGE / COMMENT / REQUEST_CHANGES)
        golden: list of gold expected decisions (same length)

    Returns:
        DecisionMetrics
    """
    assert len(predictions) == len(golden), "Length mismatch"
    m = DecisionMetrics(prs_evaluated=len(predictions))

    correct = 0
    over_block = 0
    under_block = 0

    for pred_raw, gold_raw in zip(predictions, golden):
        pred = _canon(pred_raw)
        gold = _canon(gold_raw)
        m.confusion[gold][pred] += 1
        if pred == gold:
            correct += 1
        if gold == "MERGE" and pred == "REQUEST_CHANGES":
            over_block += 1
        if gold == "REQUEST_CHANGES" and pred == "MERGE":
            under_block += 1

    m.accuracy = correct / len(predictions) if predictions else 0.0
    m.over_blocking_rate = over_block / len(predictions) if predictions else 0.0
    m.under_blocking_rate = under_block / len(predictions) if predictions else 0.0

    # Per-class P/R/F1
    macro_f1_sum = 0.0
    valid_classes = 0
    for cls in DECISION_CLASSES:
        tp = m.confusion[cls].get(cls, 0)
        fp = sum(m.confusion[other].get(cls, 0) for other in DECISION_CLASSES if other != cls)
        fn = sum(m.confusion[cls].get(other, 0) for other in DECISION_CLASSES if other != cls)

        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        support = sum(m.confusion[cls].values())

        m.per_class[cls] = {"precision": p, "recall": r, "f1": f1, "support": support}
        if support > 0:
            macro_f1_sum += f1
            valid_classes += 1

    m.macro_f1 = macro_f1_sum / valid_classes if valid_classes > 0 else 0.0

    return m
