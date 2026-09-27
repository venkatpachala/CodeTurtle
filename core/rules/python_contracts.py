"""Narrow AST proof of an introduced arithmetic exception, not a heuristic warning."""
from __future__ import annotations

import ast
import textwrap
from core.runtime.models import Candidate
from core.verification.diff_index import DiffIndex


def removed_zero_guard_candidates(index: DiffIndex, bundle_by_path: dict[str, str]) -> list[Candidate]:
    candidates = []
    for path in sorted(index.file_set()):
        if not path.endswith(".py") or path not in bundle_by_path:
            continue
        for hunk in index.hunks_for(path):
            rows = hunk.body.splitlines()
            old = textwrap.dedent("\n".join(row[1:] for row in rows if row.startswith((" ", "-"))))
            new = textwrap.dedent("\n".join(row[1:] for row in rows if row.startswith((" ", "+"))))
            try:
                before, after = ast.parse(old), ast.parse(new)
            except SyntaxError:
                continue
            if len(before.body) != 1 or len(after.body) != 1:
                continue
            prior, current = before.body[0], after.body[0]
            if not isinstance(prior, ast.FunctionDef) or not isinstance(current, ast.FunctionDef):
                continue
            if prior.name != current.name or current.decorator_list or len(prior.body) != 2 or len(current.body) != 1:
                continue
            guard, previous_return = prior.body
            returned = current.body[0]
            if not isinstance(guard, ast.If) or guard.orelse or len(guard.body) != 1:
                continue
            if not isinstance(returned, ast.Return) or ast.dump(returned, include_attributes=False) != ast.dump(previous_return, include_attributes=False):
                continue
            division = returned.value
            if not isinstance(division, ast.BinOp) or not isinstance(division.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                continue
            if not isinstance(division.left, ast.Name) or not isinstance(division.right, ast.Name):
                continue
            args = {a.arg for a in [*current.args.posonlyargs, *current.args.args]}
            if division.left.id not in args or division.right.id not in args:
                continue
            condition = guard.test
            if not (isinstance(condition, ast.Compare) and len(condition.ops) == 1 and isinstance(condition.ops[0], ast.Eq)
                    and isinstance(condition.left, ast.Name) and condition.left.id == division.right.id
                    and len(condition.comparators) == 1 and isinstance(condition.comparators[0], ast.Constant)
                    and condition.comparators[0].value == 0):
                continue
            guarded_return = guard.body[0]
            if not (isinstance(guarded_return, ast.Return) and isinstance(guarded_return.value, ast.Constant)):
                continue
            if ast.dump(prior.args) != ast.dump(current.args):
                continue
            snippet = ast.get_source_segment(new, returned)
            if not snippet:
                continue
            denominator = division.right.id
            candidates.append(Candidate(bundle_id=bundle_by_path[path], file=path, symbol=current.name,
                start_line=hunk.new_start + returned.lineno - 1, title=f"{current.name} now raises for a zero denominator",
                claim=f"Calling {current.name} with {denominator}=0 now raises ZeroDivisionError instead of returning {guarded_return.value.value!r}.",
                existing_code=snippet, invariant="Preserve the explicit zero-denominator return contract",
                violating_condition=f"Invoke {current.name} with {denominator}=0 and other numeric arguments set to 1",
                expected=f"Return {guarded_return.value.value!r}", actual="Raise ZeroDivisionError",
                execution_path=[current.name], evidence=[path], evidence_paths=[path], source="rule",
                severity="medium", confidence=1.0, hypothesis_id="rule:removed_zero_guard"))
    return candidates


def proves_removed_zero_guard(candidate: Candidate, index: DiffIndex) -> bool:
    return candidate.source == "rule" and any(
        other.file == candidate.file and other.symbol == candidate.symbol and other.existing_code == candidate.existing_code
        for other in removed_zero_guard_candidates(index, {candidate.file: candidate.bundle_id}))
