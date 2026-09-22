"""One LLM agent per bundle. Max 4 steps. Never sets MERGE/COMMENT/REQUEST_CHANGES."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from core.agent.parse import candidate_dict, parse_agent_output
from core.agent.hypothesis import ReviewHypothesis, hypothesis_dict
from core.agent.tools import BundleTools
from core.runtime.models import Bundle, Candidate

MAX_STEPS = 4
PROMPT_VERSION = "hypothesis-proof-v1"


@dataclass
class AgentRunResult:
    """Auditable outcome of one bundle investigation.

    ``candidates=[]`` is intentionally not enough information for benchmark
    analysis: it can mean a healthy no-finding review or a broken model/tool
    interaction.  This object makes that distinction explicit.
    """

    status: str
    candidates: List[Candidate] = field(default_factory=list)
    raw_outputs: List[str] = field(default_factory=list)
    tool_calls: List[dict[str, Any]] = field(default_factory=list)
    hypotheses: List[ReviewHypothesis] = field(default_factory=list)
    evidence_items: List[dict[str, Any]] = field(default_factory=list)
    stage_status: dict[str, str] = field(default_factory=dict)
    parse_error: str | None = None
    exception: str | None = None
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_count": len(self.candidates),
            "raw_outputs": list(self.raw_outputs),
            "tool_calls": list(self.tool_calls),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "hypothesis_count": len(self.hypotheses),
            "evidence_items": list(self.evidence_items),
            "evidence_count": len(self.evidence_items),
            "stage_status": dict(self.stage_status),
            "parse_error": self.parse_error,
            "exception": self.exception,
            "latency_ms": round(self.latency_ms, 2),
            "prompt_version": PROMPT_VERSION,
            "model_calls": len(self.raw_outputs),
            "estimated_completion_tokens": sum(max(1, len(x) // 4) for x in self.raw_outputs),
        }

_SYSTEM = """You review one code bundle from a pull request.
You may call one tool at a time by outputting JSON:
{"tool":"read_hunk","path":"..."}
{"tool":"graph_node","symbol":"..."}
{"tool":"graph_callers","symbol":"..."}
{"tool":"graph_callees","symbol":"..."}
{"tool":"graph_tests","symbol":"..."}
{"tool":"callee_contract","symbol":"ClassName.method"}
Symbols are identifiers (Foo.bar ok). No slashes, not "py", not *.py paths.
read_hunk path must be a file in this bundle.

Return [] if you cannot name a violating_condition.
Do not emit Potential/may/might as defects.
existing_code must be copied from the hunk.
start_line must be the line of existing_code in the hunk, not the first line of the file.
execution_path is function names in call order.
If existing_code is the guard that enforces the invariant (raise, Error print, assert), that is NOT a defect — return [].
If a test in this bundle already asserts the invariant, do not file that defect.
Do NOT emit a finding because a function, flag, type, or test was added.
A finding must state where the invariant is VIOLATED, not that the invariant exists.

When finished, output a JSON list:
[{"bundle_id":"...","file":"...","symbol":"...","start_line":0,"title":"...","claim":"...","existing_code":"...","invariant":"...","violating_condition":"...","expected":"...","actual":"...","execution_path":["fn"],"evidence":["file"],"severity":"medium","confidence":0.7,"source":"agent","kind":"defect"}]
or [].
Do not output MERGE, COMMENT, or REQUEST_CHANGES.
"""

_DISCOVERY_SYSTEM = """You are the high-recall discovery stage of a code review.
Identify 1-5 concrete behavioral regression hypotheses caused by the changed code.
A hypothesis is an investigation lead, not a final review comment. Uncertainty is allowed.
Prefer correctness, security, data loss, API contract, concurrency, and performance failures.
Do not report naming, style, documentation, or merely missing tests.
Every hypothesis must name a changed file and quote a concrete observation from the diff.
Static risk signals are deterministic leads, not automatically defects. Prioritize them
when their stated execution path is real, and request the evidence they specify.
Return JSON only:
{"hypotheses":[{"file":"...","symbol":"...","category":"correctness",
"observation":"...","hypothesis":"...","why_investigate":"...",
"required_evidence":["source","callers","tests"],"confidence":0.6}]}
Return {"hypotheses":[]} only when no behavioral risk is visible.
"""

_PROOF_SYSTEM = """You are the proof-construction stage of a code review.
For each supplied hypothesis, use only the supplied diff/source/graph evidence.
Omit hypotheses that are contradicted or unsupported. Never invent files or lines.
For a supported defect, existing_code must be copied exactly from an added diff line;
start_line is its right-side line. State a concrete violating condition and observable impact.
Use direct defect language: do not write potential, may, might, or could.
The evidence field is a JSON list of changed repository file paths, never explanatory prose.
The execution_path field is a JSON list of function or method identifiers in call order.
Return a JSON list of proof-complete findings with fields:
bundle_id,file,symbol,start_line,title,claim,existing_code,invariant,
violating_condition,expected,actual,execution_path,evidence,severity,confidence,source,kind.
Return [] if none can be supported.
"""


class BundleAgent:
    def __init__(
        self,
        llm: Optional[Callable[[str], str]] = None,
        *,
        max_steps: int = MAX_STEPS,
    ):
        self.llm = llm
        self.max_steps = max(1, int(max_steps or MAX_STEPS))

    def _complete(self, prompt: str) -> str:
        if self.llm is not None:
            return str(self.llm(prompt) or "")
        from core.gateway.gateway import AIGateway

        gw = AIGateway()
        resp = gw.generate(
            prompt=prompt,
            capability="correctness_review",
            agent_name="BundleAgent",
            temperature=0.0,
            max_tokens=1400,
            retries=1,
        )
        return str(getattr(resp, "content", None) or "")

    def _prompt(self, bundle: Bundle, history: List[str]) -> str:
        units_bits = []
        for u in (bundle.units or [])[:12]:
            if isinstance(u, dict):
                path = u.get("path")
                excerpt = str(u.get("excerpt") or "")[:400]
                symbols = u.get("symbols") or []
            else:
                path = getattr(u, "path", "")
                excerpt = str(getattr(u, "excerpt", "") or "")[:400]
                symbols = getattr(u, "symbols", None) or []
            units_bits.append(f"{path} symbols={list(symbols)}\n{excerpt}")
        body = (
            f"{_SYSTEM}\n"
            f"bundle_id={bundle.id} kind={bundle.kind}\n"
            f"paths={list(bundle.paths)}\n"
            f"symbols={list(bundle.symbols)}\n"
            f"units:\n" + "\n---\n".join(units_bits[:8])
        )
        if bundle.risk_signals:
            body += "\n\nStatic risk signals:\n" + json.dumps(bundle.risk_signals, indent=2)[:5000]
        if history:
            body += "\n\nTool results:\n" + "\n".join(history)
        body += "\n\nRespond with JSON only."
        return body

    def _discovery_prompt(self, bundle: Bundle, history: List[str]) -> str:
        body = self._prompt(bundle, history)
        return body.replace(_SYSTEM, _DISCOVERY_SYSTEM)

    @staticmethod
    def _candidate_shaped(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        return bool(set(item) & {
            "title", "start_line", "existing_code", "invariant",
            "violating_condition", "expected", "actual", "execution_path",
        })

    def _parse_candidates(self, payload: Any, bundle: Bundle) -> tuple[List[Candidate], int]:
        out: List[Candidate] = []
        invalid = 0
        for item in payload or []:
            d = candidate_dict(item, bundle_id=bundle.id)
            if not d:
                invalid += 1
                continue
            out.append(Candidate(**d))
        return out, invalid

    def _parse_hypotheses(self, payload: Any, bundle: Bundle) -> tuple[List[ReviewHypothesis], int]:
        out: List[ReviewHypothesis] = []
        invalid = 0
        allowed = {str(p).replace("\\", "/") for p in bundle.paths}
        seen: set[tuple[str, str, str]] = set()
        for index, item in enumerate(payload or [], start=1):
            d = hypothesis_dict(item, bundle_id=bundle.id, index=index)
            if not d:
                invalid += 1
                continue
            if d["file"] not in allowed:
                basename = d["file"].split("/")[-1]
                matches = [p for p in allowed if p.endswith("/" + d["file"]) or p.split("/")[-1] == basename]
                if len(matches) != 1:
                    invalid += 1
                    continue
                d["file"] = matches[0]
            key = (d["file"], d["symbol"].lower(), d["hypothesis"].lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ReviewHypothesis(**d))
        return out[:5], invalid

    @staticmethod
    def _signal_hypotheses(bundle: Bundle) -> List[ReviewHypothesis]:
        """Turn deterministic signals into investigation leads, never findings."""
        out: List[ReviewHypothesis] = []
        for index, signal in enumerate(bundle.risk_signals or [], start=1):
            if not isinstance(signal, dict) or not signal.get("file") or not signal.get("description"):
                continue
            out.append(ReviewHypothesis(
                id=f"S-{index:03d}",
                bundle_id=bundle.id,
                file=str(signal["file"]),
                symbol=str(signal.get("symbol") or ""),
                category="correctness",
                observation=" | ".join(str(item) for item in (signal.get("evidence") or [])[:3]),
                hypothesis=str(signal["description"]),
                why_investigate="Deterministic structural analysis identified this execution path; verify its behavioral consequence.",
                required_evidence=list(signal.get("required_evidence") or ["source"]),
                confidence=float(signal.get("confidence") or 0.5),
            ))
        return out

    @staticmethod
    def _merge_hypotheses(
        signal_hypotheses: List[ReviewHypothesis], model_hypotheses: List[ReviewHypothesis],
    ) -> List[ReviewHypothesis]:
        out: List[ReviewHypothesis] = []
        seen: set[tuple[str, str]] = set()
        for hypothesis in [*signal_hypotheses, *model_hypotheses]:
            key = (hypothesis.file, hypothesis.symbol.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(hypothesis)
        return out[:5]

    def _collect_evidence(
        self, hypotheses: List[ReviewHypothesis], tools: BundleTools,
        tool_calls: List[dict[str, Any]],
    ) -> List[dict[str, Any]]:
        evidence: List[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for hyp in hypotheses:
            requests = set(hyp.required_evidence or ["source"])
            requests.add("source")
            planned: List[dict[str, str]] = []
            if "source" in requests:
                planned.append({"tool": "read_hunk", "path": hyp.file})
            if hyp.symbol:
                if "symbol" in requests:
                    planned.append({"tool": "graph_node", "symbol": hyp.symbol})
                if "callers" in requests:
                    planned.append({"tool": "graph_callers", "symbol": hyp.symbol})
                if "callees" in requests:
                    planned.append({"tool": "graph_callees", "symbol": hyp.symbol})
                if "tests" in requests:
                    planned.append({"tool": "graph_tests", "symbol": hyp.symbol})
            bundle_signals = list(getattr(tools.bundle, "risk_signals", None) or [])
            for signal in bundle_signals:
                if (
                    isinstance(signal, dict)
                    and signal.get("kind") == "cross_file_argument_contract"
                    and str(signal.get("file") or "") == hyp.file
                    and str(signal.get("symbol") or "")
                ):
                    planned.append({"tool": "callee_contract", "symbol": str(signal["symbol"])})
            for request in planned:
                target = request.get("path") or request.get("symbol") or ""
                key = (request["tool"], target)
                if key in seen or len(tool_calls) >= 12:
                    continue
                seen.add(key)
                result = tools.dispatch(request)
                record = {"hypothesis_id": hyp.id, "request": request, "result": result}
                tool_calls.append(record)
                if not (isinstance(result, dict) and result.get("error")):
                    evidence.append(record)
        return evidence

    def _proof_prompt(
        self, bundle: Bundle, hypotheses: List[ReviewHypothesis], evidence: List[dict[str, Any]],
    ) -> str:
        payload = {
            "bundle_id": bundle.id,
            "allowed_paths": list(bundle.paths),
            "hypotheses": [h.to_dict() for h in hypotheses],
            "evidence": evidence,
            "risk_signals": list(bundle.risk_signals or []),
        }
        return f"{_PROOF_SYSTEM}\n\nInvestigation package:\n{json.dumps(payload)[:12000]}\n\nJSON only."

    def run_result(self, bundle: Bundle, tools: Optional[BundleTools] = None) -> AgentRunResult:
        history: List[str] = []
        tools = tools or BundleTools(bundle)
        raw_outputs: List[str] = []
        tool_calls: List[dict[str, Any]] = []
        started = time.perf_counter()
        try:
            for _ in range(self.max_steps):
                raw = self._complete(self._discovery_prompt(bundle, history))
                raw_outputs.append(raw)
                kind, payload = parse_agent_output(raw)
                if kind == "candidates":
                    signal_hypotheses = self._signal_hypotheses(bundle)
                    if not payload and not signal_hypotheses:
                        return AgentRunResult(
                            status="VALID_EMPTY", raw_outputs=raw_outputs, tool_calls=tool_calls,
                            stage_status={"discovery": "VALID_EMPTY"},
                            latency_ms=(time.perf_counter() - started) * 1000,
                        )
                    if payload and any(self._candidate_shaped(item) for item in payload):
                        out, invalid_items = self._parse_candidates(payload, bundle)
                        status = "VALID_CANDIDATES" if out else "INVALID_SCHEMA"
                        return AgentRunResult(
                            status=status, candidates=out, raw_outputs=raw_outputs,
                            tool_calls=tool_calls, stage_status={"discovery": "LEGACY_CANDIDATES"},
                            parse_error="all candidate objects were invalid" if invalid_items and not out else None,
                            latency_ms=(time.perf_counter() - started) * 1000,
                        )
                    hypotheses, invalid_items = self._parse_hypotheses(payload, bundle) if payload else ([], 0)
                    hypotheses = self._merge_hypotheses(signal_hypotheses, hypotheses)
                    if not hypotheses:
                        return AgentRunResult(
                            status="INVALID_SCHEMA", raw_outputs=raw_outputs, tool_calls=tool_calls,
                            stage_status={"discovery": "INVALID_SCHEMA"},
                            parse_error="all hypothesis objects were invalid",
                            latency_ms=(time.perf_counter() - started) * 1000,
                        )
                    evidence = self._collect_evidence(hypotheses, tools, tool_calls)
                    proof_raw = self._complete(self._proof_prompt(bundle, hypotheses, evidence))
                    raw_outputs.append(proof_raw)
                    proof_kind, proof_payload = parse_agent_output(proof_raw)
                    if proof_kind != "candidates":
                        return AgentRunResult(
                            status="INVALID_JSON", raw_outputs=raw_outputs, tool_calls=tool_calls,
                            hypotheses=hypotheses, evidence_items=evidence,
                            stage_status={"discovery": "VALID_HYPOTHESES", "proof": "INVALID_JSON"},
                            parse_error="proof response did not contain a JSON candidate list",
                            latency_ms=(time.perf_counter() - started) * 1000,
                        )
                    out, invalid_proofs = self._parse_candidates(proof_payload, bundle)
                    status = "VALID_CANDIDATES" if out else (
                        "INVALID_SCHEMA" if invalid_proofs else "VALID_EMPTY"
                    )
                    return AgentRunResult(
                        status=status, candidates=out, raw_outputs=raw_outputs,
                        tool_calls=tool_calls, hypotheses=hypotheses, evidence_items=evidence,
                        stage_status={
                            "discovery": "VALID_HYPOTHESES",
                            "evidence": "AVAILABLE" if evidence else "EMPTY",
                            "proof": status,
                        },
                        parse_error="all proof objects were invalid" if invalid_proofs and not out else None,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                if kind == "tool":
                    result = tools.dispatch(payload if isinstance(payload, dict) else {})
                    tool_calls.append({"request": payload, "result": result})
                    history.append(
                        json.dumps({"tool": (payload or {}).get("tool"), "result": result})[:2000]
                    )
                    continue
                return AgentRunResult(
                    status="INVALID_JSON", raw_outputs=raw_outputs, tool_calls=tool_calls,
                    parse_error="response did not contain a supported JSON list or tool call",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
        except Exception as exc:
            return AgentRunResult(
                status="EXCEPTION", raw_outputs=raw_outputs, tool_calls=tool_calls,
                exception=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        return AgentRunResult(
            status="MAX_STEPS", raw_outputs=raw_outputs, tool_calls=tool_calls,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def run(self, bundle: Bundle, tools: Optional[BundleTools] = None) -> List[Candidate]:
        """Compatibility API for callers that have not migrated to run_result."""
        return self.run_result(bundle, tools).candidates
