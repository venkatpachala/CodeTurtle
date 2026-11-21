"""V4 review orchestrator. LangGraph is not on this path."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import hashlib
import subprocess
from core.review.contract import ReviewTarget, ReviewHealth, StageOutcome, evaluate_policy
from core.review.inspection import collect_inspection, unresolved_hypotheses
from core.review.budget import ReviewBudget

from core.agent.contract import classify_kind, proof_complete
from core.bundling.builder import BundleBuilder
from core.change_units import attach_change_units, build_change_units
from core.graphctx.symbols import is_valid_symbol, symbols_from_units
from core.positioner import position_candidate
from core.pr_facts import build_pr_facts, normalize_path
from core.reflector import reflect_candidate
from core.review.finding import ReviewFinding
from core.review.trace import (
    PipelineTrace,
    STAGE_CLASSIFY,
    STAGE_PROOF,
    STAGE_REFLECTOR,
    STAGE_POSITIONER,
    STAGE_VERIFIER,
    STAGE_FINAL,
)
from core.review.timing import TimingRecord, timed
from core.runtime.models import Bundle, Candidate, Comment, ReviewResult, comment_from_candidate
from core.verification.diff_index import DiffIndex, build_diff_index
from core.verification.execute import is_pytest_file
from core.verification.policy import coverage_score, decide


def _coverage_from_units(all_units: List[Any], bundles: List[Bundle]) -> Dict[str, Any]:
    packed_ids = set()
    packed_n = 0
    for b in bundles:
        for u in b.units or []:
            uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)
            if uid is not None:
                if uid in packed_ids:
                    continue
                packed_ids.add(uid)
            packed_n += 1
    source_n = 0
    for u in all_units:
        kind = u.get("kind") if isinstance(u, dict) else getattr(u, "kind", "")
        if kind == "source":
            source_n += 1
    total = len(all_units)
    packed = len(packed_ids) if packed_ids else packed_n
    return {
        "units_total": total,
        "units_packed": packed,
        "units_omitted": max(0, total - packed),
        "source_units": source_n,
    }


def _finding_from_comment(c: Comment) -> Dict[str, Any]:
    return {
        "title": c.title,
        "claim": c.claim,
        "file": c.file,
        "symbol": c.symbol,
        "start_line": c.line or c.start_line,
        "severity": c.severity,
        "verification_status": c.verification or "supported",
        "evidence": list(c.evidence_paths or []),
        "source": c.source,
        "bundle_id": c.bundle_id,
        "kind": str(getattr(c, "kind", "") or "defect"),
        "tests_run": bool(getattr(c, "tests_run", False)),
        "existing_code": str(getattr(c, "existing_code", "") or ""),
        "invariant": str(getattr(c, "invariant", "") or ""),
        "violating_condition": str(getattr(c, "violating_condition", "") or ""),
        "expected": str(getattr(c, "expected", "") or ""),
        "actual": str(getattr(c, "actual", "") or ""),
        "execution_path": list(getattr(c, "execution_path", None) or []),
        "evidence": list(getattr(c, "evidence", None) or []),
        "counter_evidence": list(getattr(c, "counter_evidence", None) or []),
        "verify_status": str(getattr(c, "verify_status", "") or "candidate"),
        "confidence": float(getattr(c, "confidence", 0.5) or 0.5),
    }


def _bundle_test_paths(bundles: List[Bundle]) -> List[str]:
    out: List[str] = []
    for b in bundles:
        for p in b.paths or []:
            n = normalize_path(p)
            if is_pytest_file(n) and n not in out:
                out.append(n)
    return out


def _log_sandbox(execution: Dict[str, Any]) -> None:
    rec = execution or {}
    if rec.get("skipped"):
        print(f"[Sandbox] skip reason={rec.get('skip_reason') or 'flag_off'}")
        return
    print(
        f"[Sandbox] cmd={rec.get('cmd')} exit={rec.get('exit_code')} "
        f"passed={rec.get('passed')} failed={rec.get('failed')}"
    )


def result_to_review_state(result: ReviewResult, context: Any = None) -> Dict[str, Any]:
    """Map ReviewResult onto the existing display / github_review state shape."""
    ctx = context
    facts = dict(getattr(ctx, "pr_facts", None) or {})
    files = list(getattr(ctx, "files_changed", None) or facts.get("files_changed") or [])
    # Findings are canonical; the legacy dictionaries remain only for callers
    # that have not yet migrated off ``validated_findings``.
    findings = [f.to_dict() for f in (getattr(result, "findings", None) or [])]
    pr = getattr(ctx, "pr", None)
    title = ""
    body = ""
    author = ""
    if pr is not None:
        title = str(getattr(pr, "title", "") or "")
        body = str(getattr(pr, "body", "") or "")
        user = getattr(pr, "user", None)
        author = str(getattr(user, "login", "") or "") if user is not None else ""
    if not title:
        title = str(facts.get("title") or "")
    units_payload = dict(getattr(ctx, "change_units_payload", None) or {})
    repo_cfg = getattr(ctx, "repo_cfg", None)
    summary_bits = [f"**{result.decision}** ({result.policy_reason})"]
    if findings:
        summary_bits.append(f"{len(findings)} kept comment(s).")
    else:
        summary_bits.append("No validated findings.")
    summary = " ".join(summary_bits)
    cov = dict(result.coverage or {})
    packed = int(cov.get("units_packed") or 0)
    total = int(cov.get("units_total") or 0)
    classif = str(facts.get("classification") or "")
    ratio, low = coverage_score(
        cov, classification=classif, files_changed=files
    )
    state: Dict[str, Any] = {
        "repo": getattr(ctx, "repo", "") or facts.get("repo") or "",
        "number": getattr(ctx, "number", 0) or facts.get("pr_number") or 0,
        "title": title,
        "body": body,
        "author": author,
        "full_diff": getattr(ctx, "full_diff", "") or "",
        "files_changed": files,
        "pr_facts": facts,
        "pr_head_sha": getattr(ctx, "pr_head_sha", "") or "",
        "recommendation": result.decision,
        "policy_reason": result.policy_reason,
        "validated_findings": findings,
        "findings": findings,
        "review_coverage": cov,
        "coverage_ratio": ratio,
        "coverage_low": low,
        "final_comment": summary,
        "merge_decision": {
            "recommendation": result.decision,
            "policy_reason": result.policy_reason,
            "summary": summary,
            "blocking_issues": [
                f.get("title")
                for f in findings
                if str(f.get("severity") or "").lower()
                in ("medium", "concern", "high", "critical", "blocking")
            ],
        },
        "v4_bundles": [b.to_dict() for b in result.bundles],
        "v4_dropped": list(result.dropped),
        "inline_max": int(getattr(repo_cfg, "inline_max", 8) or 8) if repo_cfg is not None else 8,
        "inline_lockfile": bool(getattr(repo_cfg, "inline_lockfile", False)) if repo_cfg else False,
        "coverage_merge_min": float(getattr(repo_cfg, "coverage_merge_min", 0.5) or 0.5)
        if repo_cfg is not None
        else 0.5,
        "ignore_paths": list(getattr(repo_cfg, "ignore_paths", None) or []) if repo_cfg else [],
        "runtime": "v4",
        "_review_result": result,
        "execution_report": dict(result.execution or {}),
        "pipeline_trace": (
            result.pipeline_trace.to_list()
            if getattr(result, "pipeline_trace", None) is not None
            and hasattr(result.pipeline_trace, "to_list") else []
        ),
        "timing": (
            result.timing.to_dict()
            if getattr(result, "timing", None) is not None
            and hasattr(result.timing, "to_dict") else {}
        ),
        "agent_runs": list(getattr(result, "agent_runs", None) or []),
        "pipeline_health": dict(getattr(result, "pipeline_health", None) or {}),
        "execute_tests": bool(getattr(ctx, "execute_tests", False)),
        "execute_install": bool(getattr(ctx, "execute_install", False)),
    }
    state.update(units_payload)
    state["review_coverage"] = cov
    state["coverage_ratio"] = ratio
    state["coverage_low"] = low
    state["recommendation"] = result.decision
    state["policy_reason"] = result.policy_reason
    state["validated_findings"] = findings
    state["findings"] = findings
    return state


class ReviewRuntime:
    """intake facts/units → bundles → BundleAgent → Positioner → Reflector → Policy."""

    def __init__(
        self,
        *,
        llm: Optional[Callable[[str], str]] = None,
        verification_llm: Optional[Callable[[str], str]] = None,
        requirement_llm: Optional[Callable[[str, str], str]] = None,
        finding_verification_llm: Optional[Callable[[str], str]] = None,
        finding_verifier_mode: str = "structured",
        finding_source_rules: bool = True,
        graphify_client: Any = None,
        rule_engine: Optional[Callable[..., List[Candidate]]] = None,
        agent: Any = None,
    ):
        self.llm = llm
        # Kept separate because verification uses a tiny classification call,
        # while BundleAgent requires a much larger completion budget.
        self.verification_llm = verification_llm
        self.requirement_llm = requirement_llm
        if finding_verifier_mode not in {"structured", "legacy"}:
            raise ValueError("unknown finding verifier mode")
        self.finding_verification_llm = finding_verification_llm
        self.finding_verifier_mode = finding_verifier_mode
        self.finding_source_rules = finding_source_rules
        self.graphify_client = graphify_client
        self.rule_engine = rule_engine
        self.agent = agent
        self.stage_errors: List[StageOutcome] = []
        self.budget = ReviewBudget()
        self.verification_usage: List[Dict[str, Any]] = []

    def _verify_completion(self, prompt: str) -> str:
        from core.gateway.gateway import AIGateway
        try:
            self.budget.reserve(prompt)
            response = AIGateway().generate(prompt=prompt, capability="correctness_review",
                agent_name="FindingVerifier", temperature=0.0, max_tokens=96, retries=1)
            self.verification_usage.append(response.telemetry.model_dump(mode="json"))
            return str(response.content or "")
        except Exception:
            self.stage_errors.append(StageOutcome(stage="verification", status="failed", code="model_call_failed"))
            raise

    def _client(self, repo: str) -> Any:
        if self.graphify_client is not None:
            return self.graphify_client
        if not repo:
            return None
        try:
            from config import settings
            if not settings.graphify_enabled:
                return None
            from core.workspace import graph_is_stale, _run_default
            from core.repository_knowledge.paths import resolve_repo_dir, resolve_graph_path
            if graph_is_stale(resolve_repo_dir(repo), resolve_graph_path(repo), _run_default):
                return None
            from core.repository_knowledge.structural import get_provider_if_available

            return get_provider_if_available(repo)
        except Exception:
            return None

    def _rules(
        self,
        bundles: List[Bundle],
        files_changed: List[str],
        *,
        full_diff: str = "",
        repo_dir: str = "",
    ) -> List[Candidate]:
        fn = self.rule_engine
        if fn is None:
            try:
                from core.rules.engine import run_rule_engine

                fn = run_rule_engine
            except Exception:
                self.stage_errors.append(StageOutcome(stage="rules", status="failed", code="rule_import_failed"))
                return []
        try:
            return list(
                fn(
                    bundles,
                    files_changed=files_changed,
                    full_diff=full_diff,
                    repo_dir=repo_dir or None,
                )
                or []
            )
        except TypeError:
            try:
                return list(fn(bundles, files_changed=files_changed) or [])
            except TypeError:
                try:
                    return list(fn(bundles) or [])
                except Exception:
                    self.stage_errors.append(StageOutcome(stage="rules", status="failed", code="rule_execution_failed"))
                    return []
        except Exception:
            self.stage_errors.append(StageOutcome(stage="rules", status="failed", code="rule_execution_failed"))
            return []

    def _agent_candidates(self, bundle: Bundle, tools: Any) -> tuple[List[Candidate], Dict[str, Any]]:
        agent = self.agent
        if agent is None:
            from core.agent.bundle_agent import BundleAgent

            agent = BundleAgent(llm=self.llm)
        try:
            if hasattr(agent, "run_result"):
                result = agent.run_result(bundle, tools)
                record = result.to_dict() if hasattr(result, "to_dict") else dict(result)
                record["bundle_id"] = bundle.id
                return list(getattr(result, "candidates", []) or []), record
            candidates = list(agent.run(bundle, tools) or [])
            return candidates, {"bundle_id": bundle.id, "status": "LEGACY", "candidate_count": len(candidates)}
        except Exception as exc:
            return [], {"bundle_id": bundle.id, "status": "EXCEPTION", "candidate_count": 0,
                        "exception": f"{type(exc).__name__}: {exc}"}

    def run(
        self,
        context: Any = None,
        *,
        files_changed: Optional[List[str]] = None,
        full_diff: str = "",
        pr_facts: Optional[dict] = None,
        change_units: Optional[List[Any]] = None,
        repo: str = "",
        classification: str = "",
    ) -> ReviewResult:
        self.stage_errors = []
        self.budget = ReviewBudget()
        self.verification_usage = []
        if self.agent is not None and hasattr(self.agent, "usage_records"):
            self.agent.usage_records = []
        ctx = context
        static_only = getattr(ctx, "analysis_mode", "model") == "static_only"
        snapshot = getattr(ctx, "review_snapshot", None)
        input_provider = getattr(ctx, "input_provider", None)
        files = list(
            files_changed
            or getattr(ctx, "files_changed", None)
            or []
        )
        files = [normalize_path(p) for p in files if p]
        diff = full_diff or getattr(ctx, "full_diff", "") or ""
        pr_snapshot = getattr(ctx, "pr_review_snapshot", None)
        pr_inputs = getattr(ctx, "pr_input_provider", None)
        prepared_pr = getattr(ctx, "source_preparation", None) is not None
        if pr_snapshot is not None:
            from core.input.snapshot import InputError
            preparation = getattr(ctx, "source_preparation", None) or {}
            if (pr_inputs is None or pr_snapshot.base_sha != getattr(ctx, "pr_base_sha", "")
                    or pr_snapshot.head_sha != getattr(ctx, "pr_head_sha", "")
                    or preparation.get("review_diff_sha256") != hashlib.sha256(diff.encode()).hexdigest()):
                raise InputError("prepared PR source differs from runtime review identity")
        investigation_snapshot = snapshot or pr_snapshot
        investigation_inputs = input_provider or pr_inputs
        if prepared_pr and pr_snapshot is None:
            self.stage_errors.append(StageOutcome(stage="investigation_context", status="degraded", code="snapshot_unavailable"))
        if snapshot is not None:
            from core.input.snapshot import InputError
            if input_provider is None or input_provider.diff(snapshot) != diff:
                raise InputError("runtime input does not match the sealed snapshot")
            if (getattr(ctx, "pr_head_sha", "") != snapshot.head_sha
                    or getattr(ctx, "pr_base_sha", "") != snapshot.base_sha):
                raise InputError("runtime revision identity does not match the sealed snapshot")
            if getattr(ctx, "execute_tests", False):
                raise InputError("snapshot review does not execute repository code")
        facts = dict(pr_facts or getattr(ctx, "pr_facts", None) or {})
        if not facts:
            facts = build_pr_facts(
                title=str(facts.get("title") or ""),
                files_changed=files,
                full_diff=diff,
                repo=repo or getattr(ctx, "repo", "") or "",
                pr_number=getattr(ctx, "number", None),
            )
        if not files:
            files = [normalize_path(p) for p in (facts.get("files_changed") or []) if p]
        classif = classification or str(facts.get("classification") or "")
        index: DiffIndex = build_diff_index(diff)

        payload = getattr(ctx, "change_units_payload", None) if ctx is not None else None
        units = list(change_units or [])
        if not units and isinstance(payload, dict) and payload.get("change_units") is not None:
            units = list(payload.get("change_units") or [])
        if not units:
            units = build_change_units(diff, files, index=index)
            if ctx is not None:
                try:
                    ctx.change_units_payload = attach_change_units(
                        {
                            "full_diff": diff,
                            "files_changed": files,
                            "pr_facts": facts,
                        }
                    )
                except Exception:
                    pass

        cfg = getattr(ctx, "repo_cfg", None) if ctx is not None else None
        try:
            from config import settings as _settings

            bundle_max = int(
                getattr(cfg, "bundle_max", None)
                or getattr(_settings, "bundle_max", 4)
                or 4
            )
            agent_steps = int(
                getattr(cfg, "agent_max_steps", None)
                or getattr(_settings, "agent_max_steps", 4)
                or 4
            )
        except Exception:
            bundle_max, agent_steps = 4, 4
        bundles = BundleBuilder().build(
            files_changed=files,
            units=units,
            classification=classif,
            max_bundles=bundle_max,
        )
        intent = getattr(ctx, "review_intent", None)
        requirement_strategy = getattr(ctx, "requirement_strategy", "investigate" if snapshot is not None else "link")
        if requirement_strategy not in {"investigate", "link", "off"}:
            raise ValueError("unknown requirement strategy")
        if intent is not None and requirement_strategy != "off":
            for bundle in bundles:
                bundle.requirements = intent.for_paths(bundle.paths)
        semantic_context = None
        if investigation_snapshot is not None:
            from core.intelligence.changes import build_change_context
            semantic_context = build_change_context(investigation_inputs, investigation_snapshot, files)
            for bundle in bundles:
                bundle.change_context = {
                    "snapshot_id": investigation_snapshot.id,
                    "changes": [change.model_dump() for change in semantic_context.changes if change.path in bundle.paths],
                    "limitations": list(semantic_context.limitations),
                    "unresolved_context": list(semantic_context.unresolved_context),
                }
        repo_name = repo or getattr(ctx, "repo", "") or str(facts.get("repo") or "")
        client = self._client(repo_name)
        if investigation_snapshot is not None or prepared_pr:
            client = None  # No graph may establish facts without matching snapshot provenance.
        repo_dir = str(getattr(ctx, "repo_dir", "") or "")
        if not repo_dir and repo_name:
            try:
                from core.repository_knowledge.paths import resolve_repo_dir

                repo_dir = str(resolve_repo_dir(repo_name))
            except Exception:
                repo_dir = ""

        from core.analysis.risk_signals import (
            analyze_risk_signals, attach_signals_to_bundles, attach_signals_to_candidates,
        )
        risk_signals = []
        if investigation_snapshot is not None and snapshot is None:
            from core.input.snapshot import InputError, SourceNotFound
            def read_pinned_source(path: str) -> str:
                try:
                    return investigation_inputs.read(investigation_snapshot, path).content.decode("utf-8", errors="strict")
                except SourceNotFound:
                    return ""  # Deleted files have no HEAD definitions.
            try:
                risk_signals = analyze_risk_signals(repo_dir=None, files_changed=files, index=index,
                    read_source=read_pinned_source, repository_paths=investigation_inputs.paths(investigation_snapshot))
            except (InputError, UnicodeError):
                self.stage_errors.append(StageOutcome(stage="risk_context", status="degraded", code="snapshot_read_unavailable"))
        elif snapshot is None and not prepared_pr:
            risk_signals = analyze_risk_signals(repo_dir=repo_dir, files_changed=files, index=index)
        attach_signals_to_bundles(bundles, risk_signals)
        if risk_signals:
            print(f"[RiskSignals] n={len(risk_signals)} kinds={[signal.kind for signal in risk_signals]}")

        from core.agent.tools import BundleTools
        from core.agent.bundle_agent import BundleAgent

        if self.agent is None:
            self.agent = BundleAgent(llm=self.llm, max_steps=agent_steps)
        if isinstance(self.agent, BundleAgent):
            self.agent.budget = self.budget

        trace = PipelineTrace()
        timing = TimingRecord()

        candidates: List[Candidate] = []
        agent_runs: List[Dict[str, Any]] = []
        from config import settings
        if settings.rules_enabled:
            if (investigation_snapshot is not None or prepared_pr) and self.rule_engine is None:
                from core.rules.engine import run_rule_engine
                candidates.extend(run_rule_engine(bundles, files_changed=files, full_diff=diff,
                                                 allow_checkout_tools=False))
            else:
                candidates.extend(self._rules(bundles, files, full_diff=diff, repo_dir=repo_dir))
        else:
            self.stage_errors.append(StageOutcome(stage="rules", status="skipped", code="ablation_disabled"))
        for bundle in bundles:
            bundle.symbols = [
                s
                for s in (symbols_from_units(bundle.units, bundle.paths) or list(bundle.symbols))
                if is_valid_symbol(s)
            ]
            tools = BundleTools(bundle, index=index, client=client,
                                repo_dir=None if prepared_pr else repo_dir or None)
            if investigation_snapshot is not None:
                from core.input.tools import SnapshotBundleTools
                tools = SnapshotBundleTools(bundle, index=index, provider=investigation_inputs, snapshot=investigation_snapshot)
            with timed(timing, "bundle_agent"):
                if static_only:
                    bundle_candidates, agent_record = [], {"bundle_id": bundle.id, "status": "VALID_EMPTY",
                        "assessments": [], "model_calls": 0, "stage_status": {"discovery": "SKIPPED_STATIC_ONLY"}}
                else:
                    bundle_candidates, agent_record = self._agent_candidates(bundle, tools)
                candidates.extend(bundle_candidates)
                agent_runs.append(agent_record)

        requirement_runs = []
        if intent is not None and snapshot is not None and requirement_strategy != "link":
            from core.intent.investigator import RequirementInvestigator
            def complete_requirement_stage(stage: str, prompt: str) -> str:
                if self.requirement_llm is not None:
                    return str(self.requirement_llm(stage, prompt))
                injected = (self.verification_llm or self.llm) if stage == "verify" else self.llm
                if injected is not None:
                    return str(injected(prompt))
                from core.gateway.gateway import AIGateway
                response = AIGateway().generate(prompt=prompt, capability="correctness_review",
                    agent_name=f"Requirement:{stage}", temperature=0.0, max_tokens=1400, retries=0)
                self.verification_usage.append(response.telemetry.model_dump(mode="json"))
                return str(response.content or "")
            requirement_runs = RequirementInvestigator(complete_requirement_stage, self.budget,
                max_requirements=int(getattr(ctx, "max_requirements", 8))).run(
                    intent, input_provider, snapshot, files,
                    enabled=requirement_strategy == "investigate" and getattr(ctx, "analysis_mode", "model") != "static_only")
            for run in requirement_runs:
                if run.candidate is not None:
                    owner = next((bundle for bundle in bundles if run.candidate.file in bundle.paths), None)
                    if owner is not None:
                        run.candidate.bundle_id = owner.id
                        candidates.append(run.candidate)
                    else:
                        run.status, run.reason = "unresolved", "scoped candidate omitted from scheduled bundles"
        attach_signals_to_candidates(candidates, risk_signals, index)

        comments: List[Comment] = []
        dropped: List[Dict[str, Any]] = []
        survivors: List[tuple] = []
        for cand in candidates:
            cid = trace.next_candidate_id()
            cand.candidate_id = cid
            # Store candidate_id on the candidate for later correlation
            try:
                object.__setattr__(cand, "_candidate_id", cid)
            except Exception:
                pass

            kind = classify_kind(cand.title, cand.claim, getattr(cand, "kind", None))
            cand.kind = kind
            if kind != "defect":
                dropped.append({**cand.to_dict(), "drop_reason": "note"})
                trace.drop(cid, STAGE_CLASSIFY, "note", cand)
                print(
                    f"[Reflector] DROP reason=note file={cand.file} title={cand.title!r}"
                )
                continue
            with timed(timing, "reflect"):
                if not proof_complete(cand.to_dict()):
                    dropped.append({**cand.to_dict(), "drop_reason": "incomplete_proof"})
                    trace.drop(cid, STAGE_PROOF, "incomplete_proof", cand)
                    print(
                        f"[Reflector] DROP reason=incomplete_proof file={cand.file} title={cand.title!r}"
                    )
                    continue
                line = position_candidate(cand, index)
                own_paths = next(
                    (list(b.paths or []) for b in bundles if b.id == cand.bundle_id),
                    None,
                )
                keep, reason = reflect_candidate(
                    cand,
                    files_changed=files,
                    index=index,
                    line=line,
                    bundle_paths=own_paths,
                    allow_summary_only=True,
                )
                if not keep:
                    drop_r = reason
                    dropped.append({**cand.to_dict(), "drop_reason": drop_r})
                    stage = STAGE_POSITIONER if (not line) else STAGE_REFLECTOR
                    trace.drop(cid, stage, drop_r, cand)
                    continue
            trace.keep(cid, STAGE_REFLECTOR, cand, line)
            survivors.append((cand, line))

        from core.runtime.verify_loop import verify_candidates
        from core.verification.source_verifier import SourceFindingVerifier, FINDING_PROMPT_VERSION

        verification_inputs = input_provider or getattr(ctx, "pr_input_provider", None)
        verification_snapshot = snapshot or getattr(ctx, "pr_review_snapshot", None)
        if snapshot is None and verification_snapshot is not None:
            from core.input.snapshot import InputError
            preparation = getattr(ctx, "source_preparation", None) or {}
            if (verification_snapshot.base_sha != getattr(ctx, "pr_base_sha", "")
                    or verification_snapshot.head_sha != getattr(ctx, "pr_head_sha", "")
                    or preparation.get("review_diff_sha256") != hashlib.sha256(diff.encode()).hexdigest()):
                raise InputError("prepared PR source differs from runtime review identity")
        if verification_snapshot is None and self.finding_verifier_mode == "structured" and repo_dir:
            try:
                from core.input.snapshot import GitSnapshotProvider
                base_sha, head_sha = str(getattr(ctx, "pr_base_sha", "") or ""), str(getattr(ctx, "pr_head_sha", "") or "")
                if not base_sha or not head_sha:
                    raise ValueError("missing pinned source revisions")
                verification_inputs = GitSnapshotProvider(repo_dir)
                verification_snapshot = verification_inputs.resolve(base_sha, head_sha, comparison="merge_base",
                    config={"prompt_version": FINDING_PROMPT_VERSION, "review_diff_sha256": hashlib.sha256(diff.encode()).hexdigest()})
            except Exception:
                verification_inputs, verification_snapshot = None, None
                self.stage_errors.append(StageOutcome(stage="verification_context", status="degraded", code="snapshot_unavailable"))

        finding_generation_metadata: dict = {}
        def structured_completion(prompt: str) -> str:
            finding_generation_metadata.clear()
            if static_only:
                raise RuntimeError("model verification disabled in static-only mode")
            injected = self.finding_verification_llm or self.verification_llm or self.llm
            if injected is not None:
                return str(injected(prompt))
            from core.gateway.gateway import AIGateway
            from core.domain.finding_verification import FindingDecision
            response = AIGateway().generate(prompt=prompt, capability="correctness_review",
                agent_name="FindingVerifier:structured", temperature=0.0, max_tokens=1400, retries=0,
                response_schema=FindingDecision)
            finding_generation_metadata.update(response.telemetry.model_dump(mode="json"))
            self.verification_usage.append(response.telemetry.model_dump(mode="json"))
            return str(response.content or "")

        def finding_context_paths(candidate: Candidate, bundle: Bundle | None) -> tuple[str, ...]:
            context_paths = []
            if intent is not None:
                for item in intent.items:
                    if candidate.file in item.paths:
                        context_paths.extend(item.context_paths)
            return tuple(context_paths)

        source_verifier = SourceFindingVerifier(verification_inputs, verification_snapshot,
            structured_completion, self.budget, finding_context_paths, lambda: finding_generation_metadata,
            source_rules=self.finding_source_rules and not static_only)

        def verify_completion(prompt: str) -> str:
            if static_only:
                return "UNCERTAIN"
            injected = self.verification_llm or self.llm
            if injected is not None:
                self.budget.reserve(prompt)
                return str(injected(prompt))
            return self._verify_completion(prompt)

        with timed(timing, "verify"):
            if settings.verification_enabled:
                verified_cands, vdrop = verify_candidates(
                    [c for c, _ in survivors], index=index, bundles=bundles, client=client,
                    llm=verify_completion,
                    source_verifier=(lambda candidate, bundle, hints: "UNCERTAIN" if static_only
                                     else source_verifier.verify(candidate, bundle, hints))
                                    if self.finding_verifier_mode == "structured" else None)
            else:
                verified_cands, vdrop = [], [{**c.to_dict(), "drop_reason": "verification_disabled"} for c, _ in survivors]
                self.stage_errors.append(StageOutcome(stage="verification", status="skipped", code="ablation_disabled"))
        # Record verifier drops with trace
        for vd in vdrop:
            dr = vd.get("drop_reason", "verifier_drop") if isinstance(vd, dict) else "verifier_drop"
            file_ = vd.get("file", "") if isinstance(vd, dict) else ""
            title_ = vd.get("title", "") if isinstance(vd, dict) else ""
            # Best-effort: match by file+title to candidate_id
            matching_cid = next(
                (
                    getattr(c, "_candidate_id", "?")
                    for c, _ in survivors
                    if getattr(c, "file", "") == file_ and getattr(c, "title", "") == title_
                ),
                "?",
            )
            trace.record(matching_cid, STAGE_VERIFIER, "dropped", file=file_, title=title_, drop_reason=dr)
        dropped.extend(vdrop)

        line_by_id = {id(c): ln for c, ln in survivors}
        comments = []
        review_findings: List[ReviewFinding] = []
        finding_counter = 0
        for cand in verified_cands:
            ln = position_candidate(cand, index)
            if ln is None:
                ln = line_by_id.get(id(cand))
            # Build canonical Comment (backward compat)
            comments.append(comment_from_candidate(cand, int(ln or 0)))
            # Build canonical ReviewFinding (new path)
            finding_counter += 1
            fid = f"F-{finding_counter:03d}"
            cid = getattr(cand, "_candidate_id", "?")
            rf = ReviewFinding.from_candidate_and_comment(cand, int(ln or 0), finding_id=fid, candidate_id=cid)
            trace.keep(cid, STAGE_FINAL, cand, ln)
            review_findings.append(rf)

        coverage = _coverage_from_units(units, bundles)
        findings = [_finding_from_comment(c) for c in comments]
        bundle_tests = _bundle_test_paths(bundles)

        # Attach related tests to both legacy dict and ReviewFinding
        for f in findings:
            related = [
                p
                for b in bundles
                if normalize_path(str(f.get("file") or "")) in [
                    normalize_path(x) for x in b.paths
                ]
                for p in b.paths
                if is_pytest_file(p)
            ]
            f["related_tests"] = related
        for rf in review_findings:
            rf.related_tests = [
                p
                for b in bundles
                if normalize_path(rf.file) in [normalize_path(x) for x in b.paths]
                for p in b.paths
                if is_pytest_file(p)
            ]

        exec_state = {
            "execute_tests": bool(getattr(ctx, "execute_tests", False)) if ctx is not None else False,
            "execute_install": bool(getattr(ctx, "execute_install", False)) if ctx is not None else False,
            "pr_facts": facts,
            "files_changed": files,
            "validated_findings": findings,
            "findings": findings,
            "sandbox_test_paths": bundle_tests,
            "repo": repo_name,
            "pr_head_sha": str(getattr(ctx, "pr_head_sha", "") or "") if ctx is not None else "",
            "number": getattr(ctx, "number", 0) if ctx is not None else 0,
        }
        from core.verification.execute import execute_tests_node

        with timed(timing, "sandbox"):
            try:
                ex_out = execute_tests_node(exec_state)
            except Exception:
                ex_out = {
                    "execution_report": {
                        "skipped": True,
                        "skip_reason": "checkout_failed",
                    }
                }
        execution = dict(ex_out.get("execution_report") or {})
        if ex_out.get("validated_findings"):
            findings = list(ex_out.get("validated_findings") or findings)
        # Execution is evidence, never a finding filter.  In particular, a
        # green suite does not disprove a missing-test or behavioural finding.
        from core.review.finding import ExecutionEvidence
        evidence = _execution_evidence(execution)
        for rf in review_findings:
            rf.execution = evidence
            trace.keep(rf.candidate_id or "?", "sandbox", None, rf.line)
        for comment in comments:
            comment.tests_run = evidence.status not in ("NOT_RUN", "SKIPPED")
        _log_sandbox(execution)

        healthy_statuses = {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}
        unhealthy = [r for r in agent_runs if r.get("status") not in healthy_statuses]
        ratio, low = coverage_score(
            coverage, classification=classif, files_changed=files
        )
        pipeline_health = {
            "healthy": not unhealthy,
            "agent_runs": len(agent_runs),
            "unhealthy_runs": len(unhealthy),
            "unhealthy_statuses": [str(r.get("status")) for r in unhealthy],
            "coverage_ratio": ratio,
            "coverage_adequate": not low,
        }
        inspection = collect_inspection(units, bundles, agent_runs)
        unresolved = unresolved_hypotheses(agent_runs, candidates, dropped)
        all_failed = bool(agent_runs) and len(unhealthy) == len(agent_runs)
        health = ReviewHealth(status="failed" if all_failed else "partial" if unhealthy else "completed",
            stages=[StageOutcome(stage=f"bundle:{r['bundle_id']}", status="failed" if r in unhealthy else "succeeded",
                                 code=str(r.get("status"))) for r in agent_runs])
        health.stages.extend(self.stage_errors)
        if self.stage_errors and health.status == "completed":
            health.status = "partial"
        if client is None and inspection.eligible:
            health.stages.append(StageOutcome(stage="graph", status="degraded", code="graph_unavailable"))
            # A local bounded source search is useful, but not equivalent to
            # complete cross-file structural context.
            if len([p for p in files if p.endswith(".py")]) > 1 and health.status == "completed":
                health.status = "partial"
        intake_omissions = list(getattr(ctx, "intake_omissions", []) or [])
        if intake_omissions and health.status == "completed":
            health.status = "partial"
        unresolved.extend(intake_omissions)
        if semantic_context is not None:
            unresolved.extend({"reason": reason, "stage": "semantic_context"}
                              for reason in semantic_context.unresolved_context)
        for run in agent_runs:
            for call in run.get("tool_calls") or []:
                observation = call.get("result") or {}
                if observation.get("truncated") or observation.get("error"):
                    unresolved.append({"stage": "tool_context", "bundle_id": run.get("bundle_id"),
                                       "reason": "incomplete_tool_observation"})
        requirement_assessments, requirement_investigations, requirement_evidence = [], [], []
        source_observations = []
        if requirement_runs:
            from core.intent.adjudication import adjudicate_requirements
            requirement_outcome = adjudicate_requirements(requirement_runs, review_findings)
            requirement_assessments = requirement_outcome.assessments
            requirement_investigations = requirement_outcome.investigations
            requirement_evidence = requirement_outcome.evidence
            source_observations = requirement_outcome.observations
            for run in requirement_runs:
                if run.status == "error":
                    health.stages.append(StageOutcome(stage=f"requirement:{run.requirement.id}", status="failed", code="invalid_or_failed_assessment"))
                    if health.status == "completed":
                        health.status = "partial"
        elif intent is not None and requirement_strategy == "link" and not static_only:
            from core.intent.service import assess_verified_findings
            def complete_requirement(prompt: str) -> str:
                self.budget.reserve(prompt)
                if self.verification_llm is not None or self.llm is not None:
                    return str((self.verification_llm or self.llm)(prompt))
                from core.gateway.gateway import AIGateway
                response = AIGateway().generate(prompt=prompt, capability="correctness_review",
                    agent_name="RequirementAssessor", temperature=0.0, max_tokens=64, retries=1)
                self.verification_usage.append(response.telemetry.model_dump(mode="json"))
                return str(response.content or "")
            requirement_assessments, requirement_investigations, requirement_evidence = assess_verified_findings(
                intent, review_findings,
                ReviewTarget(head_sha=str(getattr(ctx, "pr_head_sha", "") or "")), complete_requirement,
            )
        elif intent is not None:
            from core.domain.review_contracts import RequirementAssessment
            requirement_assessments = [RequirementAssessment(requirement_id=item.id, status="not_assessed",
                reason="Requirement model assessment disabled") for item in intent.items]
        observation_index = {observation.id: observation for observation in source_observations}
        observation_index.update(source_verifier.observations)
        source_observations = list(observation_index.values())
        from core.domain.review_contracts import EvidenceRecord
        for record in source_verifier.records:
            health.stages.append(StageOutcome(stage=f"finding_verifier:{record.candidate_id}",
                status="succeeded" if record.status == "completed" else "degraded", code=record.status))
            if record.status != "completed" and health.status == "completed":
                health.status = "partial"
            if record.verdict != "supported":
                continue
            for finding in review_findings:
                if finding.candidate_id != record.candidate_id:
                    continue
                for citation in record.decision.supporting_citations:
                    observation = observation_index[citation.observation_id]
                    eid = "EF-" + hashlib.sha256(f"{record.id}:{observation.id}".encode()).hexdigest()[:24]
                    if eid in finding.evidence_ids:
                        continue
                    requirement_evidence.append(EvidenceRecord(id=eid, kind="contract",
                        source_ref=f"{observation.path}:{observation.start_line}-{observation.end_line}",
                        content_hash=observation.excerpt_sha256, revision_sha=observation.revision_sha,
                        revision_side=observation.revision_side, observation_refs=(observation.id,),
                        supports_claim_refs=(finding.id,),
                        limitations=("Source-grounded model verification; not execution or formal proof.",)))
                    finding.evidence_ids.append(eid)
        unresolved.extend({"requirement_id": item.requirement_id, "reason": item.reason}
                          for item in requirement_assessments if item.status in {"unverified", "not_assessed"})
        with timed(timing, "policy"):
            outcome = evaluate_policy(health=health, coverage=inspection, findings=review_findings,
                unresolved=unresolved, execution=execution, classification=classif)
        decision, policy_reason = outcome.decision, outcome.reasons[0]
        pipeline_health.update(healthy=health.status == "completed", status=health.status, inspection_ratio=inspection.inspection_ratio)
        timing.total_s = sum(
            timing.to_dict()[k] for k in timing.to_dict() if k != "total_s"
        )
        packed = int(coverage.get("units_packed") or 0)
        total = int(coverage.get("units_total") or 0)
        print(
            f"[Coverage] packed={packed} total={total} ratio={ratio:.2f} "
            f"low={str(low).lower()} (observational)"
        )
        print(f"[Review] Decision={decision} reason={policy_reason}")

        # Print pipeline trace summary
        ts = trace.summary()
        print(
            f"[Trace] candidates={ts.get('total_candidates', 0)} "
            f"final={ts.get('final_findings', 0)} "
            f"drop_reasons={ts.get('drop_reasons', {})}"
        )

        return ReviewResult(
            decision=decision,
            policy_reason=policy_reason,
            comments=comments,
            dropped=dropped,
            bundles=bundles,
            coverage=coverage,
            execution=execution,
            findings=review_findings,
            pipeline_trace=trace,
            timing=timing,
            agent_runs=agent_runs,
            pipeline_health=pipeline_health,
            target=ReviewTarget(repo=repo_name, number=int(getattr(ctx, "number", 0) or 0),
                head_sha=str(getattr(ctx, "pr_head_sha", "") or ""),
                base_sha=str(getattr(ctx, "pr_base_sha", "") or ""),
                comparison_base_sha=str(verification_snapshot.comparison_base_sha or "") if verification_snapshot else "",
                diff_sha256=hashlib.sha256(diff.encode()).hexdigest()),
            health=health, inspection=inspection, unresolved=unresolved,
            approval_eligible=outcome.approval_eligible, policy_reasons=outcome.reasons,
            provenance={**_provenance(self.agent), "budget": self.budget.to_dict(),
                        "investigation_source": "git_snapshot" if investigation_snapshot is not None else "unavailable" if prepared_pr else "legacy_checkout",
                        "model_calls": [*getattr(self.agent, "usage_records", []), *self.verification_usage],
                        "requirement_strategy": requirement_strategy,
                        "requirement_runs": [run.to_dict() for run in requirement_runs],
                        "finding_verifier_mode": self.finding_verifier_mode,
                        "finding_source_rules": self.finding_source_rules,
                        "source_preparation": getattr(ctx, "source_preparation", None),
                        **({"verification_snapshot_id": verification_snapshot.id,
                            "verification_snapshot": verification_snapshot.model_dump(mode="json")}
                           if verification_snapshot else {}),
                        **({"input_snapshot": snapshot.model_dump(), "snapshot_id": snapshot.id,
                            "source_input_id": snapshot.source_id}
                           if snapshot is not None else {})},
            intent_sources=[intent.source] if intent is not None else [],
            requirements=intent.requirements if intent is not None else [],
            requirement_assessments=requirement_assessments,
            investigations=requirement_investigations, evidence=requirement_evidence,
            source_observations=source_observations,
            finding_verifications=list(source_verifier.records),
        )


def _provenance(agent: Any) -> dict:
    from core.agent.bundle_agent import PROMPT_VERSION
    from config import settings
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = "", None
    import os
    records = list(getattr(agent, "usage_records", []) or [])
    model = records[-1]["model"] if records else (os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        if settings.llm_backend == "openai" else settings.ollama_model)
    return {"reviewer_commit": commit, "dirty": dirty, "prompt_version": PROMPT_VERSION,
            "provider": getattr(settings, "llm_backend", "ollama"),
            "model": model, "model_calls": records}


def _execution_evidence(execution: Dict[str, Any]):
    """Translate legacy execution reports into per-finding evidence."""
    from core.review.finding import ExecutionEvidence

    skipped = bool(execution.get("skipped", True))
    reason = str(execution.get("skip_reason") or "")
    if skipped:
        status = "TIMEOUT" if reason == "timeout" else (
            "INSTALL_FAILED" if "install" in reason else "SKIPPED"
        )
    elif execution.get("exit_code") == 0 and not execution.get("failed"):
        status = "PASSED"
    else:
        status = "FAILED"
    return ExecutionEvidence(
        status=status,
        sandbox=False,
        environment=str(execution.get("python_env") or execution.get("env") or ""),
        command=str(execution.get("cmd") or ""),
        exit_code=execution.get("exit_code"),
        passed=execution.get("passed"),
        failed=execution.get("failed"),
        duration_seconds=execution.get("elapsed_s"),
        failed_tests=list(execution.get("failed_names") or []),
    )
