from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from core.repository_knowledge.models import (
    GraphNode,
    GraphStats,
    KnowledgeQueryResult,
    NeighborResult,
    PathResult,
    PRImpact,
)
from core.repository_knowledge.provider import RepositoryKnowledgeProvider


class GraphifyMCPError(RuntimeError):
    pass


class GraphifyMCPProvider(RepositoryKnowledgeProvider):
    """
    Graphify adapter.

    Transport:
      - stdio: spawn `python -m graphify.serve <graph.json>`
      - http:  connect to GRAPHIFY_HTTP_URL (default http://localhost:8080/mcp)
    """

    def __init__(
        self,
        graph_path: str = "graphify-out/graph.json",
        transport: str = "stdio",
        http_url: str = "http://localhost:8080/mcp",
        python_executable: str = "python",
        project_path: Optional[str] = None,
        timeout_s: float = 45.0,
    ):
        self.graph_path = graph_path
        self.transport = transport.lower()
        self.http_url = http_url
        self.python_executable = python_executable
        self.project_path = project_path
        self.timeout_s = timeout_s

    def healthcheck(self) -> str:
        tools = self.list_tools()
        stats = self.graph_stats()
        return (
            f"Graphify MCP OK | transport={self.transport} | "
            f"tools={len(tools)} | stats_preview={stats.raw_text[:120]!r}"
        )

    def list_tools(self) -> List[str]:
        result = self._run(self._list_tools_async())
        return result

    def query(self, question: str, depth: int = 3) -> KnowledgeQueryResult:
        args: Dict[str, Any] = {"question": question, "mode": "bfs", "depth": depth}
        raw = self._call_tool("query_graph", args)
        return KnowledgeQueryResult(question=question, raw_text=raw)

    def get_node(self, label: str) -> Optional[GraphNode]:
        raw = self._call_tool("get_node", {"label": label})
        if not raw or "not found" in raw.lower():
            return None
        return GraphNode(id=label, label=label, raw={"text": raw})

    def get_neighbors(
        self,
        label: str,
        relation_filter: Optional[str] = None,
    ) -> NeighborResult:
        args: Dict[str, Any] = {"label": label}
        if relation_filter:
            args["relation_filter"] = relation_filter
        raw = self._call_tool("get_neighbors", args)
        return NeighborResult(
            node=GraphNode(id=label, label=label),
            raw_text=raw,
        )

    def shortest_path(self, source: str, target: str, max_hops: int = 8) -> PathResult:
        raw = self._call_tool(
            "shortest_path",
            {"source": source, "target": target, "max_hops": max_hops},
        )
        hops = [part.strip() for part in raw.replace("→", "->").split("->") if part.strip()]
        return PathResult(
            source=source,
            target=target,
            hops=hops,
            raw_text=raw,
            found=bool(hops) and "no path" not in raw.lower(),
        )

    def graph_stats(self) -> GraphStats:
        raw = self._call_tool("graph_stats", {})
        return GraphStats(raw_text=raw)

    def get_pr_impact(self, pr_number: int, repo: Optional[str] = None) -> PRImpact:
        args: Dict[str, Any] = {"pr_number": pr_number}
        if repo:
            args["repo"] = repo
        raw = self._call_tool("get_pr_impact", args)
        return PRImpact(pr_number=pr_number, repo=repo, raw_text=raw)

    def get_community(self, community_id: int) -> str:
        return self._call_tool("get_community", {"community_id": community_id})

    def god_nodes(self, top_n: int = 10) -> str:
        return self._call_tool("god_nodes", {"top_n": top_n})

    def list_prs(self, repo: Optional[str] = None, base: Optional[str] = None) -> str:
        args: Dict[str, Any] = {}
        if repo:
            args["repo"] = repo
        if base:
            args["base"] = base
        return self._call_tool("list_prs", args)

    def triage_prs(self, repo: Optional[str] = None, base: Optional[str] = None) -> str:
        args: Dict[str, Any] = {}
        if repo:
            args["repo"] = repo
        if base:
            args["base"] = base
        return self._call_tool("triage_prs", args)

    def _call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if self.project_path:
            arguments = {**arguments, "project_path": self.project_path}
        return self._run(self._call_tool_async(name, arguments))

    def _run(self, coro):
        try:
            return asyncio.run(asyncio.wait_for(coro, timeout=self.timeout_s))
        except TimeoutError as exc:
            raise GraphifyMCPError(
                f"Graphify MCP timed out after {self.timeout_s}s "
                f"(transport={self.transport})"
            ) from exc
        except Exception as exc:
            raise GraphifyMCPError(str(exc)) from exc

    async def _list_tools_async(self) -> List[str]:
        async with self._session() as session:
            tools = await session.list_tools()
            return [t.name for t in tools.tools]

    async def _call_tool_async(self, name: str, arguments: Dict[str, Any]) -> str:
        async with self._session() as session:
            result = await session.call_tool(name, arguments)
            return _extract_text(result)

    def _session(self):
        if self.transport == "http":
            return _HttpSession(self.http_url)
        return _StdioSession(self.python_executable, self.graph_path)


class _StdioSession:
    def __init__(self, python_executable: str, graph_path: str):
        self.python_executable = python_executable
        self.graph_path = graph_path
        self._cm = None
        self._session = None

    async def __aenter__(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.python_executable,
            args=["-m", "graphify.serve", self.graph_path],
        )
        self._cm = stdio_client(params)
        read, write = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.__aexit__(exc_type, exc, tb)
        if self._cm:
            await self._cm.__aexit__(exc_type, exc, tb)


class _HttpSession:
    def __init__(self, url: str):
        self.url = url
        self._cm = None
        self._session = None

    async def __aenter__(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._cm = streamablehttp_client(self.url)
        read, write, _ = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.__aexit__(exc_type, exc, tb)
        if self._cm:
            await self._cm.__aexit__(exc_type, exc, tb)


def _extract_text(result: Any) -> str:
    parts: List[str] = []
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    for item in content:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
        else:
            parts.append(str(item))
    return "\n".join(parts).strip()


def dumps_pretty(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return json.dumps(obj, indent=2, default=str)