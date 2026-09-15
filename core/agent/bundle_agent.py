"""One LLM agent per bundle. Max 4 steps. Never sets MERGE/COMMENT/REQUEST_CHANGES."""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

from core.agent.parse import candidate_dict, parse_agent_output
from core.agent.tools import BundleTools
from core.runtime.models import Bundle, Candidate

MAX_STEPS = 4

_SYSTEM = """You review one code bundle from a pull request.
You may call one tool at a time by outputting JSON:
{"tool":"read_hunk","path":"..."}
{"tool":"graph_node","symbol":"..."}
{"tool":"graph_callers","symbol":"..."}
{"tool":"graph_tests","symbol":"..."}
Symbols are identifiers (Foo.bar ok). No slashes, not "py", not *.py paths.
read_hunk path must be a file in this bundle.

Return [] if you cannot name a violating_condition.
Do not emit Potential/may/might as defects.
existing_code must be copied from the hunk.
execution_path is function names in call order.
If a test in this bundle already asserts the invariant, do not file that defect.
Do NOT emit a finding because a function, flag, type, or test was added.
A finding must state what can go WRONG (break, leak, wrong default, missing guard).

When finished, output a JSON list:
[{"bundle_id":"...","file":"...","symbol":"...","start_line":0,"title":"...","claim":"...","existing_code":"...","invariant":"...","violating_condition":"...","expected":"...","actual":"...","execution_path":["fn"],"evidence":["file"],"severity":"medium","confidence":0.7,"source":"agent","kind":"defect"}]
or [].
Do not output MERGE, COMMENT, or REQUEST_CHANGES.
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
            temperature=0.1,
            max_tokens=800,
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
        if history:
            body += "\n\nTool results:\n" + "\n".join(history)
        body += "\n\nRespond with JSON only."
        return body

    def run(self, bundle: Bundle, tools: Optional[BundleTools] = None) -> List[Candidate]:
        history: List[str] = []
        tools = tools or BundleTools(bundle)
        try:
            for _ in range(self.max_steps):
                raw = self._complete(self._prompt(bundle, history))
                kind, payload = parse_agent_output(raw)
                if kind == "candidates":
                    out: List[Candidate] = []
                    for item in payload or []:
                        d = candidate_dict(item, bundle_id=bundle.id)
                        if not d:
                            continue
                        out.append(Candidate(**d))
                    return out
                if kind == "tool":
                    result = tools.dispatch(payload if isinstance(payload, dict) else {})
                    history.append(
                        json.dumps({"tool": (payload or {}).get("tool"), "result": result})[:2000]
                    )
                    continue
                return []
        except Exception:
            return []
        return []
