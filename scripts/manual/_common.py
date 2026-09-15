"""
Shared helpers used by every manual_tests/NN_test_*.py script.

What this gives you:
  - force_local_models(): reroutes every AIGateway capability to your local
    Ollama model so you can iterate on prompts for free, without an
    OPENAI_API_KEY. Comment out the call in a script if you want to test the
    real (mixed local/cloud) routing from core/gateway/gateway.py instead.
  - load_state() / save_state(): a JSON file (manual_tests/outputs/state.json)
    that mimics how LangGraph's ReviewState accumulates fields across nodes.
    Run the scripts in order (01 -> 09) and each one reads what the previous
    agent actually produced and appends its own real output — exactly what
    happens inside core/graph.py, just one node at a time so you can inspect
    and edit prompts between steps.
  - print_stage(): prints the full raw structured output of whichever agent
    just ran, so you see exactly what gets handed to the next agent.
"""

import json
import os
import sys
from typing import Any

from pydantic import BaseModel

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
OUTPUTS_DIR = os.path.join(THIS_DIR, "outputs")
STATE_PATH = os.path.join(OUTPUTS_DIR, "state.json")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.makedirs(OUTPUTS_DIR, exist_ok=True)


def _jsonable(value: Any) -> Any:
    """Recursively convert pydantic models / lists of them into plain JSON."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r") as f:
        return json.load(f)


def save_state(partial: dict) -> dict:
    """Merge a node's return dict into state.json, same semantics as LangGraph's
    default reducer (overwrite), except 'traces' which accumulates like the real
    ReviewState does via operator.add."""
    state = load_state()
    for key, value in partial.items():
        value = _jsonable(value)
        if key == "traces":
            state.setdefault("traces", [])
            state["traces"].extend(value)
        else:
            state[key] = value
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)
    return state


def reset_state():
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)


def print_stage(agent_name: str, output: dict):
    print(f"\n{'=' * 70}\n  RAW OUTPUT — {agent_name}\n{'=' * 70}")
    for key, value in output.items():
        if key == "traces":
            continue
        print(f"\n--- {key} ---")
        print(json.dumps(_jsonable(value), indent=2, default=str))
    print(f"\n{'=' * 70}\n")


def force_local_models():
    """Reroute every AIGateway capability to your local Ollama model.
    Call this BEFORE importing anything from core.agents in your script,
    since core/agents.py builds a module-level `gateway = AIGateway()` on import."""
    from config import settings
    from core.gateway.gateway import AIGateway

    original_init = AIGateway.__init__

    def patched_init(self):
        original_init(self)
        for capability in self.model_registry:
            self.model_registry[capability] = {
                "provider": "ollama",
                "model": settings.ollama_model,
            }

    AIGateway.__init__ = patched_init
