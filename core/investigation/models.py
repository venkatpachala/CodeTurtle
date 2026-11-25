"""Operations and evidence records used by Graphify lookups."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


class GraphOp(str, Enum):
    GET_NODE = "get_node"
    FIND_CALLERS = "find_callers"
    FIND_CALLEES = "find_callees"
    FIND_TESTS = "find_tests"
    PR_IMPACT = "pr_impact"
    GET_NEIGHBORS = "get_neighbors"


class EvidenceItem(BaseModel):
    id: str
    source: Literal["graphify", "diff", "github"] = "graphify"
    kind: Literal[
        "query", "node", "neighbors", "pr_impact", "hunk", "callers", "callees", "tests"
    ] = "query"
    path: str = ""
    symbol: Optional[str] = None
    text: str = ""
