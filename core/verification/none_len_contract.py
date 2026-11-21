"""Narrow BASE/HEAD contract for direct built-in len(None); no execution or LLM.

Only a single undecorated module function with one plain parameter is admitted.
All other cases return None, leaving normal verification responsible.
"""
from __future__ import annotations

import ast

from core.domain.finding_verification import FindingDecision
from core.domain.observations import SourceCitation, SourceObservation
from core.input.excerpts import lexical_dependencies
from core.runtime.models import Candidate

RULE_ID = "python-none-len-v1"


def _shape(observation: SourceObservation, symbol: str):
    if observation.status != "success" or observation.unresolved_dependencies:
        return None
    try:
        tree = ast.parse(observation.text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol]
    if len(functions) != 1:
        return None
    node = functions[0]
    args = node.args
    if (not isinstance(node, ast.FunctionDef) or node not in tree.body or node.decorator_list
            or len(args.args) != 1 or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
            or args.defaults or lexical_dependencies(tree, node, symbol)):
        return None
    parameter = args.args[0].arg
    # Annotations/default evaluation could introduce additional runtime behavior.
    if args.args[0].annotation is not None or node.returns is not None:
        return None
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)
    if len(body) not in {1, 2} or not isinstance(body[-1], ast.Return):
        return None
    operation = body[-1]
    call = operation.value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "len"
            and len(call.args) == 1 and isinstance(call.args[0], ast.Name) and call.args[0].id == parameter
            and not call.keywords):
        return None
    guard = None
    if len(body) == 2:
        guard = body[0]
        if not isinstance(guard, ast.If) or guard.orelse or len(guard.body) != 1:
            return None
        condition = guard.test
        if not (isinstance(condition, ast.Compare) and len(condition.ops) == len(condition.comparators) == 1
                and isinstance(condition.ops[0], ast.Is) and isinstance(condition.left, ast.Name)
                and condition.left.id == parameter and isinstance(condition.comparators[0], ast.Constant)
                and condition.comparators[0].value is None):
            return None
        returned = guard.body[0]
        if not (isinstance(returned, ast.Return) and isinstance(returned.value, ast.Constant)
                and type(returned.value.value) is int and returned.value.value == 0):
            return None
    return parameter, operation, guard


def _citation(observation: SourceObservation, node: ast.AST) -> SourceCitation:
    return SourceCitation(observation_id=observation.id,
        start_line=observation.start_line + node.lineno - 1,
        end_line=observation.start_line + node.end_lineno - 1,
        quote="\n".join(observation.text.splitlines()[node.lineno-1:node.end_lineno]))


def verify_none_len(candidate: Candidate, observations: tuple[SourceObservation, ...]) -> FindingDecision | None:
    # "Error" is the proposal protocol's generic raised-error description. A
    # proven TypeError entails it; a different named exception does not qualify.
    if not candidate.file.endswith(".py") or candidate.expected.strip() != "0" or candidate.actual.strip() not in {"TypeError", "Error"}:
        return None
    head = next((o for o in observations if o.path == candidate.file and o.revision_side == "head"), None)
    base = next((o for o in observations if o.path == candidate.file and o.revision_side == "base"), None)
    if head is None:
        return None
    after = _shape(head, candidate.symbol)
    if after is None:
        return None
    parameter, operation, guard = after
    if candidate.violating_condition.strip() not in {f"{parameter} is None", f"{candidate.symbol}(None)"}:
        return None
    operation_citation = _citation(head, operation)
    if candidate.existing_code.strip() != operation_citation.quote.strip():
        return None
    common = dict(checked_trigger=candidate.violating_condition.strip(), missing_evidence=())
    if guard is not None:
        return FindingDecision(**common, verdict="refuted", refutation_basis="head_guard",
            rationale="The complete HEAD function returns zero for None before reaching len.",
            path_analysis=f"Direct {candidate.symbol}(None) takes the HEAD None guard and returns 0.",
            supporting_citations=(), counter_citations=(_citation(head, guard),))
    before = _shape(base, candidate.symbol) if base is not None else None
    if before is None or before[0] != parameter:
        return None
    if before[2] is not None:
        return FindingDecision(**common, verdict="supported", refutation_basis="none",
            rationale="BASE returned zero for None; HEAD directly evaluates the unshadowed built-in len(None), raising TypeError.",
            path_analysis=f"Direct {candidate.symbol}(None): BASE returns 0 through its guard; HEAD reaches len(None).",
            supporting_citations=(operation_citation, _citation(base, before[2])), counter_citations=())
    return FindingDecision(**common, verdict="refuted", refutation_basis="preexisting_failure",
        rationale="The same direct len(None) failure exists in BASE and HEAD; it was not introduced by this change.",
        path_analysis=f"Direct {candidate.symbol}(None) reaches len(None) in both captured revisions.",
        supporting_citations=(_citation(base, before[1]),), counter_citations=(operation_citation,))
